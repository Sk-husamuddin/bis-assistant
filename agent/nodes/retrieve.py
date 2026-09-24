import os
import re
from typing import List, Dict, Any

from agent.state import GraphState
from agent.debug import is_verbose

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

_pinecone_index = None

def _get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    api_key = os.getenv("PINECONE_API_KEY", "").strip()
    index_name = os.getenv("PINECONE_INDEX_NAME", "").strip()
    if not api_key or not index_name:
        return None
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=api_key)
        _pinecone_index = pc.Index(index_name)
        return _pinecone_index
    except Exception as e:
        print(f"[retrieve] pinecone init failed: {e}")
        return None

def _ensure_utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
    except Exception:
        pass

def _safe_str(s: str, max_len: int | None = None) -> str:
    if s is None:
        s = ""
    s = str(s).replace("\r", " ").replace("\n", " ")
    if max_len is not None:
        s = s[:max_len]
    # Always ascii-safe for Windows cp1252 terminal
    try:
        return s.encode("ascii", errors="replace").decode("ascii", errors="replace")
    except Exception:
        try:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            return s.encode(enc, errors="replace").decode(enc, errors="replace")
        except Exception:
            return s.encode("utf-8", errors="replace").decode("utf-8", errors="replace")

def _log_pinecone_hits(query: str, docs: List[Dict[str, Any]], source: str = "pinecone"):
    """Pretty-print retrieved chunks for terminal debugging — always visible for pinecone."""
    _ensure_utf8_stdout()
    # Always log for pinecone to aid debugging (even when DEBUG_VERBOSE=false)
    # Use is_verbose() to decide detail level
    verbose = is_verbose()
    # Also allow PINECONE_DEBUG=true to force detailed logs
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except Exception:
        pass
    pinecone_debug = os.getenv("PINECONE_DEBUG", "").lower() in ("1", "true", "yes", "on")
    if not verbose and not pinecone_debug:
        # Still print a concise one-liner for visibility
        print(f"[pinecone] retrieved {len(docs)} chunk(s) for query={_safe_str(query)!r} via {source} (k={len(docs)})")
        for i, d in enumerate(docs, 1):
            sim = d.get("similarity")
            sim_str = f"{sim:.4f}" if isinstance(sim, (int, float)) else "N/A"
            print(f"  [{i}] sim={sim_str} | {_safe_str(d.get('source_title',''), 80)} | {_safe_str(d.get('chunk_id',''))}")
        return

    # Verbose / PINECONE_DEBUG=true: detailed dump
    print("\n" + "="*78)
    print(f"[pinecone] RETRIEVED {len(docs)} chunk(s) | query={_safe_str(query)!r} | source={source}")
    print("="*78)
    if not docs:
        print("  (no hits)")
    for i, d in enumerate(docs, 1):
        sim = d.get("similarity")
        dist = d.get("distance")
        sim_str = f"{sim:.4f}" if isinstance(sim, (int, float)) else "N/A"
        dist_str = f"{dist:.4f}" if isinstance(dist, (int, float)) else "N/A"
        title = _safe_str(d.get("source_title") or "", 100)
        url = _safe_str(d.get("source_url") or "")
        cid = _safe_str(d.get("chunk_id") or "")
        content = _safe_str(d.get("content") or "").strip().replace("\r", " ").replace("\n", " ")
        snippet = content[:350] + ("..." if len(content) > 350 else "")
        # Truncate snippet to avoid flooding terminal
        print(f"  [{i}] sim={sim_str} dist={dist_str} | chunk_id={cid}")
        print(f"      title : {title}")
        print(f"      url   : {url}")
        print(f"      snippet: {snippet}")
        if verbose and d.get("content"):
            # Show a bit more metadata when verbose
            extra = []
            if d.get("source_url"):
                extra.append(f"url={_safe_str(d.get('source_url'))}")
            # Show first 600 chars of content when verbose
            if len(content) > 350:
                print(f"      full[:600]: {_safe_str(content[:600]).replace(chr(10),' ')}...")
        print()
    print("="*78 + "\n")


