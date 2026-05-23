from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.schemas import Citation, TicketDraftRequest, TicketDraftResponse
from app.services.llm import LLMService
from app.services.retrieval import RetrievalService

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("/draft", response_model=TicketDraftResponse)
def draft_ticket_reply(payload: TicketDraftRequest, db: Session = Depends(get_db)) -> TicketDraftResponse:
    llm_service = LLMService()
    retrieval = RetrievalService(db, llm_service)

    chunks = retrieval.retrieve(payload.customer_message, top_k=payload.top_k)
    context_blocks = retrieval.format_context_blocks(chunks)
    response_text = llm_service.generate_ticket_draft(payload.customer_message, context_blocks)

    citations = [
        Citation(
            chunk_id=str(chunk.chunk_id),
            title=chunk.title,
            source=chunk.source,
            snippet=chunk.content[:220],
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
    )
