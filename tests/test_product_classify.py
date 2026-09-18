import sys, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
os.environ.pop("GROQ_API_KEY", None)

from agent.nodes.synthesize import synthesize_node

def synth(q, qtype, docs):
    return synthesize_node({"query": q, "query_type": qtype, "retrieved_docs": docs})

def fake_doc(title="IS 2347 — Pressure Cookers", url="https://bis.gov.in/is2347"):
    return {"content": f"Content about {title} under ISI Scheme I", "source_url": url, "source_title": title, "chunk_id": "c1"}

def test_product_pressure_cooker_mentions_standard_and_citation():
    docs = [fake_doc("IS 2347 — Pressure Cookers"), fake_doc("BIS Product Certification ISI Scheme I", "https://bis.gov.in/isi")]
    out = synth("I manufacture stainless steel pressure cookers — which BIS standard and scheme applies?", "product_to_standard", docs)
    assert "citations" in out and len(out["citations"]) >= 1
    # heuristic answer should contain citation marker or mention standard
    assert "[1]" in out["answer"] or "IS 2347" in out["answer"] or "2347" in out["answer"]

def test_product_led_mentions_crs_or_scheme():
    docs = [fake_doc("IS 15885 — LED Lamps", "https://bis.gov.in/is15885"), fake_doc("BIS CRS Scheme II", "https://bis.gov.in/crs")]
    out = synth("I want to sell LED bulbs in India — do I need CRS or ISI?", "product_to_standard", docs)
    assert len(out["citations"]) >= 1
    # accept both heuristic "[1]" and Groq unicode citations "【1】" / "1."
    assert "[1]" in out["answer"] or "【1" in out["answer"] or "Source" in out["answer"] or "1." in out["answer"]
    # should mention scheme
    assert "CRS" in out["answer"] or "Scheme" in out["answer"] or "ISI" in out["answer"]

def test_product_no_docs_returns_ungrounded_message():
    out = synth("I make xyz unknown product abc", "product_to_standard", [])
    assert "cannot" in out["answer"].lower() or "no relevant" in out["answer"].lower()
