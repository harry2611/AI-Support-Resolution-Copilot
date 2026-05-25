from __future__ import annotations

import re
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


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "tell",
    "the",
    "to",
    "what",
    "why",
    "with",
}


class RetrievalService:
    def __init__(self, db: Session, llm_service: LLMService) -> None:
        self.db = db
        self.llm_service = llm_service

    def retrieve(self, query: str, top_k: int = 6, source_filters: list[str] | None = None) -> list[RetrievedChunk]:
        cleaned_query = self._normalize_whitespace(query)
        lexical_query = self._prepare_lexical_query(cleaned_query)
        semantic_candidates = self._semantic_search(cleaned_query, limit=top_k * 4, source_filters=source_filters or [])
        lexical_candidates = self._lexical_search(lexical_query, limit=top_k * 4, source_filters=source_filters or [])
        fused = self._reciprocal_rank_fusion(semantic_candidates, lexical_candidates, top_k=top_k * 2)
        return self._rerank_candidates(cleaned_query, fused, top_k=top_k)

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
        focus = chunks[: min(3, len(chunks))]
        avg_score = sum(chunk.score for chunk in focus) / len(focus)
        return round(min(0.99, avg_score), 3)

    def _semantic_search(self, query: str, limit: int, source_filters: list[str]) -> list[RetrievedChunk]:
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
        )
        if source_filters:
            stmt = stmt.where(models.Document.source.in_(source_filters))
        stmt = stmt.order_by(distance).limit(limit)
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

    def _lexical_search(self, query: str, limit: int, source_filters: list[str]) -> list[RetrievedChunk]:
        if not query.strip():
            return []

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
              AND (:apply_source_filters = false OR d.source = ANY(:source_filters))
            ORDER BY rank DESC
            LIMIT :limit
            """
        )
        rows = self.db.execute(
            lexical_sql,
            {
                "query": query,
                "limit": limit,
                "apply_source_filters": bool(source_filters),
                "source_filters": source_filters,
            },
        ).mappings().all()

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
        if not ranked:
            return []

        max_fused_score = ranked[0][1]
        merged: list[RetrievedChunk] = []

        for chunk_id, fused_score in ranked:
            item = chunk_map[chunk_id]
            merged.append(
                RetrievedChunk(
                    chunk_id=item.chunk_id,
                    title=item.title,
                    source=item.source,
                    content=item.content,
                    score=round(float(fused_score / max_fused_score), 4),
                )
            )

        return merged

    def _rerank_candidates(self, query: str, candidates: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        query_terms = self._significant_terms(query)
        query_phrase = self._normalize_whitespace(query.lower())
        if not candidates:
            return []

        reranked: list[RetrievedChunk] = []
        for candidate in candidates:
            title_terms = self._significant_terms(candidate.title)
            source_terms = self._significant_terms(candidate.source)
            content_terms = self._significant_terms(candidate.content)

            title_overlap = self._overlap_ratio(query_terms, title_terms)
            source_overlap = self._overlap_ratio(query_terms, source_terms)
            content_overlap = self._overlap_ratio(query_terms, content_terms)

            normalized_title = self._normalize_whitespace(candidate.title.lower())
            normalized_content = self._normalize_whitespace(candidate.content.lower())
            exact_phrase_boost = 0.0
            if query_phrase and query_phrase in normalized_title:
                exact_phrase_boost += 0.2
            elif query_phrase and query_phrase in normalized_content:
                exact_phrase_boost += 0.1

            final_score = min(
                0.99,
                (candidate.score * 0.4)
                + (title_overlap * 0.28)
                + (source_overlap * 0.08)
                + (content_overlap * 0.24)
                + exact_phrase_boost,
            )

            reranked.append(
                RetrievedChunk(
                    chunk_id=candidate.chunk_id,
                    title=candidate.title,
                    source=candidate.source,
                    content=candidate.content,
                    score=round(final_score, 4),
                )
            )

        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked[:top_k]

    def _significant_terms(self, value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.lower())
            if len(token) > 2 and token not in STOPWORDS
        }

    def _overlap_ratio(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left)

    def _prepare_lexical_query(self, value: str) -> str:
        terms = [token for token in re.findall(r"[a-z0-9]+", value.lower()) if token not in STOPWORDS]
        return " ".join(terms) if terms else value

    def _normalize_whitespace(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()
