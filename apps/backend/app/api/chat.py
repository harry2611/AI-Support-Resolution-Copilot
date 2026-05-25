import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.database import get_db
from app.schemas import ChatRequest, ChatResponse, Citation
from app.services.guardrails import GuardrailService
from app.services.llm import LLMService
from app.services.retrieval import RetrievalService

router = APIRouter(prefix="/chat", tags=["chat"])
settings = get_settings()


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    started = time.perf_counter()
    source_filters = [item.strip() for item in payload.source_filters if item.strip()]
    guardrails = GuardrailService()
    question_guardrails = guardrails.sanitize_user_text(payload.question)
    guardrail_events = question_guardrails.events()

    llm_service = LLMService()
    retrieval = RetrievalService(db, llm_service)

    if question_guardrails.blocked:
        answer = (
            "I can help with grounded support questions, but I can’t process this request because it triggered "
            "prompt-injection or policy-protection checks. Please rephrase it as a normal support or retrieval query."
        )
        sanitized_answer = guardrails.sanitize_output_text(answer).sanitized_text
        latency_ms = int((time.perf_counter() - started) * 1000)
        query_log = models.QueryLog(
            question=question_guardrails.sanitized_text,
            answer=sanitized_answer,
            latency_ms=latency_ms,
            confidence=0.0,
            num_citations=0,
        )
        db.add(query_log)
        db.commit()
        db.refresh(query_log)
        return ChatResponse(
            answer=sanitized_answer,
            citations=[],
            confidence=0.0,
            latency_ms=latency_ms,
            query_log_id=str(query_log.id),
            grounded=False,
            applied_source_filters=source_filters,
            guardrail_events=guardrail_events,
        )

    chunks = retrieval.retrieve(question_guardrails.sanitized_text, top_k=payload.top_k, source_filters=source_filters)
    confidence = retrieval.confidence_score(chunks)
    context_blocks = retrieval.format_context_blocks(chunks)
    context_blocks, context_events = guardrails.sanitize_context_blocks(context_blocks)
    guardrail_events.extend(context_events)
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
            question_guardrails.sanitized_text,
            context_blocks,
        )
    else:
        answer = llm_service.generate_answer(question_guardrails.sanitized_text, context_blocks)

    output_guardrails = guardrails.sanitize_output_text(answer)
    answer = output_guardrails.sanitized_text
    guardrail_events.extend(output_guardrails.events())

    latency_ms = int((time.perf_counter() - started) * 1000)

    citations = [
        Citation(
            chunk_id=str(chunk.chunk_id),
            title=chunk.title,
            source=chunk.source,
            snippet=guardrails.sanitize_output_text(llm_service.clean_display_text(chunk.content)[:220]).sanitized_text,
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
        question=question_guardrails.sanitized_text,
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
        guardrail_events=sorted(set(guardrail_events)),
    )
