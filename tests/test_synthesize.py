import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from unittest.mock import patch, MagicMock
from agent.nodes.synthesize import normalize_citation_markers, filter_citations_by_markers, synthesize_node
from agent.prompts import SYNTHESIZE_SYSTEM

def test_prompt_requires_ascii_brackets():
    assert "Use ONLY plain ASCII square brackets for citations: [1], [2], etc." in SYNTHESIZE_SYSTEM
    assert "Never use full-width or CJK-style brackets" in SYNTHESIZE_SYSTEM
    assert "【1】" in SYNTHESIZE_SYSTEM  # should mention the forbidden style explicitly

def test_normalize_fullwidth_brackets():
    # BUG 1 — 【1】 should become [1]
    assert normalize_citation_markers("See source 【1】 for details") == "See source [1] for details"
    assert normalize_citation_markers("As per 【12】 and 【2】") == "As per [12] and [2]"
    # Also handle ［1］ variant
    assert normalize_citation_markers("Test ［1］ marker") == "Test [1] marker"
    # ASCII already correct stays
    assert normalize_citation_markers("Already [1] and [2]") == "Already [1] and [2]"
    # Multiple
    raw = "First 【1】 then 【2】 then [3]"
    assert normalize_citation_markers(raw) == "First [1] then [2] then [3]"

def test_synthesize_normalizes_fullwidth_via_mocked_groq():
    # Mock Groq to return raw answer with 【1】, assert returned answer has [1] not 【1】
    fake_docs = [
        {"content": "doc1", "source_title": "Doc1", "source_url": "https://example.com/1", "chunk_id": "a_0"},
        {"content": "doc2", "source_title": "Doc2", "source_url": "https://example.com/2", "chunk_id": "a_1"},
    ]
    raw_with_fullwidth = "According to BIS Act 【1】, the standard applies."
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=raw_with_fullwidth))]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("agent.nodes.synthesize.Groq", return_value=mock_client):
        # Need GROQ_API_KEY present to hit Groq path (not heuristic)
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            out = synthesize_node({"query": "test", "query_type": "standard_lookup", "retrieved_docs": fake_docs, "answer": "", "citations": [], "target_language": "en", "translated_answer": None})
            assert out["answer"] == "According to BIS Act [1], the standard applies."
            assert "【1】" not in out["answer"]
            assert "[1]" in out["answer"]

def test_filter_citations_single_marker():
    # BUG 2 — only markers present in answer should be returned
    docs = [
        {"content": "doc1", "source_title": "Doc1", "source_url": "https://example.com/1", "chunk_id": "a_0"},
        {"content": "doc2", "source_title": "Doc2", "source_url": "https://example.com/2", "chunk_id": "a_1"},
        {"content": "doc3", "source_title": "Doc3", "source_url": "https://example.com/3", "chunk_id": "a_2"},
    ]
    answer = "Only first source matters [1]."
    normalized, filtered = filter_citations_by_markers(answer, docs)
    assert len(filtered) == 1
    assert filtered[0]["source_title"] == "Doc1"
    assert filtered[0]["source_url"] == "https://example.com/1"

def test_filter_citations_two_markers():
    docs = [
        {"content": "doc1", "source_title": "Doc1", "source_url": "https://example.com/1", "chunk_id": "a_0"},
        {"content": "doc2", "source_title": "Doc2", "source_url": "https://example.com/2", "chunk_id": "a_1"},
        {"content": "doc3", "source_title": "Doc3", "source_url": "https://example.com/3", "chunk_id": "a_2"},
    ]
    answer = "See [1] and [3] for details"
    _, filtered = filter_citations_by_markers(answer, docs)
    assert len(filtered) == 2
    assert filtered[0]["source_title"] == "Doc1"
    assert filtered[1]["source_title"] == "Doc3"

def test_filter_no_markers_returns_empty():
    docs = [
        {"content": "doc1", "source_title": "Doc1", "source_url": "https://example.com/1", "chunk_id": "a_0"},
    ]
    answer = "No citation here."
    _, filtered = filter_citations_by_markers(answer, docs)
    assert len(filtered) == 0

def test_synthesize_filters_via_mocked_groq():
    # End-to-end: mocked raw response only cites [1], 3 docs retrieved -> 1 citation returned
    fake_docs = [
        {"content": "doc1", "source_title": "Doc1", "source_url": "https://example.com/1", "chunk_id": "a_0"},
        {"content": "doc2", "source_title": "Doc2", "source_url": "https://example.com/2", "chunk_id": "a_1"},
        {"content": "doc3", "source_title": "Doc3", "source_url": "https://example.com/3", "chunk_id": "a_2"},
    ]
    raw = "Answer based on [1] only."
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=raw))]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp
    with patch("agent.nodes.synthesize.Groq", return_value=mock_client):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            out = synthesize_node({"query": "test", "query_type": "standard_lookup", "retrieved_docs": fake_docs, "answer": "", "citations": [], "target_language": "en", "translated_answer": None})
            assert len(out["citations"]) == 1
            assert out["citations"][0]["source_title"] == "Doc1"
            assert out["answer"] == "Answer based on [1] only."
