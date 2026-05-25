import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.database import get_db
from app.schemas import ChatRequest, ChatResponse, Citation
from app.services.llm import LLMService
from app.services.retrieval import RetrievalService

router = APIRouter(prefix="/chat", tags=["chat"])
settings = get_settings()


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    started = time.perf_counter()
    source_filters = [item.strip() for item in payload.source_filters if item.strip()]

    llm_service = LLMService()
    retrieval = RetrievalService(db, llm_service)

    chunks = retrieval.retrieve(payload.question, top_k=payload.top_k, source_filters=source_filters)
    confidence = retrieval.confidence_score(chunks)
    context_blocks = retrieval.format_context_blocks(chunks)
    grounded = confidence >= settings.minimum_grounded_confidence
    should_use_web_fallback = (
        settings.web_fallback_enabled
        and confidence < settings.web_fallback_confidence_threshold
    )
    web_references = []
    used_web_fallback = False
    web_fallback_error: str | None = None

    if should_use_web_fallback:
        answer, web_references, used_web_fallback, web_fallback_error = llm_service.generate_answer_with_web_fallback(
            payload.question,
            context_blocks,
        )
    else:
        answer = llm_service.generate_answer(payload.question, context_blocks)

    latency_ms = int((time.perf_counter() - started) * 1000)

    citations = [
        Citation(
            chunk_id=str(chunk.chunk_id),
            title=chunk.title,
            source=chunk.source,
            snippet=llm_service.clean_display_text(chunk.content)[:220],
            score=chunk.score,
        )
        for chunk in chunks
    ]

    for idx, reference in enumerate(web_references, start=1):
        citations.append(
            Citation(
                chunk_id=f"web:{idx}",
                title=f"Web: {reference.title}",
                source=reference.url,
                snippet=reference.snippet,
                score=0.55,
            )
        )

    if should_use_web_fallback and used_web_fallback and not web_references:
        citations.append(
            Citation(
                chunk_id="web:meta",
                title="Web fallback used",
                source="OpenAI web_search",
                snippet="Web search was used, but source metadata was not returned by the tool.",
                score=0.5,
            )
        )
    elif should_use_web_fallback and not used_web_fallback:
        error_text = (web_fallback_error or "Web fallback call failed").strip()[:220]
        citations.append(
            Citation(
                chunk_id="web:error",
                title="Web fallback failed",
                source="OpenAI web_search",
                snippet=error_text,
                score=0.0,
            )
        )
        answer = (
            f"{answer}\n\n"
            "Note: web fallback was attempted but failed. See the 'Web fallback failed' citation for details."
        )

    if should_use_web_fallback and used_web_fallback:
        confidence = max(confidence, 0.55)
        grounded = True
    elif confidence < settings.minimum_grounded_confidence:
        grounded = False
        answer = (
            "I could not find enough grounded evidence in the indexed knowledge base to answer this safely. "
            "Try narrowing the question, selecting a source filter, or ingesting more relevant documents."
        )

    query_log = models.QueryLog(
        question=payload.question,
        answer=answer,
        latency_ms=latency_ms,
        confidence=confidence,
        num_citations=len(citations),
    )
    db.add(query_log)
    db.commit()
    db.refresh(query_log)

    return ChatResponse(
        answer=answer,
        citations=citations,
        confidence=confidence,
        latency_ms=latency_ms,
        query_log_id=str(query_log.id),
        grounded=grounded,
        applied_source_filters=source_filters,
    )
