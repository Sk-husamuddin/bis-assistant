"""
ChunkMetadata schema for BIS ingestion.

All chunks must validate against this model before indexing.
Failures are quarantined via validate_chunk() which never raises.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ValidationError


class ChunkMetadata(BaseModel):
    source_url: str
    source_title: str
    doc_category: Literal[
        "Act",
        "Regulation",
        "Amendment",
        "Scheme Guideline",
        "Gazette Notification",
        "IS Standard",
        "Circular",
        "Unclassified",
    ]
    doc_format: Literal["pdf", "html"]
    is_standard_number: Optional[str] = None
    scheme_tag: Optional[Literal["ISI", "CRS", "HALLMARKING", "MSCS", "FMCS"]] = None
    publish_date: Optional[str] = None
    gazette_date: Optional[str] = None
    content_hash: str
    crawl_timestamp: str
    page_number: Optional[int] = None
    heading_path: Optional[str] = None
    chunk_index: int
    chunk_count: int
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    chunk_id: str


def validate_chunk(data: dict) -> Optional[ChunkMetadata]:
    """
    Validate a dict against ChunkMetadata.

    Returns ChunkMetadata on success, None on failure (never raises).
    Callers should route None results to quarantine.
    """
    try:
        return ChunkMetadata.model_validate(data)
    except (ValidationError, ValueError, TypeError, AttributeError):
        return None
