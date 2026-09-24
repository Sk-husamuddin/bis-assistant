"""
Fetch, clean, chunk, embed, store in Pinecone (integrated inference).
Usage: python -m ingestion.fetch_and_chunk [--no-fetch] [--limit N]
Upserts to Pinecone with quarantine; VECTOR_BACKEND is now always pinecone.
"""
import argparse
import datetime
import json
import os
import re
import sys
import hashlib
import pathlib
import time
from typing import List

import httpx
from bs4 import BeautifulSoup

CHUNK_SIZE = 800  # tokens approx ~ chars/4
CHUNK_OVERLAP = 100

RAW_DIR = pathlib.Path(__file__).parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

def fetch_url(url: str, timeout: int = 30) -> tuple[bytes, str]:
    headers = {"User-Agent": "BIS-Assistant/1.0 (SIH26107; ingestion)"}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        return resp.content, ctype

def html_to_text(html: bytes) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()

def pdf_to_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            t = page.extract_text() or ""
            parts.append(t)
        return "\n\n".join(parts).strip()
    except Exception as e:
        print(f"[pdf] extract failed: {e}", file=sys.stderr)
        return ""

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    # char-based approximation: ~4 chars per token
    max_chars = chunk_size * 4
    ov_chars = overlap * 4
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        # try to break on paragraph boundary
        if end < len(text):
            # look back for double newline
            cut = chunk.rfind("\n\n")
            if cut > max_chars * 0.5:
                chunk = chunk[:cut]
                end = start + len(chunk)
        chunks.append(chunk.strip())
        if end >= len(text):
            break
        start = end - ov_chars
    return [c for c in chunks if len(c.strip()) > 50]

def chunk_id(url: str, idx: int) -> str:
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{h}_{idx}"

