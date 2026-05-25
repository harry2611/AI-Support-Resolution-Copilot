from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app import models
from app.database import get_db
from app.schemas import Citation, TicketDraftRequest, TicketDraftResponse
from app.services.guardrails import GuardrailService
from app.services.llm import LLMService
from app.services.retrieval import RetrievalService

router = APIRouter(prefix="/tickets", tags=["tickets"])
settings = get_settings()


@router.post("/draft", response_model=TicketDraftResponse)
def draft_ticket_reply(payload: TicketDraftRequest, db: Session = Depends(get_db)) -> TicketDraftResponse:
    source_filters = [item.strip() for item in payload.source_filters if item.strip()]
    guardrails = GuardrailService()
    customer_guardrails = guardrails.sanitize_user_text(payload.customer_message)
    guardrail_events = customer_guardrails.events()
    llm_service = LLMService()
    retrieval = RetrievalService(db, llm_service)

    if customer_guardrails.blocked:
        response_text = (
            "I can’t draft a customer-facing response from this request because it triggered prompt-injection "
            "or policy-protection checks. Please rewrite it as a normal customer issue summary."
        )
        sanitized_response = guardrails.sanitize_output_text(response_text).sanitized_text
        draft = models.TicketDraft(
            customer_message=customer_guardrails.sanitized_text,
            drafted_response=sanitized_response,
            citations=[],
            status="blocked_guardrail",
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)
        return TicketDraftResponse(
            draft_id=str(draft.id),
            response=sanitized_response,
            citations=[],
            grounded=False,
            applied_source_filters=source_filters,
            guardrail_events=guardrail_events,
        )

    chunks = retrieval.retrieve(customer_guardrails.sanitized_text, top_k=payload.top_k, source_filters=source_filters)
    confidence = retrieval.confidence_score(chunks)
    context_blocks = retrieval.format_context_blocks(chunks)
    context_blocks, context_events = guardrails.sanitize_context_blocks(context_blocks)
    guardrail_events.extend(context_events)
    grounded = confidence >= settings.minimum_ticket_grounded_confidence
    if grounded:
        response_text = llm_service.generate_ticket_draft(customer_guardrails.sanitized_text, context_blocks)
    else:
        response_text = (
            "I do not have enough grounded evidence to draft a safe customer-facing response yet. "
            "Please narrow the source filters, ask a more specific support question, or ingest more relevant documentation first."
        )

    output_guardrails = guardrails.sanitize_output_text(response_text)
    response_text = output_guardrails.sanitized_text
    guardrail_events.extend(output_guardrails.events())

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

    draft = models.TicketDraft(
        customer_message=customer_guardrails.sanitized_text,
        drafted_response=response_text,
        citations=[citation.model_dump() for citation in citations],
        status="pending_review",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    return TicketDraftResponse(
        draft_id=str(draft.id),
        response=response_text,
        citations=citations,
        grounded=grounded,
        applied_source_filters=source_filters,
        guardrail_events=sorted(set(guardrail_events)),
    )
