from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.schemas import MetricsResponse

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
def get_metrics(db: Session = Depends(get_db)) -> MetricsResponse:
    total_queries = db.scalar(select(func.count()).select_from(models.QueryLog)) or 0
    avg_latency = db.scalar(select(func.avg(models.QueryLog.latency_ms))) or 0.0
    avg_confidence = db.scalar(select(func.avg(models.QueryLog.confidence))) or 0.0
    drafts_pending_review = (
        db.scalar(
            select(func.count())
            .select_from(models.TicketDraft)
            .where(models.TicketDraft.status == "pending_review")
        )
        or 0
    )
    documents_indexed = db.scalar(select(func.count()).select_from(models.Document)) or 0
    avg_feedback_rating = db.scalar(select(func.avg(models.Feedback.rating)))

    return MetricsResponse(
        total_queries=int(total_queries),
        avg_latency_ms=round(float(avg_latency), 2),
        avg_confidence=round(float(avg_confidence), 3),
        drafts_pending_review=int(drafts_pending_review),
        documents_indexed=int(documents_indexed),
        avg_feedback_rating=round(float(avg_feedback_rating), 2) if avg_feedback_rating is not None else None,
    )
