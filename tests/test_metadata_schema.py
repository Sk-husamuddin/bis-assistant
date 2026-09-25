import sys
import pathlib
import hashlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from ingestion.metadata_schema import validate_chunk


def _valid_payload():
    text = "IS 2347:2017 Domestic Pressure Cookers specification"
    return {
        "source_url": "https://www.bis.gov.in/bis-indian-standards/?standard_number=IS+2347",
        "source_title": "IS 2347 — Pressure Cookers",
        "doc_category": "IS Standard",
        "doc_format": "html",
        "is_standard_number": "IS 2347",
        "scheme_tag": "ISI",
        "publish_date": None,
        "gazette_date": None,
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "crawl_timestamp": "2026-05-13T00:00:00Z",
        "page_number": None,
        "heading_path": None,
        "chunk_index": 0,
        "chunk_count": 1,
        "supersedes": None,
        "superseded_by": None,
        "chunk_id": "is2347_0",
        "ingest_source": "curated",
    }


def test_validate_chunk_valid():
    data = _valid_payload()
    result = validate_chunk(data)
    assert result is not None
    assert result.doc_category == "IS Standard"
    assert result.chunk_id == "is2347_0"
    assert result.scheme_tag == "ISI"


def test_validate_chunk_missing_category_returns_none():
    data = _valid_payload()
    data.pop("doc_category", None)
    result = validate_chunk(data)
    assert result is None
