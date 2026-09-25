"""
Crawler layer for BIS ingestion — discovers beyond curated list with budget guard.
Same-domain BFS (bis.gov.in, manakonline.in), respects robots.txt, depth-limited,
rate-limited with backoff, reuses httpx client + User-Agent from fetch_and_chunk.
"""

from __future__ import annotations

import os
import re
import sys
import time
import json
import hashlib
import pathlib
import datetime
from typing import List, Dict, Any, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from ingestion.fetch_and_chunk import chunk_text, chunk_id, html_to_text, pdf_to_text
from ingestion.enrich_metadata import enrich
from ingestion.metadata_schema import validate_chunk

try:
    from pinecone import Pinecone
except ImportError:
    Pinecone = None  # type: ignore

ALLOWED_ROOTS = {"bis.gov.in", "manakonline.in"}
USER_AGENT = "BIS-Assistant/1.0 (SIH26107; crawler)"
SEED_URLS_DEFAULT = [
    # 3 NEW document URLs not in corpus_urls.py (checked 2026-09-25) — mix of PDF and HTML
    "https://www.bis.gov.in/wp-content/uploads/2024/12/Organisation-Chart-Dec24-Eng-Corrected.pdf",
    "https://www.bis.gov.in/wp-content/uploads/2023/12/Annual-Report-2021-22.pdf",
    "https://www.bis.gov.in/bis-indian-standards/?lang=en&standard_number=IS+10500",
]

QUARANTINE_DIR = pathlib.Path(__file__).parent / "data" / "quarantine"
QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_MAX_TOKENS = 50000

def _is_verbose() -> bool:
    try:
        from agent.debug import is_verbose
        return is_verbose()
    except Exception:
        return os.getenv("DEBUG_VERBOSE", "false").lower() == "true"

def _is_pinecone_debug() -> bool:
    return os.getenv("PINECONE_DEBUG", "").lower() in ("1", "true", "yes", "on")

def _ensure_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
    except Exception:
        pass

def _safe(s: str, max_len: int | None = None) -> str:
    if s is None:
        s = ""
    s = str(s).replace("\r", " ").replace("\n", " ")
    if max_len is not None:
        s = s[:max_len]
    try:
        return s.encode("ascii", errors="replace").decode("ascii", errors="replace")
    except Exception:
        return s.encode("utf-8", errors="replace").decode("utf-8", errors="replace")

_robot_parsers: Dict[str, RobotFileParser] = {}

def _allowed_by_robots(url: str) -> bool:
    try:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in _robot_parsers:
            rp = RobotFileParser()
            rp.set_url(urljoin(origin, "/robots.txt"))
            try:
                rp.read()
            except Exception:
                _robot_parsers[origin] = rp
                return True
            _robot_parsers[origin] = rp
        return _robot_parsers[origin].can_fetch(USER_AGENT, url)
    except Exception:
        return True

def _is_allowed_domain(url: str) -> bool:
    try:
        netloc = urlparse(url).netloc.lower().split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc in ALLOWED_ROOTS
    except Exception:
        return False

def _normalize_url(url: str, base: str | None = None) -> str | None:
    try:
        if base:
            url = urljoin(base, url)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        parsed = parsed._replace(fragment="")
        netloc = parsed.netloc.lower()
        if netloc.endswith(":80"):
            netloc = netloc[:-3]
        if netloc.endswith(":443"):
            netloc = netloc[:-4]
        return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        return None

