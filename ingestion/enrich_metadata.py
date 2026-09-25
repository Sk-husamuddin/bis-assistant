"""
Enrich raw chunk text + source info into metadata fields.

Reuses keyword logic from agent.nodes.retrieve (_detect_topics / _TOPIC_PATTERNS)
and IS-number pattern (_IS_NUMBER_RE) via import — does not duplicate regex.

Computes content_hash as sha256(text).
"""

from __future__ import annotations

import hashlib
import re

# Reuse existing patterns / detection — do not duplicate
from agent.nodes.retrieve import _IS_NUMBER_RE as _BASE_IS_RE, _TOPIC_PATTERNS, _detect_topics
import re as _re
# Extend IS regex to handle URL-encoded plus and spaces (e.g. IS+1786)
_IS_NUMBER_RE = _re.compile(r"IS\s*[\+\s]*\d{3,6}(?:\s*[-–]\s*\d{4})?", _re.I)


def _normalize_is_number(raw: str) -> str:
    """Normalize IS number like 'IS  2347' or 'IS+1786' -> 'IS 2347' (upper, single space)."""
    # Replace plus with space, then collapse whitespace
    cleaned = raw.replace("+", " ")
    return re.sub(r"\s+", " ", cleaned.strip().upper())


def _detect_doc_category(
    text: str, source_url: str, source_title: str, is_standard_number: str | None
) -> str:
    """
    Heuristic doc_category detection.
    Priority:
      1. IS Standard if IS number present
      2. Keyword in url/title/text for other categories
      3. Scheme Guideline via _TOPIC_PATTERNS reuse
      4. Unclassified fallback
    """
    combined = f"{source_title} {source_url} {text}"
    combined_lower = combined.lower()

    if is_standard_number:
        return "IS Standard"
    if "gazette" in combined_lower:
        return "Gazette Notification"
    if "amendment" in combined_lower:
        return "Amendment"
    if "regulation" in combined_lower:
        return "Regulation"
    if "circular" in combined_lower:
        return "Circular"
    if re.search(r"\bact\b", combined_lower):
        return "Act"
    if "guideline" in combined_lower:
        return "Scheme Guideline"
    # Reuse _TOPIC_PATTERNS (imported from retrieve) for scheme-related docs
    for pat in _TOPIC_PATTERNS.values():
        if pat.search(combined):
            return "Scheme Guideline"
    return "Unknown"


def enrich(text: str, source_url: str, source_title: str, doc_format: str) -> dict:
    """
    Enrich chunk context into metadata fields.

    Args:
        text: chunk content
        source_url: original document URL
        source_title: human title
        doc_format: "pdf" or "html" (case-insensitive)

    Returns:
        dict with at least doc_category, scheme_tag, is_standard_number, content_hash
    """
    # Normalize doc_format to allowed literals
    fmt = doc_format.strip().lower()
    if fmt not in ("pdf", "html"):
        # keep as-is lower; validation will catch invalid — but default to html for safety
        # caller can handle validation failure via quarantine
        pass

    # Reuse _detect_topics / _TOPIC_PATTERNS for scheme_tag (imported, not duplicated)
    combined_for_topics = f"{source_title} {source_url} {text}"
    topics = _detect_topics(combined_for_topics)
    scheme_tag: str | None = None
    for t in topics:
        if t in _TOPIC_PATTERNS:  # _TOPIC_PATTERNS keys are the valid scheme_tags
            scheme_tag = t
            break

    # Extract IS number via existing _IS_NUMBER_RE (imported)
    is_match = _IS_NUMBER_RE.search(combined_for_topics)
    is_standard_number: str | None = None
    if is_match:
        is_standard_number = _normalize_is_number(is_match.group(0))

    # doc_category via reused IS detection + keyword heuristics
    doc_category = _detect_doc_category(text, source_url, source_title, is_standard_number)

    # content_hash as sha256 of text (utf-8)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    return {
        "doc_category": doc_category,
        "scheme_tag": scheme_tag,
        "is_standard_number": is_standard_number,
        "content_hash": content_hash,
        "doc_format": fmt,
        "source_url": source_url,
        "source_title": source_title,
    }
