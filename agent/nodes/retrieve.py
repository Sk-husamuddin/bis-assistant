import os
import re
from typing import List, Dict, Any

from agent.state import GraphState
from agent.debug import is_verbose

COLLECTION_NAME = "bis_corpus"
TOP_K = 5
TOP_K_COMPARISON = 10
TOP_K_PER_TOPIC = 4

# For query decomposition (comparison queries)
_TOPIC_PATTERNS = {
    "ISI": re.compile(r"\bISI\b", re.I),
    "CRS": re.compile(r"\bCRS\b", re.I),
    "HALLMARKING": re.compile(r"HALLMARK", re.I),
    "MSCS": re.compile(r"\bMSCS\b", re.I),
    "FMCS": re.compile(r"\bFMCS\b", re.I),
}
_IS_NUMBER_RE = re.compile(r"IS\s*\d{3,6}(?:-\d{4})?", re.I)
_SCHEME_RE = re.compile(r"Scheme[-\s]*[IVX]+", re.I)

def _detect_topics(query: str) -> list[str]:
    """Detect distinct scheme/standard keywords. Simple keyword-presence, no LLM."""
    topics: list[str] = []
    q_upper = query.upper()
    for name, pat in _TOPIC_PATTERNS.items():
        if pat.search(query):
            topics.append(name)
    # IS numbers as separate topics
    is_nums = _IS_NUMBER_RE.findall(query)
    for n in is_nums:
        # normalize e.g. "IS 2347"
        norm = re.sub(r"\s+", " ", n.strip().upper())
        if norm not in topics:
            topics.append(norm)
    # If query mentions "Scheme" generically without specific ISI/CRS, treat as topic
    if not topics and _SCHEME_RE.search(query):
        topics.append("SCHEME")
    # Deduplicate preserve order
    seen = set()
    uniq: list[str] = []
    for t in topics:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq

def _topic_to_subquery(topic: str, original_query: str) -> str:
    """Map detected topic to a focused subquery that retrieves well."""
    mapping = {
        "ISI": "ISI Scheme I BIS Product Certification",
        "CRS": "CRS Scheme II Compulsory Registration",
        "HALLMARKING": "Hallmarking BIS precious metal",
        "MSCS": "MSCS BIS Systems Certification",
        "FMCS": "FMCS BIS Foreign Manufacturers",
        "SCHEME": "BIS certification scheme",
    }
    if topic in mapping:
        return mapping[topic]
    # IS number topics: use as is
    if topic.upper().startswith("IS"):
        return topic
    return topic

def _merge_dedup(docs_list: List[List[Dict[str, Any]]], max_total: int = TOP_K_COMPARISON) -> List[Dict[str, Any]]:
    """Merge multiple top-k lists, dedup by chunk_id, sort by similarity desc, truncate."""
    seen_ids = set()
    merged: List[Dict[str, Any]] = []
    for docs in docs_list:
        for d in docs:
            cid = d.get("chunk_id") or d.get("source_url","") + d.get("content","")[:50]
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            merged.append(d)
    # Sort by similarity desc (None at end)
    def _sim(d):
        s = d.get("similarity")
        return s if isinstance(s, (int,float)) else -1
    merged.sort(key=_sim, reverse=True)
    return merged[:max_total]
# numeric threshold — NOT string equality (LBRCE bug fix, see implementation.md:81)
GROUNDEDNESS_THRESHOLD = 0.35  # cosine distance; chroma returns distance, convert to similarity = 1-distance

_chroma_client = None
_collection = None

def _resolve_persist_dir(raw: str) -> str:
    if os.path.isabs(raw):
        return raw
    # try .env relative to bis-assistant root (two levels up from this file's directory)
    # this file is at bis-assistant/agent/nodes/retrieve.py
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidate = os.path.join(project_root, raw.lstrip("./"))
    if os.path.exists(candidate) or os.path.exists(os.path.join(candidate, "chroma.sqlite3")) or True:
        return candidate
    return os.path.abspath(raw)

