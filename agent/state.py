from typing import TypedDict, Literal

QueryType = Literal["standard_lookup", "product_to_standard", "scheme_process", "lab_query", "consumer_query"]

TargetLanguage = Literal["en", "hi", "te", "ta"]

class GraphState(TypedDict, total=False):
    query: str
    query_type: QueryType
    retrieved_docs: list[dict]  # {content, source_url, source_title, score?}
    used_live_fallback: bool
    answer: str
    citations: list[dict]  # {source_title, source_url, chunk_id?}
    target_language: TargetLanguage  # default "en"
    translated_answer: str | None
