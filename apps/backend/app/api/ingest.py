from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.schemas import DocumentInput, IngestRequest, IngestResponse
from app.services.ingestion import ingest_documents
from app.services.llm import LLMService

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/documents", response_model=IngestResponse)
def ingest_documents_endpoint(payload: IngestRequest, db: Session = Depends(get_db)) -> IngestResponse:
    if not payload.documents:
        raise HTTPException(status_code=400, detail="No documents provided for ingestion")

    llm_service = LLMService()
    ingested_documents, ingested_chunks = ingest_documents(db, payload.documents, llm_service)
    return IngestResponse(ingested_documents=ingested_documents, ingested_chunks=ingested_chunks)


@router.get("/documents", response_model=list[DocumentInput])
def list_documents(db: Session = Depends(get_db)) -> list[DocumentInput]:
    rows = db.execute(select(models.Document).order_by(models.Document.created_at.desc()).limit(100)).scalars().all()
    return [
        DocumentInput(title=row.title, source=row.source, content=row.content, tags=row.tags)
        for row in rows
    ]
