"""
Pre-cache English audio for the 6 locked demo queries.
Phase 1: 6 files -> static/audio_cache/demo_{i}_en.mp3
Phase 2 extension: 6 * 4 langs = 24 files -> static/audio_cache/demo_{i}_{lang}.mp3
Usage: python -m ingestion.precache_audio [--lang en] [--force]
For Phase 1 always call live /speak; cache is for demo reliability fallback only.
"""
import argparse
import hashlib
import pathlib
import sys

# Ensure project root on path when run as `python -m ingestion.precache_audio`
HERE = pathlib.Path(__file__).resolve()
PROJECT_ROOT = HERE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.corpus_urls import DEMO_QUERIES

# Phase 1 langs, Phase 2 adds hi/te/ta
ALL_LANGS = ["en", "hi", "te", "ta"]

def query_id_for(query: str) -> str:
    # stable id matching frontend hash: demo_0..5
    for i, d in enumerate(DEMO_QUERIES):
        if d["query"] == query:
            return f"demo_{i}"
    # fallback hash
    h = hashlib.md5(query.encode()).hexdigest()[:8]
    return f"q_{h}"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en", choices=ALL_LANGS, help="single lang to precache, or use --all for 4 langs")
    parser.add_argument("--all", action="store_true", help="precache all 4 langs (24 files)")
    parser.add_argument("--force", action="store_true", help="overwrite existing mp3s")
    args = parser.parse_args()

    langs = ALL_LANGS if args.all else [args.lang]

    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:
        pass

    from agent.graph import run_query
    from api.speak import clean_for_speech
    from gtts import gTTS

    out_dir = PROJECT_ROOT / "static" / "audio_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[precache] output dir: {out_dir}")
    print(f"[precache] langs: {langs}, force={args.force}")

    generated = 0
    manifest = {}
    for lang in langs:
        for i, dq in enumerate(DEMO_QUERIES):
            q = dq["query"]
            qid = f"demo_{i}"
            out_path = out_dir / f"{qid}_{lang}.mp3"
            if out_path.exists() and not args.force:
                print(f"[precache] skip exists {out_path.name}")
                # still populate manifest for existing file if possible
                try:
                    # need cleaned hash; re-run to get text if not cached
                    try:
                        result = run_query(q, target_language=lang)  # type: ignore
                    except TypeError:
                        result = run_query(q)
                    text = result.get("translated_answer") or result.get("answer", "")
                    cleaned = clean_for_speech(text) if text else ""
                    if cleaned:
                        h = hashlib.md5(cleaned.encode()).hexdigest()[:12]
                        manifest[h] = {"file": out_path.name, "lang": lang, "qid": qid, "hash_path": f"hash_{h}_{lang}.mp3"}
                        # ensure hash copy exists
                        hash_path = out_dir / f"hash_{h}_{lang}.mp3"
                        if not hash_path.exists():
                            import shutil
                            shutil.copyfile(out_path, hash_path)
                except Exception:
                    pass
                continue
            print(f"[precache] {qid}_{lang}: {q[:60]}...")
            # For multilingual precache (Phase 2), we need translated answer if lang != en
            # Phase 1: run_query returns English answer via graph
            # For Phase 2, pass target_language through if available
            try:
                try:
                    # Phase 2 run_query will accept target_language
                    result = run_query(q, target_language=lang)  # type: ignore
                except TypeError:
                    result = run_query(q)
                    # if non-en requested but graph doesn't support yet, translate is not available
                    # just use English for now (Phase 1)
                    if lang != "en":
                        print(f"[precache] warn: lang {lang} requested but graph doesn't support target_language yet, using en")
                # Prefer translated_answer if present, else answer
                text = result.get("translated_answer") or result.get("answer", "")
                if not text:
                    print(f"[precache] warn: empty answer for {qid}")
                    continue
                cleaned = clean_for_speech(text)
                if not cleaned:
                    print(f"[precache] warn: empty cleaned for {qid}_{lang}")
                    continue
                # gTTS can throw on network; catch and continue
                tts = gTTS(text=cleaned, lang=lang)
                tts.save(str(out_path))
                print(f"[precache] saved {out_path} ({out_path.stat().st_blocks if hasattr(out_path.stat(), 'st_blocks') else out_path.stat().st_size} bytes)")
                # also save hash copy for /speak cache lookup
                h = hashlib.md5(cleaned.encode()).hexdigest()[:12]
                hash_path = out_dir / f"hash_{h}_{lang}.mp3"
                import shutil
                shutil.copyfile(out_path, hash_path)
                manifest[h] = {"file": out_path.name, "lang": lang, "qid": qid, "hash_path": hash_path.name}
                generated += 1
            except Exception as e:
                print(f"[precache] failed {qid}_{lang}: {e}", file=sys.stderr)

    # save manifest for /speak cache lookup
    import json
    manifest_path = out_dir / "manifest.json"
    try:
        # merge with existing
        existing = {}
        if manifest_path.exists():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing.update(manifest)
        manifest_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[precache] manifest saved {manifest_path} ({len(existing)} entries)")
    except Exception as e:
        print(f"[precache] manifest save failed: {e}", file=sys.stderr)

    print(f"[precache] done. generated {generated} files in {out_dir}")
    # list
    for p in sorted(out_dir.glob("*.mp3")):
        print(f"  {p.name} {p.stat().st_size} bytes")

if __name__ == "__main__":
    main()
