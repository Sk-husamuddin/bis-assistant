import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from unittest.mock import patch
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_query_returns_schema():
    fake_result = {
        "answer": "IS 2347 covers pressure cookers [1]",
        "citations": [{"source_title": "IS 2347", "source_url": "https://bis.gov.in/is2347", "chunk_id": "c1"}],
        "query_type": "standard_lookup",
        "used_live_fallback": False,
    }
    with patch("api.main.run_query", return_value=fake_result):
        r = client.post("/query", json={"query": "What is IS 2347?"})
        assert r.status_code == 200
        j = r.json()
        assert "answer" in j and "citations" in j and "query_type" in j and "used_live_fallback" in j
        assert j["query_type"] == "standard_lookup"

def test_query_validation_short():
    r = client.post("/query", json={"query": "hi"})
    assert r.status_code == 422

def test_index_serves_html():
    r = client.get("/")
    # either html or json message, but should be 200
    assert r.status_code == 200
