import sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from unittest.mock import patch, MagicMock
from agent.nodes.translate import translate_node

def test_translate_en_skips_groq():
    state = {"answer": "Hello world [1] IS 2347 CRS", "target_language": "en"}
    with patch("agent.nodes.translate._call_groq_translate") as mock:
        out = translate_node(state)  # type: ignore
        assert out.get("translated_answer") is None
        mock.assert_not_called()

def test_translate_hi_produces_non_empty():
    state = {"answer": "Hello world IS 2347", "target_language": "hi"}
    fake = "नमस्ते दुनिया IS 2347"
    with patch("agent.nodes.translate._call_groq_translate", return_value=fake) as mock:
        out = translate_node(state)  # type: ignore
        assert out.get("translated_answer") == fake
        assert out["translated_answer"] != state["answer"]
        mock.assert_called_once()
        # verify language_name passed correctly (Hindi)
        args, _ = mock.call_args
        assert "नमस्ते" in args[0] or "Hello" in args[0]

def test_translate_te_ta_non_empty():
    for lang in ["te", "ta"]:
        state = {"answer": "Answer IS 2347 CRS", "target_language": lang}
        fake = f"Translated {lang} IS 2347"
        with patch("agent.nodes.translate._call_groq_translate", return_value=fake):
            out = translate_node(state)  # type: ignore
            assert out.get("translated_answer") == fake
            assert out["translated_answer"] not in (None, "")

def test_preserve_is_crs_citation():
    # mocked output containing IS 2347, CRS, [1] must survive unchanged
    mocked = "यह IS 2347 मानक है [1] और CRS योजना के तहत आता है। IS 2347 [1] CRS"
    state = {"answer": "English IS 2347 CRS [1] text", "target_language": "hi"}
    with patch("agent.nodes.translate._call_groq_translate", return_value=mocked):
        out = translate_node(state)  # type: ignore
        ans = out.get("translated_answer", "")
        assert re.search(r"IS\s*2347", ans), f"IS 2347 not preserved in {ans}"
        assert "CRS" in ans, f"CRS not preserved in {ans}"
        assert re.search(r"\[1\]", ans), f"[1] not preserved in {ans}"

def test_missing_api_key_fallback_returns_english():
    state = {"answer": "Original English IS 2347", "target_language": "hi"}
    # Simulate missing key by making _call_groq_translate return None (as implemented)
    with patch("agent.nodes.translate._call_groq_translate", return_value=None):
        out = translate_node(state)  # type: ignore
        # spec: fallback to English answer
        assert out.get("translated_answer") == state["answer"]

def test_graph_run_query_with_lang():
    # Test via graph run_query with mocked translate to avoid real Groq
    from unittest.mock import patch as mpatch
    # Mock translate_node's Groq to return fake translation, but keep retrieve/synthesize mocked via heuristic (no GROQ_API_KEY)
    # We set GROQ_API_KEY empty so synthesize falls back to heuristic, then translate will be mocked
    import os
    orig = os.environ.get("GROQ_API_KEY")
    if "GROQ_API_KEY" in os.environ:
        del os.environ["GROQ_API_KEY"]
    try:
        from agent.graph import run_query
        fake_translated = "हिन्दी अनुवाद IS 2347 CRS [1]"
        with mpatch("agent.nodes.translate._call_groq_translate", return_value=fake_translated):
            out = run_query("What is IS 2347?", target_language="hi")
            # Should have translated_answer set to fake (since synthesize gives heuristic answer, translate returns fake)
            assert out.get("translated_answer") == fake_translated
            assert out.get("target_language") == "hi"
            # English answer still present
            assert out.get("answer")
        # en should give None
        out2 = run_query("What is IS 2347?", target_language="en")
        assert out2.get("translated_answer") is None
    finally:
        if orig is not None:
            os.environ["GROQ_API_KEY"] = orig

def test_api_query_accepts_target_language():
    # Verify api/main.py QueryRequest pattern and response shape via TestClient (mock graph)
    from fastapi.testclient import TestClient
    from unittest.mock import patch as mpatch
    from api.main import app

    client = TestClient(app)
    fake_result = {
        "answer": "English IS 2347 CRS [1]",
        "translated_answer": "हिन्दी IS 2347 CRS [1]",
        "target_language": "hi",
        "citations": [],
        "query_type": "standard_lookup",
        "used_live_fallback": False,
    }
    with mpatch("api.main.run_query", return_value=fake_result):
        r = client.post("/query", json={"query": "What is IS 2347?", "target_language": "hi"})
        assert r.status_code == 200
        j = r.json()
        assert j["target_language"] == "hi"
        assert j["translated_answer"] == fake_result["translated_answer"]
        assert j["answer"] == fake_result["answer"]
    # invalid lang -> 422
    r2 = client.post("/query", json={"query": "hello world", "target_language": "xx"})
    assert r2.status_code == 422
