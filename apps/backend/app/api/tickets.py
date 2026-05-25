from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app import models
from app.database import get_db
from app.schemas import Citation, TicketDraftRequest, TicketDraftResponse
from app.services.llm import LLMService
from app.services.retrieval import RetrievalService

router = APIRouter(prefix="/tickets", tags=["tickets"])
settings = get_settings()


@router.post("/draft", response_model=TicketDraftResponse)
def draft_ticket_reply(payload: TicketDraftRequest, db: Session = Depends(get_db)) -> TicketDraftResponse:
    source_filters = [item.strip() for item in payload.source_filters if item.strip()]
    llm_service = LLMService()
    retrieval = RetrievalService(db, llm_service)

    chunks = retrieval.retrieve(payload.customer_message, top_k=payload.top_k, source_filters=source_filters)
    confidence = retrieval.confidence_score(chunks)
    context_blocks = retrieval.format_context_blocks(chunks)
    grounded = confidence >= settings.minimum_ticket_grounded_confidence
    if grounded:
        response_text = llm_service.generate_ticket_draft(payload.customer_message, context_blocks)
    else:
        response_text = (
            "I do not have enough grounded evidence to draft a safe customer-facing response yet. "
            "Please narrow the source filters, ask a more specific support question, or ingest more relevant documentation first."
        )

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

    draft = models.TicketDraft(
        customer_message=payload.customer_message,
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
    )
