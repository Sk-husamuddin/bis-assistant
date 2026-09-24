"""
Provision a Pinecone serverless index bound to the llama-text-embed-v2
integrated inference model.

Uses Pinecone Python SDK's `create_index_for_model` with a field_map
mapping ``text`` → the record field that holds chunk content (``chunk_text``).

Env (via python-dotenv):
  PINECONE_API_KEY      – required
  PINECONE_INDEX_NAME   – required
  PINECONE_CLOUD        – e.g. "aws" (default: "aws")
  PINECONE_REGION       – e.g. "us-east-1" (default: "us-east-1")

Usage:
  python -m ingestion.provision_pinecone
  python ingestion/provision_pinecone.py
"""

import os
import sys

from dotenv import load_dotenv

# Load .env from project root and current directory (python-dotenv handles both)
load_dotenv()
# Also try to load from parent of ingestion/ if run as script
try:
    import pathlib

    # bis-assistant/.env is one level above ingestion/
    env_path = pathlib.Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    # repo root C:/sih2026/.env
    repo_env = pathlib.Path(__file__).resolve().parents[2] / ".env"
    if repo_env.exists():
        load_dotenv(dotenv_path=repo_env, override=False)
except Exception:
    pass


def main() -> None:
    api_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME")
    cloud = os.getenv("PINECONE_CLOUD", "aws")
    region = os.getenv("PINECONE_REGION", "us-east-1")

    if not api_key:
        print("ERROR: PINECONE_API_KEY is not set (check .env)", file=sys.stderr)
        sys.exit(1)
    if not index_name:
        print("ERROR: PINECONE_INDEX_NAME is not set (check .env)", file=sys.stderr)
        sys.exit(1)

    # Import here so env validation happens even without pinecone installed
    try:
        from pinecone import Pinecone
    except ImportError as e:
        print(f"ERROR: pinecone SDK not installed: {e}", file=sys.stderr)
        print("Install with: pip install pinecone", file=sys.stderr)
        sys.exit(1)

    pc = Pinecone(api_key=api_key)

    # If index already exists, just describe it (idempotent)
    try:
        if pc.has_index(index_name):
            print(f"Index '{index_name}' already exists — skipping creation.")
            desc = pc.describe_index(index_name)
            print(desc)
            return
    except Exception:
        # has_index may fail on older SDKs — fall through to create attempt
        pass

    # Create serverless index bound to llama-text-embed-v2 integrated model
    # field_map maps model input field "text" -> record field "chunk_text" that holds chunk content
    try:
        pc.create_index_for_model(
            name=index_name,
            cloud=cloud,
            region=region,
            embed={
                "model": "llama-text-embed-v2",
                "field_map": {"text": "chunk_text"},
            },
        )
    except Exception as e:
        # If index already exists (race), describe it instead of failing
        msg = str(e).lower()
        if "already exists" in msg or "alreadyexists" in msg or "409" in msg:
            print(f"Index '{index_name}' already exists (create returned conflict).")
            try:
                desc = pc.describe_index(index_name)
                print(desc)
                return
            except Exception as desc_e:
                print(f"Failed to describe index after conflict: {desc_e}", file=sys.stderr)
                sys.exit(1)
        print(f"ERROR: failed to create index '{index_name}': {e}", file=sys.stderr)
        sys.exit(1)

    # Print index description on success
    try:
        desc = pc.describe_index(index_name)
        print(desc)
    except Exception as e:
        print(f"Index '{index_name}' created but failed to describe: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
