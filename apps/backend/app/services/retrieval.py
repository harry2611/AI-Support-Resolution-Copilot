from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import models
from app.services.llm import LLMService


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    title: str
    source: str
    content: str
    score: float


class RetrievalService:
    def __init__(self, db: Session, llm_service: LLMService) -> None:
        self.db = db
        self.llm_service = llm_service

    def retrieve(self, query: str, top_k: int = 6) -> list[RetrievedChunk]:
        semantic_candidates = self._semantic_search(query, limit=top_k * 3)
        lexical_candidates = self._lexical_search(query, limit=top_k * 3)
        return self._reciprocal_rank_fusion(semantic_candidates, lexical_candidates, top_k=top_k)

    def format_context_blocks(self, chunks: list[RetrievedChunk]) -> list[str]:
        context: list[str] = []
        for chunk in chunks:
            context.append(
                f"[{chunk.title} | {chunk.source} | chunk:{chunk.chunk_id}]\n{chunk.content}"
            )
        return context

    def confidence_score(self, chunks: list[RetrievedChunk]) -> float:
        if not chunks:
            return 0.0
        avg_score = sum(chunk.score for chunk in chunks) / len(chunks)
        return round(min(0.99, avg_score * 12), 3)

    def _semantic_search(self, query: str, limit: int) -> list[RetrievedChunk]:
        query_embedding = self.llm_service.embed_texts([query])[0]
        distance = models.DocumentChunk.embedding.cosine_distance(query_embedding)
        stmt = (
            select(
                models.DocumentChunk.id,
                models.DocumentChunk.content,
                models.Document.title,
                models.Document.source,
                distance.label("distance"),
            )
            .join(models.Document, models.Document.id == models.DocumentChunk.document_id)
            .order_by(distance)
            .limit(limit)
        )
        rows = self.db.execute(stmt).all()

        results: list[RetrievedChunk] = []
        for row in rows:
            score = max(0.0, 1.0 - float(row.distance))
            results.append(
                RetrievedChunk(
                    chunk_id=row.id,
                    title=row.title,
                    source=row.source,
                    content=row.content,
                    score=score,
                )
            )
        return results

    def _lexical_search(self, query: str, limit: int) -> list[RetrievedChunk]:
        lexical_sql = text(
            """
            SELECT
                c.id AS chunk_id,
                c.content AS content,
                d.title AS title,
                d.source AS source,
                ts_rank_cd(c.search_vector, websearch_to_tsquery('english', :query)) AS rank
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.search_vector @@ websearch_to_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT :limit
            """
        )
        rows = self.db.execute(lexical_sql, {"query": query, "limit": limit}).mappings().all()

        results: list[RetrievedChunk] = []
        for row in rows:
            results.append(
                RetrievedChunk(
                    chunk_id=row["chunk_id"],
                    title=row["title"],
                    source=row["source"],
                    content=row["content"],
                    score=float(row["rank"]),
                )
            )
        return results

    def _reciprocal_rank_fusion(
        self,
        semantic_candidates: list[RetrievedChunk],
        lexical_candidates: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        fused_scores: dict[uuid.UUID, float] = {}
        chunk_map: dict[uuid.UUID, RetrievedChunk] = {}

        for rank, item in enumerate(semantic_candidates, start=1):
            fused_scores[item.chunk_id] = fused_scores.get(item.chunk_id, 0.0) + 1.0 / (50 + rank)
            chunk_map[item.chunk_id] = item

        for rank, item in enumerate(lexical_candidates, start=1):
            fused_scores[item.chunk_id] = fused_scores.get(item.chunk_id, 0.0) + 1.0 / (50 + rank)
            if item.chunk_id not in chunk_map:
                chunk_map[item.chunk_id] = item

        ranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        merged: list[RetrievedChunk] = []

        for chunk_id, fused_score in ranked:
            item = chunk_map[chunk_id]
            merged.append(
                RetrievedChunk(
                    chunk_id=item.chunk_id,
                    title=item.title,
                    source=item.source,
                    content=item.content,
                    score=round(float(fused_score), 4),
                )
            )

        return merged
