import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import os
os.environ.pop("GROQ_API_KEY", None)

from unittest.mock import patch
from agent.nodes.synthesize import synthesize_node
from agent.nodes.retrieve import retrieve_node

def fake_doc(title, url, content):
    return {"content": content, "source_title": title, "source_url": url, "chunk_id": "c1", "distance": 0.3, "similarity": 0.7}

def test_consumer_synthetic_retrievable_and_cited():
    # Mock retrieve to return consumer synthetic
    consumer = fake_doc(
        "BIS Consumer Verification & Complaint Guide — ISI / CRS / Hallmark",
        "https://www.bis.gov.in/consumer-overview/consumer-overviews/consumer-protection?lang=en",
        "BIS Care app Verify HUID and Branch Office complaint",
    )
    with patch("agent.nodes.retrieve._query_pinecone", return_value=[consumer]):
        with patch("agent.nodes.retrieve._query_vector_store", return_value=[consumer]):
            with patch("agent.nodes.retrieve._live_fallback", return_value=[]):
                out = retrieve_node({"query": "I bought a product with a fake ISI mark, how do I report it?", "query_type": "consumer_query"})
                assert any("Consumer" in d["source_title"] for d in out["retrieved_docs"])
    # Synthesize should cite it and mention BIS Care + Branch Office
    docs = [
        {"content": "How to verify ... BIS Care app Verify HUID ... Branch Office", "source_title": "BIS Consumer Verification & Complaint Guide", "source_url": "https://www.bis.gov.in/consumer-overview/consumer-overviews/consumer-protection?lang=en", "chunk_id": "c1"}
    ]
    out = synthesize_node({"query": "I bought a product with a fake ISI mark, how do I report it?", "query_type": "consumer_query", "retrieved_docs": docs})
    assert "BIS Care" in out["answer"] or "Branch Office" in out["answer"]
    assert len(out["citations"]) >= 1
    assert "consumer" in out["citations"][0]["source_title"].lower() or "Consumer" in out["answer"]

def test_hallmark_huid_retrievable_and_cited():
    hallmark = fake_doc(
        "BIS Hallmarking — HUID, Purity & AHC Operations",
        "https://www.bis.gov.in/hallmarking-overview/hallmarking-overview/",
        "HUID 6-digit purity 14K/585 18K/750 22K/916 AHC free online",
    )
    with patch("agent.nodes.retrieve._query_pinecone", return_value=[hallmark]):
        with patch("agent.nodes.retrieve._query_vector_store", return_value=[hallmark]):
            with patch("agent.nodes.retrieve._live_fallback", return_value=[]):
                out = retrieve_node({"query": "What does the HUID number on my jewelry mean?", "query_type": "consumer_query"})
                assert any("HUID" in d["source_title"] or "Hallmark" in d["source_title"] for d in out["retrieved_docs"])
    docs = [
        {"content": "HUID 6-digit 14K/585 18K/750 22K/916 AHC free online lifetime", "source_title": "BIS Hallmarking — HUID, Purity & AHC Operations", "source_url": "https://www.bis.gov.in/hallmarking-overview/hallmarking-overview/", "chunk_id": "c1"}
    ]
    # Mock Groq to avoid rate-limit flakiness and ensure deterministic HUID answer
    mock_resp = type("obj", (), {"choices": [type("obj", (), {"message": type("obj", (), {"content": "HUID is a 6-digit alphanumeric code. Purity 14K/585 etc. [1]"})()})()]})()
    mock_client = type("obj", (), {"chat": type("obj", (), {"completions": type("obj", (), {"create": lambda *a, **k: mock_resp})()})})()
    with patch("agent.nodes.synthesize.Groq", return_value=mock_client):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            out = synthesize_node({"query": "What does the HUID number on my jewelry mean?", "query_type": "consumer_query", "retrieved_docs": docs})
    assert "HUID" in out["answer"]
    # Check for 6-digit with any hyphen variant (normal -, non-breaking hyphen \u2011, etc.)
    assert "6" in out["answer"] and "digit" in out["answer"].lower()
    assert len(out["citations"]) >= 1

def test_hallmark_purity_retrievable():
    docs = [
        {"content": "Purity markings 14K/585 18K/750 22K/916 IS 2112", "source_title": "BIS Hallmarking — HUID, Purity & AHC Operations", "source_url": "https://www.bis.gov.in/hallmarking-overview/hallmarking-overview/", "chunk_id": "c1"}
    ]
    mock_resp = type("obj", (), {"choices": [type("obj", (), {"message": type("obj", (), {"content": "Purity 22K corresponds to 916 fineness, 14K to 585. HUID 6-digit. [1]"})()})()]})()
    mock_client = type("obj", (), {"chat": type("obj", (), {"completions": type("obj", (), {"create": lambda *a, **k: mock_resp})()})})()
    with patch("agent.nodes.synthesize.Groq", return_value=mock_client):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            out = synthesize_node({"query": "What are the purity markings for 22K gold?", "query_type": "consumer_query", "retrieved_docs": docs})
    # Should mention 22K/916 or 14K/585
    assert "22K" in out["answer"] or "916" in out["answer"]
    assert "HUID" in out["answer"] or "purity" in out["answer"].lower()
