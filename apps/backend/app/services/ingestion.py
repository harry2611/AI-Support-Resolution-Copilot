from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app import models
from app.schemas import DocumentInput
from app.services.guardrails import GuardrailService
from app.services.llm import LLMService
from sqlalchemy.orm import Session

settings = get_settings()


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []
    if len(clean) <= chunk_size:
        return [clean]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(clean)


def ingest_documents(db: Session, documents: list[DocumentInput], llm_service: LLMService) -> tuple[int, int]:
    ingested_docs = 0
    ingested_chunks = 0
    guardrails = GuardrailService()

    for payload in documents:
        sanitized_document = guardrails.sanitize_document_text(payload.content)
        sanitized_content = sanitized_document.sanitized_text

        doc = models.Document(
            title=payload.title,
            source=payload.source,
            content=sanitized_content,
            tags=payload.tags,
        )
        db.add(doc)
        db.flush()

        chunks = chunk_text(
            sanitized_content,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
        embeddings = llm_service.embed_texts(chunks)

        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            db.add(
                models.DocumentChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    content=chunk,
                    embedding=embedding,
                    metadata_json={"source": payload.source, "title": payload.title},
                )
            )

        ingested_docs += 1
        ingested_chunks += len(chunks)

    db.commit()
    return ingested_docs, ingested_chunks