def _discover_links(html: bytes, base_url: str) -> List[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href")
            if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
                continue
            norm = _normalize_url(href, base_url)
            if not norm or not _is_allowed_domain(norm):
                continue
            path = urlparse(norm).path.lower()
            if path.endswith((".pdf", ".html", ".htm")) or "." not in path.split("/")[-1]:
                links.append(norm)
        seen = set()
        uniq = []
        for l in links:
            if l not in seen:
                seen.add(l)
                uniq.append(l)
        return uniq
    except Exception:
        return []

def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

def _get_pinecone_index():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    api_key = os.getenv("PINECONE_API_KEY", "").strip()
    index_name = os.getenv("PINECONE_INDEX_NAME", "").strip()
    if not api_key or not index_name or Pinecone is None:
        return None, None
    try:
        pc = Pinecone(api_key=api_key)
        idx = pc.Index(index_name)
        return pc, idx
    except Exception as e:
        print(f"[crawler] pinecone init failed: {e}", file=sys.stderr)
        return None, None

def _check_idempotency(index, namespace: str, chunk_id: str, content_hash: str) -> bool:
    try:
        res = index.fetch(ids=[chunk_id], namespace=namespace)
        vectors = getattr(res, "vectors", None)
        if isinstance(res, dict):
            vectors = res.get("vectors") or res.get("records") or {}
        if not vectors:
            return False
        rec = vectors.get(chunk_id)
        if not rec:
            return False
        metadata = getattr(rec, "metadata", None)
        if isinstance(rec, dict):
            metadata = rec.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        existing = metadata.get("content_hash")
        return existing == content_hash
    except Exception as e:
        print(f"[crawler] idempotency check failed for {chunk_id}: {e}", file=sys.stderr)
        return False

def crawl(
    seed_urls: List[str] | None = None,
    max_depth: int = 1,
    max_pages: int = 20,
    quarantine_dir: pathlib.Path | None = None,
    budget_tokens: int | None = None,
) -> Dict[str, Any]:
    _ensure_utf8()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    if seed_urls is None:
        seed_urls = SEED_URLS_DEFAULT
    if quarantine_dir is None:
        quarantine_dir = QUARANTINE_DIR
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    quarantine_file = quarantine_dir / f"quarantine_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"

    max_budget = int(os.getenv("MAX_EMBED_TOKEN_BUDGET", str(budget_tokens if budget_tokens is not None else DEFAULT_MAX_TOKENS)))
    pc, index = _get_pinecone_index()
    if pc is None or index is None:
        print("[crawler] ERROR: Pinecone not configured", file=sys.stderr)
        sys.exit(1)

    try:
        desc = pc.describe_index(os.getenv("PINECONE_INDEX_NAME", "").strip())
        embed_info = getattr(desc, "embed", None)
        field_map = {}
        if embed_info is not None:
            if isinstance(embed_info, dict):
                field_map = embed_info.get("field_map", {})
            else:
                field_map = getattr(embed_info, "field_map", {}) or {}
        text_field = field_map.get("text", "chunk_text") if isinstance(field_map, dict) else "chunk_text"
        if not text_field:
            text_field = "chunk_text"
    except Exception:
        text_field = "chunk_text"

    namespace = os.getenv("PINECONE_NAMESPACE", "default").strip() or "default"

    queue: List[Tuple[str, int]] = [(url, 0) for url in seed_urls]
    visited: Set[str] = set()
    discovered_urls: Set[str] = set(seed_urls)
    processed_docs = 0
    total_chunks = 0
    validated_cnt = 0
    quarantined_cnt = 0
    skipped_idempotent = 0
    tokens_used = 0
    pending_records: List[Dict[str, Any]] = []

    headers = {"User-Agent": USER_AGENT}
    last_fetch = 0.0
    min_interval = 1.0
    verbose = _is_verbose()
    pinecone_debug = _is_pinecone_debug()

    # For summary
    discovered = len(seed_urls)

    def _would_exceed(est: int) -> bool:
        return tokens_used + est > max_budget

    budget_exceeded = False

    while queue and len(visited) < max_pages and not budget_exceeded:
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if not _is_allowed_domain(url):
            print(f"[crawler] skip out-of-domain {_safe(url)}")
            continue
        if not _allowed_by_robots(url):
            print(f"[crawler] blocked by robots.txt {_safe(url)}")
            continue

        now = time.time()
        if now - last_fetch < min_interval:
            time.sleep(min_interval - (now - last_fetch))
        last_fetch = time.time()

        data = None
        ctype = ""
        for attempt in range(3):
            try:
                with httpx.Client(follow_redirects=True, timeout=30, headers=headers) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    data = resp.content
                    ctype = resp.headers.get("content-type", "")
                    break
            except Exception as e:
                if attempt < 2 and ("429" in str(e) or "429" in str(getattr(e, "response", ""))):
                    backoff = 2 ** attempt
                    print(f"[crawler] 429 for {_safe(url)}, backoff {backoff}s", file=sys.stderr)
                    time.sleep(backoff)
                    continue
                print(f"[crawler] fetch failed {_safe(url)}: {e}", file=sys.stderr)
                data = None
                break

        if data is None:
            qrec = {"source_url": url, "error": "fetch failed", "crawl_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")}
            with open(quarantine_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(qrec, ensure_ascii=False) + "\n")
            quarantined_cnt += 1
            continue

        is_pdf = url.lower().endswith(".pdf") or "pdf" in ctype.lower()
        doc_format = "pdf" if is_pdf else "html"

        if doc_format == "pdf":
            text = pdf_to_text(data)
            heading_path = None
            source_title = url.split("/")[-1][:200] or url
        else:
            text = html_to_text(data)
            try:
                soup = BeautifulSoup(data, "html.parser")
                t = soup.find("title")
                source_title = t.get_text().strip()[:200] if t and t.get_text().strip() else url
                h1 = soup.find("h1")
                heading_path = h1.get_text().strip()[:200] if h1 else None
            except Exception:
                source_title = url
                heading_path = None

        if not source_title:
            source_title = url

        if not text or len(text.strip()) < 100:
            qrec = {
                "source_url": url,
                "source_title": source_title,
                "doc_format": doc_format,
                "content_hash": hashlib.sha256((text or "").encode()).hexdigest(),
                "crawl_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                "error": "extraction shorter than 100 chars",
                "text_snippet": (text or "")[:500],
            }
            with open(quarantine_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(qrec, ensure_ascii=False) + "\n")
            quarantined_cnt += 1
            if verbose or pinecone_debug:
                print(f"[crawler] quarantine short {_safe(url)} ({len(text or '')} chars)")
            else:
                print(f"[crawler] quarantine {_safe(url)} short extraction")
            continue

        if doc_format == "html" and depth < max_depth:
            new_links = _discover_links(data, url)
            for link in new_links:
                if link not in visited and link not in discovered_urls:
                    discovered_urls.add(link)
                    queue.append((link, depth + 1))
            if verbose or pinecone_debug:
                print(f"[crawler] discovered {len(new_links)} links from {_safe(url)} depth {depth}")

        full_text = f"Source: {source_title}\nURL: {url}\n\n{text}"
        chunks = chunk_text(full_text)
        if not chunks:
            qrec = {"source_url": url, "source_title": source_title, "error": "chunking 0 chunks", "crawl_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")}
            with open(quarantine_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(qrec, ensure_ascii=False) + "\n")
            quarantined_cnt += 1
            continue

        processed_docs += 1
        total_chunks += len(chunks)

        if verbose or pinecone_debug:
            print(f"[crawler] doc {_safe(url)} | {len(chunks)} chunks | title: {_safe(source_title, 80)}")
        else:
            print(f"[crawler] doc {_safe(url)} | {len(chunks)} chunks | tokens {tokens_used}/{max_budget}")

        # Process chunks
        for idx, ch in enumerate(chunks):
            if budget_exceeded:
                break
            chunk_id_val = chunk_id(url, idx)
            try:
                enriched = enrich(text=ch, source_url=url, source_title=source_title, doc_format=doc_format)
            except Exception as e:
                qrec = {"source_url": url, "source_title": source_title, "chunk_id": chunk_id_val, "error": f"enrich failed: {e}", "crawl_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")}
                with open(quarantine_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(qrec, ensure_ascii=False) + "\n")
                quarantined_cnt += 1
                continue

            crawl_ts = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            payload = {
                "source_url": enriched.get("source_url", url),
                "source_title": enriched.get("source_title", source_title),
                "doc_category": enriched.get("doc_category"),
                "doc_format": enriched.get("doc_format", doc_format),
                "is_standard_number": enriched.get("is_standard_number"),
                "scheme_tag": enriched.get("scheme_tag"),
                "publish_date": None,
                "gazette_date": None,
                "content_hash": enriched.get("content_hash") or hashlib.sha256(ch.encode()).hexdigest(),
                "crawl_timestamp": crawl_ts,
                "page_number": idx + 1 if doc_format == "pdf" else None,
                "heading_path": heading_path if doc_format == "html" else None,
                "chunk_index": idx,
                "chunk_count": len(chunks),
                "supersedes": None,
                "superseded_by": None,
                "chunk_id": chunk_id_val,
                "ingest_source": "crawler",
            }

            validated = validate_chunk(payload)
            if validated is None:
                qrec = dict(payload)
                qrec["content"] = ch[:1000]
                qrec["_quarantine_reason"] = "validation failed"
                with open(quarantine_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(qrec, ensure_ascii=False) + "\n")
                quarantined_cnt += 1
                continue

            content_hash = payload["content_hash"]
            if _check_idempotency(index, namespace, chunk_id_val, content_hash):
                skipped_idempotent += 1
                if verbose or pinecone_debug:
                    print(f"[crawler] skip idempotent {chunk_id_val} hash {_safe(content_hash[:8])}")
                continue

            est = _estimate_tokens(ch)
            if _would_exceed(est):
                print(f"[crawler] token budget would exceed: used {tokens_used} + est {est} > {max_budget} — stopping", file=sys.stderr)
                budget_exceeded = True
                break

            # Check pending batch would exceed
            pending_est = sum(_estimate_tokens(r.get(text_field, "")) for r in pending_records)
            if tokens_used + pending_est + est > max_budget:
                # Flush pending first
                if pending_records:
                    batch_est = sum(_estimate_tokens(r.get(text_field, "")) for r in pending_records)
                    if tokens_used + batch_est <= max_budget:
                        try:
                            resp = index.upsert_records(records=pending_records, namespace=namespace)
                            # Try to get actual usage
                            batch_used = None
                            if hasattr(resp, "usage") and getattr(resp, "usage"):
                                try:
                                    batch_used = resp.usage.embed_total_tokens  # type: ignore
                                except Exception:
                                    pass
                            if isinstance(batch_used, int):
                                tokens_used += batch_used
                            else:
                                tokens_used += batch_est
                            print(f"[crawler] upsert batch {len(pending_records)} | tokens batch {batch_est} total {tokens_used}/{max_budget} remaining {max_budget - tokens_used}")
                            if verbose or pinecone_debug:
                                print(f"[crawler] token budget: used {tokens_used}/{max_budget} remaining {max_budget - tokens_used}")
                        except Exception as e:
                            print(f"[crawler] upsert failed: {e}", file=sys.stderr)
                        pending_records = []
                    else:
                        print(f"[crawler] budget would exceed for pending batch — stopping", file=sys.stderr)
                        budget_exceeded = True
                        break
                if _would_exceed(est):
                    print(f"[crawler] still would exceed after flush — stopping", file=sys.stderr)
                    budget_exceeded = True
                    break

            vdict = validated.model_dump()
            vdict_filtered = {k: v for k, v in vdict.items() if v is not None}
            record = {"_id": vdict_filtered["chunk_id"], text_field: ch, **vdict_filtered}
            if text_field != "text":
                record["text"] = ch
            if text_field != "chunk_text":
                record["chunk_text"] = ch
            record["_id"] = str(record["_id"])
            pending_records.append(record)
            validated_cnt += 1

            if len(pending_records) >= 96:
                est_batch = sum(_estimate_tokens(r.get(text_field, "")) for r in pending_records)
                if _would_exceed(est_batch):
                    print(f"[crawler] budget would exceed for batch 96: used {tokens_used} + {est_batch} > {max_budget} — stopping", file=sys.stderr)
                    budget_exceeded = True
                    break
                try:
                    resp = index.upsert_records(records=pending_records, namespace=namespace)
                    batch_used = None
                    if hasattr(resp, "usage") and getattr(resp, "usage"):
                        try:
                            batch_used = resp.usage.embed_total_tokens  # type: ignore
                        except Exception:
                            pass
                    if isinstance(batch_used, int):
                        tokens_used += batch_used
                    else:
                        tokens_used += est_batch
                    print(f"[crawler] upsert batch {len(pending_records)} | tokens {est_batch} total {tokens_used}/{max_budget} remaining {max_budget - tokens_used}")
                except Exception as e:
                    msg = str(e)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "RateLimit" in type(e).__name__:
                        print(f"[crawler] rate limited, splitting batch", file=sys.stderr)
                        time.sleep(5)
                        # Split and retry as two halves
                        mid = len(pending_records)//2
                        for half in [pending_records[:mid], pending_records[mid:]]:
                            est_half = sum(_estimate_tokens(r.get(text_field, "")) for r in half)
                            if _would_exceed(est_half):
                                print(f"[crawler] budget would exceed for half batch — stopping", file=sys.stderr)
                                budget_exceeded = True
                                break
                            try:
                                resp2 = index.upsert_records(records=half, namespace=namespace)
                                batch_used2 = est_half
                                if hasattr(resp2, "usage") and getattr(resp2, "usage"):
                                    try:
                                        batch_used2 = resp2.usage.embed_total_tokens  # type: ignore
                                    except Exception:
                                        pass
                                tokens_used += batch_used2 if isinstance(batch_used2, int) else est_half
                                print(f"[crawler] upsert half batch {len(half)} | tokens {est_half} total {tokens_used}")
                            except Exception as e2:
                                print(f"[crawler] half batch failed: {e2}", file=sys.stderr)
                        pending_records = []
                        if budget_exceeded:
                            break
                    else:
                        print(f"[crawler] upsert failed: {e}", file=sys.stderr)
                pending_records = []
                if budget_exceeded:
                    break

        if budget_exceeded:
            print(f"[crawler] stopping: token budget exceeded")
            break

    # Flush remaining pending
    if pending_records and not budget_exceeded:
        est_pending = sum(_estimate_tokens(r.get(text_field, "")) for r in pending_records)
        if tokens_used + est_pending <= max_budget:
            try:
                resp = index.upsert_records(records=pending_records, namespace=namespace)
                batch_used = est_pending
                if hasattr(resp, "usage") and getattr(resp, "usage"):
                    try:
                        batch_used = resp.usage.embed_total_tokens  # type: ignore
                    except Exception:
                        pass
                tokens_used += batch_used if isinstance(batch_used, int) else est_pending
                print(f"[crawler] upsert final batch {len(pending_records)} tokens {batch_used} total {tokens_used} remaining {max_budget - tokens_used}")
            except Exception as e:
                print(f"[crawler] final upsert failed: {e}", file=sys.stderr)
        else:
            print(f"[crawler] skipping final pending batch: would exceed budget {tokens_used}+{est_pending}>{max_budget}", file=sys.stderr)
            for r in pending_records:
                qrec = {"chunk_id": r["_id"], "source_url": r.get("source_url"), "error": "skipped due token budget", "crawl_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")}
                with open(quarantine_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(qrec, ensure_ascii=False) + "\n")
                quarantined_cnt += 1

    # Final summary
    print("\n" + "="*78)
    print(f"[crawler] SUMMARY | crawled {processed_docs} docs (discovered {len(discovered_urls)} urls, visited {len(visited)})")
    print(f"[crawler] chunks: total {total_chunks} validated {validated_cnt} quarantined {quarantined_cnt} skipped_idempotent {skipped_idempotent}")
    print(f"[crawler] tokens: consumed {tokens_used}/{max_budget} remaining {max_budget - tokens_used} (monthly 5M, used ~1.5M prior, this run budget {max_budget})")
    print(f"[crawler] quarantine file: {quarantine_file} ({quarantined_cnt} records)")
    print(f"[crawler] Pinecone index: {os.getenv('PINECONE_INDEX_NAME')} namespace {namespace} ingest_source=crawler")
    print("="*78 + "\n")
    monthly_remaining = 5000000 - 1500000 - tokens_used
    print(f"[crawler] monthly Pinecone budget: 5M total, ~1.5M used prior, this run {tokens_used}, remaining ~{monthly_remaining}")

    return {
        "documents_crawled": processed_docs,
        "discovered_urls": len(discovered_urls),
        "chunks_total": total_chunks,
        "validated": validated_cnt,
        "quarantined": quarantined_cnt,
        "skipped_idempotent": skipped_idempotent,
        "tokens_used": tokens_used,
        "tokens_remaining_budget": max_budget - tokens_used,
        "tokens_remaining_monthly": monthly_remaining,
        "quarantine_file": str(quarantine_file),
    }

