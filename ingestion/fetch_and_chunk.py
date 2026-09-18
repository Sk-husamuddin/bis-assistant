"""
Fetch, clean, chunk, embed, store in Chroma.
Usage: python -m ingestion.fetch_and_chunk [--no-fetch] [--persist-dir ingestion/data/chroma]
Idempotent: clears and re-creates collection on each run.
"""
import argparse
import os
import re
import sys
import hashlib
import pathlib
from typing import List

import httpx
from bs4 import BeautifulSoup

# Chroma + embeddings — lazy import to allow --help without deps
CHUNK_SIZE = 800  # tokens approx ~ chars/4
CHUNK_OVERLAP = 100
COLLECTION_NAME = "bis_corpus"

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

def build_chroma(persist_dir: str, chunks_with_meta: List[dict], append: bool = False):
    import chromadb
    from chromadb.utils import embedding_functions

    model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
    print(f"[chroma] embedding model: {model_name}")
    print(f"[chroma] persist dir: {persist_dir}")
    print(f"[chroma] mode: {'APPEND' if append else 'RECREATE'}")

    # Use sentence-transformers embedding function (local)
    try:
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
    except Exception as e:
        print(f"[chroma] sentence-transformer ef failed ({e}), falling back to default ef", file=sys.stderr)
        ef = embedding_functions.DefaultEmbeddingFunction()

    client = chromadb.PersistentClient(path=persist_dir)
    if append:
        col = client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=ef, metadata={"hnsw:space": "cosine"})
        count_before = col.count()
        print(f"[chroma] append mode — count_before={count_before}")
        # Deduplicate: only add ids not already present
        if count_before > 0:
            existing = set(col.get(include=[])["ids"])
            filtered = [c for c in chunks_with_meta if c["id"] not in existing]
            skipped = len(chunks_with_meta) - len(filtered)
            if skipped:
                print(f"[chroma] dedup: {skipped} chunks already exist, {len(filtered)} new")
            chunks_with_meta = filtered
            if not chunks_with_meta:
                print(f"[chroma] nothing new to add, count remains {count_before}")
                return col
    else:
        # recreate collection for idempotency
        try:
            client.delete_collection(COLLECTION_NAME)
            print(f"[chroma] deleted existing collection {COLLECTION_NAME}")
        except Exception:
            pass
        col = client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=ef, metadata={"hnsw:space": "cosine"})

    ids = [c["id"] for c in chunks_with_meta]
    docs = [c["content"] for c in chunks_with_meta]
    metas = [{"source_url": c["source_url"], "source_title": c["source_title"], "chunk_id": c["id"]} for c in chunks_with_meta]

    # batch add (chromadb limit)
    B = 100
    for i in range(0, len(ids), B):
        col.add(ids=ids[i:i+B], documents=docs[i:i+B], metadatas=metas[i:i+B])
        print(f"[chroma] added batch {i//B+1} ({min(i+B, len(ids))}/{len(ids)})")

    print(f"[chroma] done. count={col.count()}")
    return col

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fetch", action="store_true", help="skip HTTP fetch, use cached raw/")
    parser.add_argument("--persist-dir", default=os.getenv("CHROMA_PERSIST_DIR", str(pathlib.Path(__file__).parent / "data" / "chroma")))
    parser.add_argument("--limit", type=int, default=0, help="limit sources for testing")
    parser.add_argument("--offset", type=int, default=0, help="skip first N sources (for additive dry runs on new corpus tail)")
    parser.add_argument("--append", action="store_true", help="append to existing collection without deleting (additive mode)")
    args = parser.parse_args()

    # dotenv
    try:
        from dotenv import load_dotenv
        load_dotenv()
        # re-read persist dir after dotenv if not explicitly passed
        if args.persist_dir == str(pathlib.Path(__file__).parent / "data" / "chroma"):
            args.persist_dir = os.getenv("CHROMA_PERSIST_DIR", args.persist_dir)
    except Exception:
        pass

    from ingestion.corpus_urls import CORPUS

    # Support --offset + --limit for additive dry runs (new corpus is appended at tail)
    if args.offset or args.limit:
        start = args.offset
        end = (args.offset + args.limit) if args.limit else None
        sources = CORPUS[start:end]
    else:
        sources = CORPUS
    # Deduplicate exact-URL duplicates before fetch (spec: skip exact URL duplicates)
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

        # extract text
        if src.kind == "pdf" or cache_path.suffix == ".pdf" or "pdf" in ctype:
            text = pdf_to_text(data)
        else:
            text = html_to_text(data)

        if not text or len(text) < 100:
            print(f"[warn] no text extracted for {src.url} (len={len(text) if text else 0})", file=sys.stderr)
            # store raw snippet so retrieval still has something to ground on
            text = f"Source: {src.title} ({src.url}) — content could not be extracted. Title: {src.title}"

        # prepend title for better retrieval
        text = f"Source: {src.title}\nURL: {src.url}\n\n{text}"

        chunks = chunk_text(text)
        print(f"[chunk] {src.title}: {len(chunks)} chunks")
        for idx, ch in enumerate(chunks):
            all_chunks.append({
                "id": chunk_id(src.url, idx),
                "content": ch,
                "source_url": src.url,
                "source_title": src.title,
            })

    print(f"[total] {len(all_chunks)} chunks from {len(sources)} sources")
    if not all_chunks:
        print("[error] no chunks — aborting chroma build", file=sys.stderr)
        sys.exit(1)

    build_chroma(args.persist_dir, all_chunks, append=args.append)
    print("[done] ingestion complete")

if __name__ == "__main__":
    main()