def build_pinecone(index_name: str, chunks_with_meta: List[dict], quarantine_path: str = "ingestion/data/quarantine.jsonl"):
    """
    Upsert chunks to Pinecone integrated-inference index.

    For each chunk: enrich() -> merge -> validate via validate_chunk.
    Invalid records are appended as JSON to quarantine_path and never sent.
    Valid records are upserted via upsert_records in batches of 96
    (integrated-inference limit is lower than raw-vector upsert).
    """
    try:
        from ingestion.enrich_metadata import enrich
        from ingestion.metadata_schema import validate_chunk
    except ImportError:
        # Fallback when run as script with different cwd
        from enrich_metadata import enrich  # type: ignore
        from metadata_schema import validate_chunk  # type: ignore

    try:
        from pinecone import Pinecone
    except ImportError as e:
        print(f"[pinecone] SDK not installed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        print("[pinecone] ERROR: PINECONE_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    if not index_name:
        print("[pinecone] ERROR: index_name empty / PINECONE_INDEX_NAME not set", file=sys.stderr)
        sys.exit(1)

    q_path = pathlib.Path(quarantine_path)
    q_path.parent.mkdir(parents=True, exist_ok=True)

    pc = Pinecone(api_key=api_key)
    try:
        index = pc.Index(index_name)
    except Exception as e:
        print(f"[pinecone] failed to get index '{index_name}': {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve record text field from index field_map (handles both chunk_text and text)
    try:
        desc = pc.describe_index(index_name)
        embed_info = getattr(desc, "embed", None)
        if embed_info is None and isinstance(desc, dict):
            embed_info = desc.get("embed")
        field_map = {}
        if embed_info is not None:
            if isinstance(embed_info, dict):
                field_map = embed_info.get("field_map", {})
            else:
                field_map = getattr(embed_info, "field_map", {}) or {}
        text_field = field_map.get("text", "chunk_text") if isinstance(field_map, dict) else "chunk_text"
        if not text_field:
            text_field = "chunk_text"
        print(f"[pinecone] index field_map text -> {text_field}")
    except Exception as e:
        print(f"[pinecone] warning: could not resolve field_map, defaulting to chunk_text: {e}", file=sys.stderr)
        text_field = "chunk_text"

    namespace = os.getenv("PINECONE_NAMESPACE", "default")
    if not namespace or not namespace.strip():
        namespace = "default"

    valid_records: List[dict] = []
    quarantined = 0
    crawl_ts = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    for idx, chunk in enumerate(chunks_with_meta):
        content = chunk.get("content") or chunk.get("chunk_text") or chunk.get("text") or ""
        source_url = chunk.get("source_url", "")
        source_title = chunk.get("source_title", "")
        chunk_id_val = chunk.get("chunk_id") or chunk.get("id") or chunk.get("_id") or f"unknown_{idx}"
        chunk_index = chunk.get("chunk_index")
        if chunk_index is None:
            try:
                chunk_index = int(str(chunk_id_val).split("_")[-1])
            except Exception:
                chunk_index = idx
        chunk_count = chunk.get("chunk_count")
        if chunk_count is None:
            chunk_count = len(chunks_with_meta)
        doc_format = chunk.get("doc_format") or chunk.get("kind") or "html"
        doc_format = str(doc_format).lower().strip()
        if doc_format not in ("pdf", "html"):
            doc_format = "html"

        try:
            enriched = enrich(text=content, source_url=source_url, source_title=source_title, doc_format=doc_format)
        except Exception as e:
            raw = {
                "source_url": source_url,
                "source_title": source_title,
                "chunk_id": chunk_id_val,
                "content": content[:500],
                "error": f"enrich failed: {e}",
            }
            with open(q_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(raw, ensure_ascii=False) + "\n")
            quarantined += 1
            continue

        payload = {
            "source_url": enriched.get("source_url", source_url),
            "source_title": enriched.get("source_title", source_title),
            "doc_category": enriched.get("doc_category"),
            "doc_format": enriched.get("doc_format", doc_format),
            "is_standard_number": enriched.get("is_standard_number"),
            "scheme_tag": enriched.get("scheme_tag"),
            "publish_date": chunk.get("publish_date"),
            "gazette_date": chunk.get("gazette_date"),
            "content_hash": enriched.get("content_hash") or hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "crawl_timestamp": chunk.get("crawl_timestamp") or crawl_ts,
            "page_number": chunk.get("page_number"),
            "heading_path": chunk.get("heading_path"),
            "chunk_index": int(chunk_index),
            "chunk_count": int(chunk_count),
            "supersedes": chunk.get("supersedes"),
            "superseded_by": chunk.get("superseded_by"),
            "chunk_id": str(chunk_id_val),
        }

        validated = validate_chunk(payload)
        if validated is None:
            raw = dict(payload)
            raw["content"] = content[:2000]
            raw["_quarantine_reason"] = "ChunkMetadata validation failed"
            try:
                with open(q_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(raw, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"[pinecone] failed to write quarantine {q_path}: {e}", file=sys.stderr)
            quarantined += 1
            continue

        vdict = validated.model_dump()
        vdict_filtered = {k: v for k, v in vdict.items() if v is not None}
        record = {
            "_id": vdict_filtered["chunk_id"],
            text_field: content,
            **vdict_filtered,
        }
        if text_field != "text":
            record["text"] = content
        if text_field != "chunk_text":
            record["chunk_text"] = content
        record["_id"] = str(record["_id"])
        valid_records.append(record)

    print(f"[pinecone] validated {len(valid_records)}/{len(chunks_with_meta)} chunks, quarantined {quarantined}")
    if quarantined > 0:
        print(f"[pinecone] quarantine file: {q_path} ({quarantined} records)")

    if not valid_records:
        print("[pinecone] no valid records to upsert", file=sys.stderr)
        return None

    BATCH = 96
    total = len(valid_records)
    def _upsert_with_retry(batch_records, batch_idx, total_batches):
        stack = [(batch_records, 0)]
        while stack:
            cur_batch, depth = stack.pop()
            retries = 0
            max_retries = 3
            while True:
                try:
                    resp = index.upsert_records(records=cur_batch, namespace=namespace)
                    print(f"[pinecone] upsert batch {batch_idx} ({len(cur_batch)} recs) namespace={namespace} resp={resp}")
                    break
                except Exception as e:
                    msg = str(e)
                    is_rate_limit = "429" in msg or "RESOURCE_EXHAUSTED" in msg or "RateLimit" in type(e).__name__
                    if is_rate_limit and len(cur_batch) > 10 and depth < 4:
                        mid = len(cur_batch) // 2
                        print(f"[pinecone] rate limited on {len(cur_batch)} recs, splitting batch {batch_idx} (depth {depth})", file=sys.stderr)
                        stack.append((cur_batch[mid:], depth + 1))
                        stack.append((cur_batch[:mid], depth + 1))
                        time.sleep(5)
                        break
                    if is_rate_limit and retries < max_retries:
                        retries += 1
                        wait = 65
                        try:
                            headers = getattr(e, "headers", None) or getattr(getattr(e, "response", None), "headers", None)
                            if headers and "retry-after" in {k.lower(): v for k, v in headers.items()}:
                                wait = int(headers.get("Retry-After", wait))
                        except Exception:
                            pass
                        print(f"[pinecone] rate limited (429), waiting {wait}s retry {retries}/{max_retries} batch {batch_idx}: {e}", file=sys.stderr)
                        time.sleep(wait)
                        continue
                    print(f"[pinecone] upsert batch {batch_idx} failed: {e}", file=sys.stderr)
                    raise
            if stack:
                time.sleep(2)

    for i in range(0, total, BATCH):
        batch = valid_records[i : i + BATCH]
        batch_idx = i // BATCH + 1
        _upsert_with_retry(batch, batch_idx, (total + BATCH - 1) // BATCH)
        if i + BATCH < total:
            time.sleep(12)

    print(f"[pinecone] done. upserted {total} records to index '{index_name}' namespace '{namespace}'")
    return index

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fetch", action="store_true", help="skip HTTP fetch, use cached raw/")
    parser.add_argument("--limit", type=int, default=0, help="limit sources for testing")
    parser.add_argument("--offset", type=int, default=0, help="skip first N sources (for additive dry runs on new corpus tail)")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    from ingestion.corpus_urls import CORPUS

    if args.offset or args.limit:
        start = args.offset
        end = (args.offset + args.limit) if args.limit else None
        sources = CORPUS[start:end]
    else:
        sources = CORPUS
    seen_urls = set()
    deduped = []
    dups = 0
    for s in sources:
        if s.url in seen_urls:
            print(f"[dedup] skipping exact duplicate URL already in CORPUS: {s.url}", file=sys.stderr)
            dups += 1
            continue
        seen_urls.add(s.url)
        deduped.append(s)
    if dups:
        print(f"[dedup] skipped {dups} exact duplicate URL(s) in requested slice")
    sources = deduped
    all_chunks: List[dict] = []

    for src in sources:
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", src.url)[:120]
        ext = ".pdf" if src.kind == "pdf" else ".html"
        cache_path = RAW_DIR / f"{safe_name}{ext}"

        data: bytes | None = None
        ctype = ""
        if not args.no_fetch or not cache_path.exists():
            print(f"[fetch] {src.title} -> {src.url}")
            try:
                data, ctype = fetch_url(src.url)
                cache_path.write_bytes(data)
                print(f"[fetch] saved {len(data)} bytes to {cache_path} (ctype={ctype})")
            except Exception as e:
                print(f"[fetch] FAILED {src.url}: {e}", file=sys.stderr)
                if cache_path.exists():
                    print(f"[fetch] using stale cache {cache_path}")
                    data = cache_path.read_bytes()
                else:
                    continue
        else:
            print(f"[cache] {src.title} -> {cache_path}")
            data = cache_path.read_bytes()

        if data is None:
            continue

        if src.kind == "pdf" or cache_path.suffix == ".pdf" or "pdf" in ctype:
            text = pdf_to_text(data)
        else:
            text = html_to_text(data)

        if not text or len(text) < 100:
            print(f"[warn] no text extracted for {src.url} (len={len(text) if text else 0})", file=sys.stderr)
            text = f"Source: {src.title} ({src.url}) — content could not be extracted. Title: {src.title}"

        text = f"Source: {src.title}\nURL: {src.url}\n\n{text}"

        chunks = chunk_text(text)
        print(f"[chunk] {src.title}: {len(chunks)} chunks")
        for idx, ch in enumerate(chunks):
            all_chunks.append({
                "id": chunk_id(src.url, idx),
                "content": ch,
                "source_url": src.url,
                "source_title": src.title,
                "doc_format": src.kind,
                "chunk_index": idx,
                "chunk_count": len(chunks),
            })

    print(f"[total] {len(all_chunks)} chunks from {len(sources)} sources")
    if not all_chunks:
        print("[error] no chunks — aborting build", file=sys.stderr)
        sys.exit(1)

    index_name = os.getenv("PINECONE_INDEX_NAME", "").strip()
    if not index_name:
        print("[error] PINECONE_INDEX_NAME not set", file=sys.stderr)
        sys.exit(1)
    quarantine_path = os.getenv("QUARANTINE_PATH", "ingestion/data/quarantine.jsonl")
    build_pinecone(index_name, all_chunks, quarantine_path=quarantine_path)
    print("[done] ingestion complete")

if __name__ == "__main__":
    main()
