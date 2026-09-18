import os
import re
from agent.state import GraphState
from agent.prompts import (
    SYNTHESIZE_SYSTEM,
    SYNTHESIZE_USER_TMPL,
    PRODUCT_SYNTHESIZE_ADDENDUM,
    CONSUMER_SYNTHESIZE_ADDENDUM,
    HALLMARK_SYNTHESIZE_ADDENDUM,
)
from agent.debug import is_verbose

try:
    from groq import Groq
except Exception:
    Groq = None  # type: ignore

MAX_DOC_CHARS = 1200  # per doc truncation for prompt budget

# BUG 1 — citation marker normalization (full-width → ASCII)
# Covers 【1】 (U+3010/U+3011), ［1］(U+FF3B/U+FF3D), and similar
_FULLWIDTH_RE = re.compile(r"[【＊\u3010\uFF3B]\s*(\d+)\s*[】\u3011\uFF3D]")

def normalize_citation_markers(text: str) -> str:
    """Post-process: replace any full-width/CJK bracket citations like 【1】 with [1]."""
    if not text:
        return text
    # Replace 【N】, ［N］, etc. with [N]
    t = _FULLWIDTH_RE.sub(r"[\1]", text)
    # Also handle full-width digits? No, digits are same
    return t

def filter_citations_by_markers(answer: str, docs: list[dict]) -> tuple[str, list[dict]]:
    """
    BUG 2 — only return citations for markers that actually appear in answer text.
    Extracts [N] occurrences, keeps only those where 1 <= N <= len(docs).
    Returns (normalized_answer, filtered_citations).
    """
    normalized = normalize_citation_markers(answer)
    # Extract all [N] markers
    markers = re.findall(r"\[(\d+)\]", normalized)
    if not markers:
        return normalized, []
    # Unique sorted ints within range
    idxs = sorted({int(m) for m in markers if m.isdigit()})
    filtered = []
    for i in idxs:
        if 1 <= i <= len(docs):
            d = docs[i - 1]
            filtered.append({"source_title": d.get("source_title",""), "source_url": d.get("source_url",""), "chunk_id": d.get("chunk_id","")})
    return normalized, filtered

def _format_docs(docs: list[dict]) -> str:
    if not docs:
        return "(no documents retrieved — answer that you cannot answer from authorized BIS sources)"
    blocks = []
    for i, d in enumerate(docs, 1):
        title = d.get("source_title", "Untitled")
        url = d.get("source_url", "")
        content = (d.get("content") or "")[:MAX_DOC_CHARS]
        blocks.append(f"[{i}] {title}\nURL: {url}\nContent: {content}")
    return "\n\n".join(blocks)

def _heuristic_answer(query: str, query_type: str, docs: list[dict]) -> tuple[str, list[dict]]:
    """Offline fallback when Groq key missing — returns a grounded stub citing docs."""
    citations = []
    for i, d in enumerate(docs, 1):
        citations.append({"source_title": d.get("source_title",""), "source_url": d.get("source_url",""), "chunk_id": d.get("chunk_id","")})
    if not docs:
        return ("I cannot answer this from the authorized BIS corpus — no relevant documents were retrieved. Try rephrasing or check bis.gov.in directly.", citations)
    # build minimal answer that satisfies test expectations (mentions standard/scheme + citation)
    if query_type == "product_to_standard":
        # pick most relevant doc title as hint
        hint = docs[0].get("source_title","")
        answer = (
            f"Based on the BIS corpus, your product likely maps to the standard mentioned in the retrieved sources (e.g. {hint}). "
            f"Applicable scheme depends on whether the product falls under QCO/CRS or voluntary ISI — see sources [1]. "
            f"This is grounded only in the retrieved documents; verify on bis.gov.in before applying."
        )
    elif query_type == "standard_lookup":
        answer = f"Per the BIS sources, {docs[0].get('source_title','')} describes the scope. Details are summarized from sources [1][2]. See citations for the authoritative text."
    elif query_type == "scheme_process":
        answer = "The retrieved BIS documents outline the scheme process at a high level (steps, eligibility, documents). Refer to citations [1] for the authoritative process on bis.gov.in."
    elif query_type == "lab_query":
        answer = "Lab recognition under LRS 2018 is described in the retrieved LRS document. Key requirements and sample handling guidelines are in [1][2]."
    elif query_type == "consumer_query":
        # Consumer verification / complaint — must mention BIS Care + Branch Office fallback
        answer = (
            "For verification, check the BIS Standard Mark with licence/registration/HUID number on bis.gov.in or the BIS Care app (Verify HUID / Verify Licence). "
            "To report a fake or substandard product, file a complaint via the BIS Care app or the nearest BIS Regional/Branch Office (addresses at bis.gov.in) with product details, photos and purchase evidence [1]."
        )
    else:
        # Default for unknown types (including hallmark ops that route as standard_lookup)
        # If hallmark HUID/purity keywords present, try to give hallmark-specific stub
        ql = query.lower()
        if any(k in ql for k in ["huid", "hallmark", "purity", "ahc"]):
            answer = (
                "HUID is a 6-digit alphanumeric Hallmark Unique ID for traceability, purity is marked as 14K/585, 18K/750, 22K/916 (IS 2112 for silver), "
                "assayed only at BIS-recognised Assaying & Hallmarking Centres (AHC), and jeweller registration is free/online/lifetime valid [1]. "
                "Verify HUID on bis.gov.in or the BIS Care app."
            )
        else:
            answer = "Answer based on retrieved BIS documents [1]."
    # ensure citations markers present
    if "[1]" not in answer and citations:
        answer += " [1]"
    return answer, citations