def main():
    import argparse
    parser = argparse.ArgumentParser(description="BIS crawler — Pinecone budget-guarded")
    parser.add_argument("--seed", action="append", dest="seed_urls", help="Seed URL (can be repeated)")
    parser.add_argument("--depth", type=int, default=1, help="BFS depth (default 1)")
    parser.add_argument("--max-pages", type=int, default=20, help="Max pages to crawl")
    parser.add_argument("--budget", type=int, default=None, help="Override MAX_EMBED_TOKEN_BUDGET")
    args = parser.parse_args()

    seed_urls = args.seed_urls or SEED_URLS_DEFAULT
    env_seeds = os.getenv("CRAWLER_SEED_URLS")
    if env_seeds:
        seed_urls = [s.strip() for s in env_seeds.split(",") if s.strip()]

    budget = args.budget or int(os.getenv("MAX_EMBED_TOKEN_BUDGET", str(DEFAULT_MAX_TOKENS)))

    print(f"[crawler] starting with {len(seed_urls)} seeds, depth={args.depth}, max_pages={args.max_pages}, budget={budget}")
    for s in seed_urls:
        print(f"[crawler] seed: {_safe(s)}")

    result = crawl(seed_urls=seed_urls, max_depth=args.depth, max_pages=args.max_pages, budget_tokens=budget)
    if result["tokens_used"] >= budget:
        print("[crawler] stopped: token budget reached (clean exit, no partial state)")
    sys.exit(0)

if __name__ == "__main__":
    main()
