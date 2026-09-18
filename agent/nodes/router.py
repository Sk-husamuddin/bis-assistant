import os
import re
from agent.state import GraphState, QueryType
from agent.prompts import ROUTER_SYSTEM, ROUTER_USER_TMPL

# heuristic fallback keywords — ensures tests pass without API key
_HEURISTICS = {
    "product_to_standard": [
        r"i (manufacture|make|sell|want to sell|produce)",
        r"which.*standard.*applies",
        r"do i need.*(crs|isi|hallmark)",
        r"sell.*in india",
    ],
    "lab_query": [r"\blab\b", r"laboratory", r"lrs", r"recognition", r"sample.*handling", r"testing.*lab"],
    "scheme_process": [r"\bscheme\b", r"\bcrs\b.*process", r"\bisi\b.*process", r"registration.*process", r"certification.*process", r"fmcs", r"hallmark.*process", r"mscs"],
    "standard_lookup": [r"\bis\s*\d+", r"what is is\b", r"what does is\b", r"which products.*cover", r"specify"],
    "consumer_query": [
        r"complaint",
        r"fake",
        r"verify.*(mark|hallmark|isi|crs|huid)",
        r"genuine",
        r"counterfeit",
        r"consumer",
        r"bis care",
        r"report.*fake",
        r"huid",
        r"verify.*jewel",
    ],
}

VALID_LABELS: set[str] = {"standard_lookup", "product_to_standard", "scheme_process", "lab_query", "consumer_query"}

def _heuristic(query: str) -> QueryType:
    q = query.lower()
    scores = {k: 0 for k in VALID_LABELS}
    for label, patterns in _HEURISTICS.items():
        for pat in patterns:
            if re.search(pat, q):
                scores[label] += 1
    # priority tie-break: product_to_standard > lab_query > scheme_process > consumer_query > standard_lookup
    order = ["product_to_standard", "lab_query", "scheme_process", "consumer_query", "standard_lookup"]
    best = max(order, key=lambda k: scores[k])
    if scores[best] == 0:
        # default to standard_lookup for IS-number queries, else scheme_process
        if re.search(r"\bis\s*\d+", q):
            return "standard_lookup"
        return "standard_lookup"
    return best  # type: ignore

def _call_groq(query: str) -> str | None:
    api_key = os.getenv("GROQ_API_KEY", "")
    try:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GROQ_API_KEY", api_key)
    except Exception:
        pass
    if not api_key:
        return None
    try:
        from groq import Groq
        model = os.getenv("GROQ_ROUTER_MODEL", "openai/gpt-oss-20b")
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": ROUTER_USER_TMPL.format(query=query)},
            ],
            temperature=0,
            max_tokens=10,
        )
        text = (resp.choices[0].message.content or "").strip().lower()
        # extract label
        for lbl in VALID_LABELS:
            if lbl in text:
                return lbl
        return None
    except Exception as e:
        print(f"[router] groq call failed: {e}")
        return None

def router_node(state: GraphState) -> dict:
    query = state.get("query", "").strip()
    if not query:
        return {"query_type": "standard_lookup"}
    label = _call_groq(query)
    if label and label in VALID_LABELS:
        return {"query_type": label}
    # fallback heuristic — keeps tests deterministic offline
    return {"query_type": _heuristic(query)}