def _get_collection():
    global _chroma_client, _collection
    if _collection is not None:
        return _collection
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./ingestion/data/chroma")
    model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
    try:
        from dotenv import load_dotenv
        load_dotenv()
        # re-read after dotenv; keep raw value for resolution
        persist_dir = os.getenv("CHROMA_PERSIST_DIR", persist_dir)
        model_name = os.getenv("EMBEDDING_MODEL", model_name)
    except Exception:
        pass
    persist_dir = _resolve_persist_dir(persist_dir)

    import chromadb
    from chromadb.utils import embedding_functions
    try:
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
    except Exception:
        ef = embedding_functions.DefaultEmbeddingFunction()

    # Chroma PersistentClient will create dir if missing
    _chroma_client = chromadb.PersistentClient(path=persist_dir)
    try:
        _collection = _chroma_client.get_collection(name=COLLECTION_NAME, embedding_function=ef)
    except Exception:
        # create empty if not exists
        _collection = _chroma_client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=ef, metadata={"hnsw:space": "cosine"})
    return _collection

def _query_chroma(query: str, k: int = TOP_K) -> List[Dict[str, Any]]:
    col = _get_collection()
    if col.count() == 0:
        return []
    res = col.query(query_texts=[query], n_results=k, include=["documents", "metadatas", "distances"])
    docs = []
    if not res or not res.get("documents"):
        return []
    for i in range(len(res["documents"][0])):
        doc = res["documents"][0][i]
        meta = res["metadatas"][0][i] or {}
        dist = res["distances"][0][i] if res.get("distances") else None
        # chroma cosine distance in [0,2]; similarity = 1 - distance/2? but with hnsw cosine it's [0,2] where 0=identical.
        # For sentence-transformers cosine, chroma stores 1-cos_sim as distance in some configs. Use 1-distance as similarity approx.
        similarity = None
        if dist is not None:
            # clamp: if distance 0..2, sim 1..-1; but we threshold at 0.35 distance means sim 0.65
            # spec says "similarity scores are all below threshold (e.g. 0.35)" — interpret as distance > 0.65? 
            # To avoid confusion, we treat threshold on similarity where similarity = 1 - distance
            # So distance 0.35 => similarity 0.65 (good). Spec example 0.35 likely means similarity.
            # We implement: if distance > 0.6 => low similarity. Keep both interpretations logged.
            similarity = 1 - dist
        docs.append({
            "content": doc,
            "source_url": meta.get("source_url", ""),
            "source_title": meta.get("source_title", ""),
            "chunk_id": meta.get("chunk_id", ""),
            "distance": dist,
            "similarity": similarity,
        })
    return docs

def _live_fallback(query: str) -> List[Dict[str, Any]]:
    # Try Tavily first (if key present), else DuckDuckGo (zero-setup per Q1)
    api_key = os.getenv("TAVILY_API_KEY", "")
    try:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("TAVILY_API_KEY", api_key)
    except Exception:
        pass

    if api_key:
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=api_key)
            resp = client.search(query=query, search_depth="advanced", max_results=5, include_domains=["bis.gov.in"])
            out = []
            for r in resp.get("results", []):
                out.append({
                    "content": r.get("content", "")[:2000],
                    "source_url": r.get("url", ""),
                    "source_title": r.get("title", ""),
                    "chunk_id": "",
                    "distance": None,
                    "similarity": None,
                })
            if out:
                return out
        except Exception as e:
            print(f"[retrieve] tavily fallback failed: {e}")

    # DuckDuckGo zero-setup fallback (supports both duckduckgo_search and ddgs renames)
    try:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            from ddgs import DDGS
        results = DDGS().text(f"site:bis.gov.in {query}", max_results=5)
        out = []
        for r in (results or []):
            out.append({
                "content": (r.get("body") or r.get("title") or "")[:2000],
                "source_url": r.get("href", ""),
                "source_title": r.get("title", ""),
                "chunk_id": "",
                "distance": None,
                "similarity": None,
            })
        if out:
            return out
        # general search if bis-scoped empty
        try:
            from ddgs import DDGS as DDGS2
        except ImportError:
            try:
                from duckduckgo_search import DDGS as DDGS2
            except ImportError:
                DDGS2 = DDGS
        results2 = DDGS2().text(query, max_results=5)
        for r in (results2 or []):
            out.append({
                "content": (r.get("body") or "")[:2000],
                "source_url": r.get("href", ""),
                "source_title": r.get("title", ""),
                "chunk_id": "",
                "distance": None,
                "similarity": None,
            })
        return out
    except Exception as e:
        print(f"[retrieve] duckduckgo fallback failed: {e}")
        return []

