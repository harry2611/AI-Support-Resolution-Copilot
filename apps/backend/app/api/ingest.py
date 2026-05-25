from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.schemas import DocumentInput, DocumentSummary, IngestRequest, IngestResponse
from app.services.document_parser import parse_document_bytes
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


@router.get("/catalog", response_model=list[DocumentSummary])
def list_document_catalog(db: Session = Depends(get_db)) -> list[DocumentSummary]:
    rows = db.execute(select(models.Document).order_by(models.Document.created_at.desc()).limit(200)).scalars().all()
    return [
        DocumentSummary(
            title=row.title,
            source=row.source,
            tags=row.tags,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/upload", response_model=IngestResponse)
async def ingest_uploaded_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    source: str | None = Form(default=None),
    tags: str = Form(default=""),
    db: Session = Depends(get_db),
) -> IngestResponse:
    filename = file.filename or "uploaded-document"
    try:
        content = await file.read()
        parsed_text = parse_document_bytes(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse uploaded file: {exc}") from exc
    finally:
        await file.close()

    if not parsed_text.strip():
        raise HTTPException(status_code=400, detail="No extractable text found in uploaded document")

    derived_title = title.strip() if title and title.strip() else Path(filename).stem
    derived_source = source.strip() if source and source.strip() else f"Uploaded file - {filename}"
    parsed_tags = [value.strip() for value in tags.split(",") if value.strip()]

    payload = DocumentInput(
        title=derived_title,
        source=derived_source,
        content=parsed_text,
        tags=parsed_tags,
    )

    llm_service = LLMService()
    ingested_documents, ingested_chunks = ingest_documents(db, [payload], llm_service)
    return IngestResponse(ingested_documents=ingested_documents, ingested_chunks=ingested_chunks)
