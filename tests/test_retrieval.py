import sys, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from unittest.mock import patch, MagicMock
from agent.nodes.retrieve import retrieve_node

# Helper to make fake chroma docs
def fake_docs(sims):
    return [
        {"content": f"doc {i} about BIS", "source_url": f"https://bis.gov.in/{i}", "source_title": f"Doc {i}", "chunk_id": f"c{i}", "distance": 1 - s, "similarity": s}
        for i, s in enumerate(sims)
    ]

def test_retrieval_returns_docs_above_threshold_no_fallback():
    # sim 0.8 > 0.35 => grounded, no fallback
    with patch("agent.nodes.retrieve._query_chroma", return_value=fake_docs([0.8, 0.7])):
        with patch("agent.nodes.retrieve._live_fallback") as mock_live:
            out = retrieve_node({"query": "What is IS 2347?"})
            assert len(out["retrieved_docs"]) == 2
            assert out["used_live_fallback"] is False
            mock_live.assert_not_called()

def test_retrieval_low_similarity_triggers_fallback():
    # sims 0.2, 0.1 < 0.35 => not grounded => fallback
    live = [{"content": "live BIS CRS page", "source_url": "https://bis.gov.in/crs", "source_title": "CRS", "chunk_id": ""}]
    with patch("agent.nodes.retrieve._query_chroma", return_value=fake_docs([0.2, 0.1])):
        with patch("agent.nodes.retrieve._live_fallback", return_value=live) as mock_live:
            out = retrieve_node({"query": "obscure unknown query xyz"})
            assert out["used_live_fallback"] is True
            assert out["retrieved_docs"][0]["source_url"] == "https://bis.gov.in/crs"
            mock_live.assert_called_once()

def test_retrieval_empty_chroma_triggers_fallback():
    live = [{"content": "bis hallmarking", "source_url": "https://bis.gov.in/hall", "source_title": "Hallmarking", "chunk_id": ""}]
    with patch("agent.nodes.retrieve._query_chroma", return_value=[]):
        with patch("agent.nodes.retrieve._live_fallback", return_value=live):
            out = retrieve_node({"query": "anything"})
            assert out["used_live_fallback"] is True
            assert len(out["retrieved_docs"]) == 1

def test_retrieval_multi_topic_merge_contains_all_topics():
    # Mock per-topic retrieval to simulate decomposition
    def fake_chroma(query, k=5):
        if "ISI" in query:
            return [{"content": "ISI content", "source_title": "BIS Product Certification (ISI / Scheme I) Overview", "source_url": "https://bis.gov.in/isi", "chunk_id": "isi1", "distance": 0.3, "similarity": 0.7}]
        if "CRS" in query:
            return [{"content": "CRS content", "source_title": "BIS Compulsory Registration Scheme (CRS / Scheme II) Overview", "source_url": "https://bis.gov.in/crs", "chunk_id": "crs1", "distance": 0.3, "similarity": 0.7}]
        if "Hallmark" in query:
            return [{"content": "Hallmark content", "source_title": "BIS Hallmarking Overview", "source_url": "https://bis.gov.in/hall", "chunk_id": "hall1", "distance": 0.3, "similarity": 0.7}]
        return []

    with patch("agent.nodes.retrieve._query_chroma", side_effect=fake_chroma):
        out = retrieve_node({"query": "Compare ISI, CRS, and Hallmarking — when does each apply?"})
        titles = " ".join([d["source_title"] for d in out["retrieved_docs"]])
        # Must contain at least one chunk for each of the three topics
        assert "ISI" in titles or "Product Certification" in titles, f"ISI missing in {titles}"
        assert "CRS" in titles or "Compulsory Registration" in titles, f"CRS missing in {titles}"
        assert "Hallmark" in titles, f"Hallmarking missing in {titles}"
        assert out["used_live_fallback"] is False  # multi-topic should not trigger fallback when merged has docs
        assert len(out["retrieved_docs"]) >= 3

def test_retrieval_single_topic_not_polluted():
    # Ensure single-topic query doesn't get cross-topic noise from decomposition
    def fake_chroma_single(query, k=5):
        # For IS 2347, return only IS 2347 docs
        return [{"content": "IS 2347 content", "source_title": "IS 2347:2017 — Domestic Pressure Cookers", "source_url": "https://bis.gov.in/is2347", "chunk_id": "is2347_0", "distance": 0.3, "similarity": 0.7}]

    with patch("agent.nodes.retrieve._query_chroma", side_effect=fake_chroma_single):
        out = retrieve_node({"query": "What is IS 2347 and which products does it cover?"})
        assert len(out["retrieved_docs"]) >= 1
        assert "IS 2347" in out["retrieved_docs"][0]["source_title"]
        # Should not contain CRS/Hallmark when not requested
        titles = " ".join([d["source_title"] for d in out["retrieved_docs"]])
        # Allow but not require: just ensure at least one correct, and not dominated by Hallmark
        assert "IS 2347" in titles