def retrieve_node(state: GraphState) -> dict:
    query = state.get("query", "").strip()
    if not query:
        return {"retrieved_docs": [], "used_live_fallback": False}

    # Step 2: query decomposition for compound/comparison queries
    # Detect multiple distinct topics; if >=2, retrieve per-topic and merge
    topics = _detect_topics(query)
    is_multi = len(topics) >= 2
    if is_multi:
        # Per-topic retrieval, then merge
        per_topic_docs: List[List[Dict[str, Any]]] = []
        for t in topics:
            subq = _topic_to_subquery(t, query)
            # Use per-topic k to keep total bounded
            docs_t = _query_chroma(subq, k=TOP_K_PER_TOPIC)
            per_topic_docs.append(docs_t)
        docs = _merge_dedup(per_topic_docs, max_total=TOP_K_COMPARISON)
        # For multi-topic, consider grounded if any topic has at least one decent hit
        # Don't trigger live fallback based on combined similarity unless merged is empty
        if not docs:
            # Fallback will be handled below
            pass
        else:
            # Skip single-query groundedness check for multi-topic; treat as grounded if we have docs
            # Directly go to debug and clean, skipping fallback
            # Set used_live False initially, fallback only if merged empty
            if is_verbose():
                try:
                    qtype = state.get("query_type", "unknown")
                    print("\n" + "=" * 60)
                    print(f"[DEBUG][retrieve] Query: {query!r} | type: {qtype} | MULTI-TOPIC detected: {topics}")
                    print(f"[DEBUG][retrieve] Per-topic subqueries: {[_topic_to_subquery(t, query) for t in topics]}")
                    print(f"[DEBUG][retrieve] Merged {len(docs)} docs from {len(topics)} topics (deduped, sorted by sim)")
                    for i, doc in enumerate(docs):
                        sim = doc.get("similarity")
                        title = doc.get("source_title", "")[:80]
                        print(f"[DEBUG][retrieve]  #{i+1} sim={sim:.3f} | {title} | {doc.get('source_url','')}")
                    print(f"[DEBUG][retrieve] used_live_fallback: False (multi-topic, no single-query fallback)")
                    print("=" * 60 + "\n")
                except Exception as _e:
                    print(f"[DEBUG][retrieve] logging failed: {_e}")
            clean_docs = []
            for d in docs:
                clean_docs.append({
                    "content": d.get("content", ""),
                    "source_url": d.get("source_url", ""),
                    "source_title": d.get("source_title", ""),
                    "chunk_id": d.get("chunk_id", ""),
                })
            return {"retrieved_docs": clean_docs, "used_live_fallback": False}

    # Single-topic path (original) — also handles comparison with top-k 10 as cheap fix (Step 1)
    # For standard_lookup that looks like a comparison, bump to 10 even if not multi-topic
    k = TOP_K
    qtype = state.get("query_type", "")
    # Cheap fix: if query_type is standard_lookup and looks like comparison, use 10
    if qtype == "standard_lookup" and any(w in query.lower() for w in ["compare", " vs ", " versus ", "difference between", "when does each"]):
        k = TOP_K_COMPARISON
    docs = _query_chroma(query, k=k)

    # groundedness check — numeric threshold, not string equality
    # if all similarities below threshold => not grounded
    # Chroma distance -> similarity = 1-dist. Threshold 0.35 on similarity would be very low; use 0.35 distance => sim 0.65
    # Spec says "similarity scores are all below threshold (e.g. 0.35)" — so we check similarity < 0.35 => fallback
    # But with cosine, 0.35 similarity is low. Keep spec literal: similarity < 0.35 triggers fallback.
    # Also handle distance-based check: if no docs or all distance > 0.65 (sim <0.35) => fallback
    needs_fallback = False
    if not docs:
        needs_fallback = True
    else:
        sims = [d.get("similarity") for d in docs if d.get("similarity") is not None]
        if sims:
            # literal spec: sim < 0.35 => not grounded
            if all(s < GROUNDEDNESS_THRESHOLD for s in sims):
                needs_fallback = True
            # also show distances for debugging
        else:
            needs_fallback = False

    used_live = False
    live_docs_snapshot: list | None = None
    if needs_fallback:
        live_docs = _live_fallback(query)
        live_docs_snapshot = live_docs
        if live_docs:
            docs = live_docs
            used_live = True
        else:
            # keep original docs but mark fallback attempted
            used_live = True

    # --- DEBUG_VERBOSE block (terminal only, not API) ---
    if is_verbose():
        try:
            qtype = state.get("query_type", "unknown")
            print("\n" + "=" * 60)
            print(f"[DEBUG][retrieve] Query: {query!r} | type: {qtype}")
            print(f"[DEBUG][retrieve] Threshold: {GROUNDEDNESS_THRESHOLD} (similarity = 1 - distance)")
            # show all k results with scores (pre-clean)
            if docs:
                for i, doc in enumerate(docs):
                    # docs may be live docs without similarity; handle None
                    sim = doc.get("similarity")
                    dist = doc.get("distance")
                    # Use similarity if available, else distance
                    score_str = f"sim={sim:.3f}" if isinstance(sim, (int, float)) else f"dist={dist:.3f}" if isinstance(dist, (int, float)) else "no_score"
                    # Also show fallback status per doc if needed
                    title = doc.get("source_title", "")[:80]
                    url = doc.get("source_url", "")
                    print(f"[DEBUG][retrieve]  #{i+1} {score_str} | {title} | {url}")
            else:
                print("[DEBUG][retrieve]  (no docs)")
            # groundedness decision
            # need sims for decision trace
            try:
                sims_dbg = [d.get("similarity") for d in docs if d.get("similarity") is not None]
                if sims_dbg:
                    below = all(s < GROUNDEDNESS_THRESHOLD for s in sims_dbg)
                    print(f"[DEBUG][retrieve] groundedness: max_sim={max(sims_dbg):.3f} threshold={GROUNDEDNESS_THRESHOLD} all_below={below} -> {'FALLBACK' if below else 'GROUNDED'}")
                else:
                    print(f"[DEBUG][retrieve] groundedness: no similarity scores (likely live docs) -> used_live_fallback will be {used_live}")
            except Exception:
                pass
            print(f"[DEBUG][retrieve] used_live_fallback: {used_live}")
            if needs_fallback:
                if live_docs_snapshot:
                    print(f"[DEBUG][retrieve] live search returned {len(live_docs_snapshot)} docs (showing first 2):")
                    for j, ld in enumerate(live_docs_snapshot[:2]):
                        print(f"[DEBUG][retrieve]   live #{j+1} {ld.get('source_title','')[:60]} | {ld.get('source_url','')}")
                else:
                    print("[DEBUG][retrieve] live search returned 0 docs")
            print("=" * 60 + "\n")
        except Exception as _e:
            print(f"[DEBUG][retrieve] logging failed: {_e}")

    # strip internal score fields for downstream? keep them but downstream ignores
    # Ensure required keys present
    clean_docs = []
    for d in docs:
        clean_docs.append({
            "content": d.get("content", ""),
            "source_url": d.get("source_url", ""),
            "source_title": d.get("source_title", ""),
            "chunk_id": d.get("chunk_id", ""),
        })

    return {"retrieved_docs": clean_docs, "used_live_fallback": used_live}