def _query_pinecone(query: str, k: int = TOP_K) -> List[Dict[str, Any]]:
    """Query Pinecone integrated-inference index with raw text (no local embedding).
    Returns same shape as former _query_chroma: content, source_url, source_title, chunk_id, distance, similarity.
    """
    idx = _get_pinecone_index()
    if idx is None:
        print(f"[pinecone] no index available for query={query!r} (check PINECONE_API_KEY/INDEX)")
        return []
    namespace = os.getenv("PINECONE_NAMESPACE", "default").strip() or "default"
    try:
        # Use integrated search — server-side embedding from raw text
        res = idx.search_records(namespace=namespace, query={"inputs": {"text": query}, "top_k": k})
    except Exception as e:
        print(f"[retrieve] pinecone search failed: {e}")
        return []
    docs: List[Dict[str, Any]] = []
    try:
        hits = []
        if hasattr(res, "result") and hasattr(res.result, "hits"):
            hits = res.result.hits or []
        elif isinstance(res, dict):
            hits = res.get("result", {}).get("hits", []) or res.get("hits", [])
        else:
            # fallback: try res.hits
            hits = getattr(res, "hits", []) or []
        for hit in hits:
            # hit may be dict or object
            if isinstance(hit, dict):
                hit_id = hit.get("id") or hit.get("_id") or ""
                score = hit.get("score") or hit.get("_score")
                fields = hit.get("fields") or hit.get("metadata") or {}
            else:
                hit_id = getattr(hit, "id", "") or getattr(hit, "_id", "")
                score = getattr(hit, "score", None)
                if score is None:
                    score = getattr(hit, "_score", None)
                fields = getattr(hit, "fields", None) or getattr(hit, "metadata", None) or {}
                if fields is None:
                    fields = {}
            content = fields.get("chunk_text") or fields.get("text") or ""
            source_url = fields.get("source_url", "")
            source_title = fields.get("source_title", "")
            chunk_id = fields.get("chunk_id", hit_id)
            similarity = float(score) if isinstance(score, (int, float)) else None
            distance = (1 - similarity) if similarity is not None else None
            docs.append({
                "content": content,
                "source_url": source_url,
                "source_title": source_title,
                "chunk_id": chunk_id,
                "distance": distance,
                "similarity": similarity,
            })
    except Exception as e:
        print(f"[retrieve] pinecone parse failed: {e}")
        return []
    # --- Terminal logging for debugging ---
    _log_pinecone_hits(query, docs, source=f"pinecone:k={k} ns={namespace}")
    return docs

# Backward-compat alias (tests previously mocked _query_vector_store)
def _query_vector_store(query: str, k: int = TOP_K) -> List[Dict[str, Any]]:
    return _query_pinecone(query, k)

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

def _log_final_retrieved(query: str, docs: List[Dict[str, Any]], used_live: bool, topics: List[str] | None = None):
    """Always-visible summary of final docs sent to synthesis — for terminal debugging."""
    _ensure_utf8_stdout()
    verbose = is_verbose()
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except Exception:
        pass
    pinecone_debug = os.getenv("PINECONE_DEBUG", "").lower() in ("1", "true", "yes", "on")
    # Show concise log always; detailed when verbose/pinecone_debug
    print("\n" + "-"*78)
    topic_info = f" topics={topics}" if topics else ""
    print(f"[retrieve] FINAL {len(docs)} doc(s) for query={_safe_str(query)!r}{_safe_str(topic_info)} | used_live_fallback={used_live}")
    print("-"*78)
    if not docs:
        print("  (no docs — will trigger live fallback or abstain)")
    for i, d in enumerate(docs[:10], 1):  # cap at 10 to avoid flooding
        sim = d.get("similarity")
        sim_str = f"{sim:.4f}" if isinstance(sim, (int, float)) else "N/A"
        title = _safe_str(d.get("source_title") or "", 90)
        url = _safe_str(d.get("source_url") or "")
        cid = _safe_str(d.get("chunk_id") or "")
        content = _safe_str(d.get("content") or "").strip().replace("\r", " ").replace("\n", " ")
        snippet = content[:280] + ("..." if len(content) > 280 else "")
        if verbose or pinecone_debug:
            print(f"  [{i}] sim={sim_str} | chunk_id={cid}")
            print(f"      title: {title}")
            print(f"      url  : {url}")
            print(f"      snippet: {snippet}")
        else:
            # concise one-liner
            print(f"  [{i}] sim={sim_str} | {_safe_str(title[:70])} | {cid}")
            print(f"      {_safe_str(snippet[:120])}...")
    if len(docs) > 10:
        print(f"  ... and {len(docs)-10} more docs")
    print("-"*78 + "\n")


def retrieve_node(state: GraphState) -> dict:
    query = state.get("query", "").strip()
    if not query:
        print(f"[retrieve] empty query → no docs")
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
            # Use per-topic k to keep total bounded (pinecone only)
            docs_t = _query_pinecone(subq, k=TOP_K_PER_TOPIC)
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
            _log_final_retrieved(query, docs, used_live=False, topics=topics)
            return {"retrieved_docs": clean_docs, "used_live_fallback": False}

    # Single-topic path (original) — also handles comparison with top-k 10 as cheap fix (Step 1)
    # For standard_lookup that looks like a comparison, bump to 10 even if not multi-topic
    k = TOP_K
    qtype = state.get("query_type", "")
    # Cheap fix: if query_type is standard_lookup and looks like comparison, use 10
    if qtype == "standard_lookup" and any(w in query.lower() for w in ["compare", " vs ", " versus ", "difference between", "when does each"]):
        k = TOP_K_COMPARISON
    docs = _query_pinecone(query, k=k)

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

    _log_final_retrieved(query, docs, used_live=used_live, topics=None)
    return {"retrieved_docs": clean_docs, "used_live_fallback": used_live}