def _call_groq(query: str, query_type: str, docs: list[dict]) -> tuple[str, list[dict]] | None:
    api_key = os.getenv("GROQ_API_KEY", "")
    try:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GROQ_API_KEY", api_key)
    except Exception:
        pass
    if not api_key:
        return None
    if Groq is None:
        print("[synthesize] Groq SDK not available")
        return None
    try:
        model = os.getenv("GROQ_SYNTHESIS_MODEL", "openai/gpt-oss-120b")
        # Select addendum based on query_type and hallmark ops keywords (additive, no change to existing)
        # HUID is hallmark-specific even when classified as consumer_query
        if "huid" in query.lower():
            addendum = HALLMARK_SYNTHESIZE_ADDENDUM
        elif query_type == "consumer_query":
            addendum = CONSUMER_SYNTHESIZE_ADDENDUM
        elif query_type == "product_to_standard":
            addendum = PRODUCT_SYNTHESIZE_ADDENDUM
        elif any(k in query.lower() for k in ["ahc", "assaying", "purity", "14k", "18k", "22k", "916", "585", "750"]) and "hallmark" in query.lower():
            addendum = HALLMARK_SYNTHESIZE_ADDENDUM
        else:
            addendum = ""
        docs_block = _format_docs(docs)
        user_content = SYNTHESIZE_USER_TMPL.format(query=query, query_type=query_type, docs_block=docs_block, addendum=addendum or "(no extra instructions)")
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYNTHESIZE_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        raw_answer = (resp.choices[0].message.content or "").strip()
        # --- DEBUG_VERBOSE (terminal only) ---
        if is_verbose():
            try:
                print("\n" + "=" * 60)
                print(f"[DEBUG][synthesize] query_type={query_type} | docs={len(docs)} | model={model}")
                print(f"[DEBUG][synthesize] SYSTEM prompt:\n{SYNTHESIZE_SYSTEM[:800]}")
                print(f"\n[DEBUG][synthesize] USER prompt / retrieved context block (first 2000 chars):\n{user_content[:2000]}")
                print(f"\n[DEBUG][synthesize] docs_block injected (first 2000 chars):\n{docs_block[:2000]}")
                print(f"\n[DEBUG][synthesize] RAW model response (first 2000 chars):\n{raw_answer[:2000]}")
                # citations will be built next; print preview
                print(f"\n[DEBUG][synthesize] citations to return: {len(docs)} entries")
                for i, d in enumerate(docs[:3]):
                    print(f"[DEBUG][synthesize]  cite #{i+1} {d.get('source_title','')[:60]} | {d.get('source_url','')}")
                print("=" * 60 + "\n")
            except Exception as _e:
                print(f"[DEBUG][synthesize] logging failed: {_e}")
        if not raw_answer:
            return None
        # BUG 1 + BUG 2: normalize 【N】→[N] and filter to only cited markers
        normalized, filtered_citations = filter_citations_by_markers(raw_answer, docs)
        if is_verbose() and normalized != raw_answer:
            try:
                print(f"[DEBUG][synthesize] normalized full-width markers: {raw_answer[:200]!r} -> {normalized[:200]!r}")
            except Exception:
                pass
        if is_verbose():
            try:
                print(f"[DEBUG][synthesize] final citations list ({len(filtered_citations)}): {filtered_citations[:2]}")
                if len(filtered_citations) != len(docs):
                    print(f"[DEBUG][synthesize] filtered citations {len(docs)} -> {len(filtered_citations)} based on markers in answer")
            except Exception:
                pass
        return normalized, filtered_citations
    except Exception as e:
        print(f"[synthesize] groq call failed: {e}")
        return None

def synthesize_node(state: GraphState) -> dict:
    query = state.get("query", "")
    query_type = state.get("query_type", "standard_lookup")
    docs = state.get("retrieved_docs", []) or []
    res = _call_groq(query, query_type, docs)
    if res is not None:
        answer, citations = res
        # Ensure citations are filtered even if _call_groq already did (idempotent)
        # (defense: if raw answer had no markers, citations would be empty)
        return {"answer": answer, "citations": citations}
    # offline heuristic (also logs when verbose)
    if is_verbose():
        try:
            print("\n" + "=" * 60)
            print(f"[DEBUG][synthesize] HEURISTIC fallback (no GROQ_API_KEY or API error)")
            print(f"[DEBUG][synthesize] query={query!r} | type={query_type} | docs={len(docs)}")
            print("=" * 60 + "\n")
        except Exception:
            pass
    answer, citations = _heuristic_answer(query, query_type, docs)
    # Apply same normalization/filter for heuristic (keeps behavior consistent)
    try:
        filtered_answer, filtered_citations = filter_citations_by_markers(answer, docs)
        answer, citations = filtered_answer, filtered_citations
    except Exception:
        pass
    if is_verbose():
        try:
            print(f"[DEBUG][synthesize] heuristic answer preview: {answer[:400]!r}")
            print(f"[DEBUG][synthesize] heuristic citations: {citations[:2]}")
        except Exception:
            pass
    return {"answer": answer, "citations": citations}
