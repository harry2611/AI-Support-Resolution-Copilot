from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.services.llm import LLMService
from app.services.retrieval import RetrievalService


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
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
    "your",
}


@dataclass
class EvalAggregate:
    retrieval_hit_rate: float
    avg_precision_at_k: float
    avg_recall_at_k: float
    avg_answer_coverage: float
    avg_grounding_score: float
    avg_hallucination_risk: float
    avg_latency_ms: float


class EvalService:
    def __init__(self, db: Session, llm_service: LLMService) -> None:
        self.db = db
        self.llm_service = llm_service
        self.retrieval = RetrievalService(db, llm_service)

    def create_cases(self, cases: list[dict]) -> int:
        for payload in cases:
            self.db.add(
                models.EvalBenchmarkCase(
                    name=payload["name"],
                    question=payload["question"],
                    expected_titles=payload.get("expected_titles", []),
                    expected_sources=payload.get("expected_sources", []),
                    expected_keywords=payload.get("expected_keywords", []),
                    expected_answer_points=payload.get("expected_answer_points", []),
                    tags=payload.get("tags", []),
                )
            )

        self.db.commit()
        return len(cases)

    def list_cases(self) -> list[models.EvalBenchmarkCase]:
        stmt = select(models.EvalBenchmarkCase).order_by(models.EvalBenchmarkCase.created_at.desc())
        return self.db.execute(stmt).scalars().all()

    def run_benchmark(self, label: str, top_k: int, case_ids: list[str] | None = None) -> models.EvalRun:
        cases = self._load_cases(case_ids or [])
        if not cases:
            raise ValueError("No evaluation benchmark cases found")

        run = models.EvalRun(
            label=label,
            status="running",
            top_k=top_k,
            total_cases=len(cases),
            metadata_json={"case_ids": [str(case.id) for case in cases]},
        )
        self.db.add(run)
        self.db.flush()

        run_results: list[models.EvalCaseResult] = []
        for case in cases:
            result = self._evaluate_case(case, run.id, top_k)
            self.db.add(result)
            run_results.append(result)

        self.db.flush()
        aggregate = self._aggregate_results(run_results)
        run.status = "completed"
        run.retrieval_hit_rate = aggregate.retrieval_hit_rate
        run.avg_precision_at_k = aggregate.avg_precision_at_k
        run.avg_recall_at_k = aggregate.avg_recall_at_k
        run.avg_answer_coverage = aggregate.avg_answer_coverage
        run.avg_grounding_score = aggregate.avg_grounding_score
        run.avg_hallucination_risk = aggregate.avg_hallucination_risk
        run.avg_latency_ms = aggregate.avg_latency_ms
        run.finished_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(run)
        return run

    def list_runs(self, limit: int = 10) -> list[models.EvalRun]:
        stmt = select(models.EvalRun).order_by(models.EvalRun.started_at.desc()).limit(limit)
        return self.db.execute(stmt).scalars().all()

    def get_run(self, run_id: str) -> models.EvalRun | None:
        try:
            parsed = uuid.UUID(run_id)
        except ValueError:
            return None

        return self.db.get(models.EvalRun, parsed)

    def list_run_results(self, run_id: str) -> list[tuple[models.EvalCaseResult, models.EvalBenchmarkCase]]:
        stmt = (
            select(models.EvalCaseResult, models.EvalBenchmarkCase)
            .join(models.EvalBenchmarkCase, models.EvalBenchmarkCase.id == models.EvalCaseResult.benchmark_case_id)
            .where(models.EvalCaseResult.eval_run_id == uuid.UUID(run_id))
            .order_by(models.EvalCaseResult.created_at.asc())
        )
        return list(self.db.execute(stmt).all())

    def _load_cases(self, case_ids: list[str]) -> list[models.EvalBenchmarkCase]:
        if case_ids:
            parsed_ids = [uuid.UUID(case_id) for case_id in case_ids]
            stmt = (
                select(models.EvalBenchmarkCase)
                .where(models.EvalBenchmarkCase.id.in_(parsed_ids))
                .order_by(models.EvalBenchmarkCase.created_at.asc())
            )
        else:
            stmt = select(models.EvalBenchmarkCase).order_by(models.EvalBenchmarkCase.created_at.asc())
        return self.db.execute(stmt).scalars().all()

    def _evaluate_case(
        self,
        case: models.EvalBenchmarkCase,
        run_id: uuid.UUID,
        top_k: int,
    ) -> models.EvalCaseResult:
        started = time.perf_counter()
        chunks = self.retrieval.retrieve(case.question, top_k=top_k)
        confidence = self.retrieval.confidence_score(chunks)
        context_blocks = self.retrieval.format_context_blocks(chunks)
        answer = self.llm_service.generate_answer(case.question, context_blocks)
        latency_ms = int((time.perf_counter() - started) * 1000)

        matched_titles, matched_sources, relevant_chunk_count = self._match_retrieved_chunks(case, chunks)
        retrieval_hit = relevant_chunk_count > 0
        precision_at_k = round(relevant_chunk_count / max(len(chunks), 1), 3)
        recall_at_k = self._recall_score(case, matched_titles, matched_sources, context_blocks)
        answer_coverage = self._coverage_score(answer, case.expected_answer_points or case.expected_keywords)
        grounding_score = self._grounding_score(answer, context_blocks)
        hallucination_risk = round(max(0.0, 1.0 - grounding_score), 3)

        notes = None
        if not (case.expected_titles or case.expected_sources or case.expected_keywords or case.expected_answer_points):
            notes = "No expected references or answer points defined for this benchmark case."

        citations_json = [
            {
                "chunk_id": str(chunk.chunk_id),
                "title": chunk.title,
                "source": chunk.source,
                "snippet": chunk.content[:220],
                "score": chunk.score,
            }
            for chunk in chunks
        ]

        return models.EvalCaseResult(
            eval_run_id=run_id,
            benchmark_case_id=case.id,
            question=case.question,
            generated_answer=answer,
            retrieval_hit=retrieval_hit,
            precision_at_k=precision_at_k,
            recall_at_k=recall_at_k,
            answer_coverage=answer_coverage,
            grounding_score=grounding_score,
            hallucination_risk=hallucination_risk,
            confidence=confidence,
            latency_ms=latency_ms,
            matched_titles=matched_titles,
            matched_sources=matched_sources,
            citations_json=citations_json,
            notes=notes,
        )

    def _match_retrieved_chunks(
        self,
        case: models.EvalBenchmarkCase,
        chunks: list,
    ) -> tuple[list[str], list[str], int]:
        expected_titles = {self._normalize(value) for value in case.expected_titles if value.strip()}
        expected_sources = {self._normalize(value) for value in case.expected_sources if value.strip()}
        expected_keywords = {self._normalize(value) for value in case.expected_keywords if value.strip()}

        matched_titles: set[str] = set()
        matched_sources: set[str] = set()
        relevant_chunk_count = 0

        for chunk in chunks:
            title_norm = self._normalize(chunk.title)
            source_norm = self._normalize(chunk.source)
            content_norm = self._normalize(chunk.content)

            title_match = any(expected in title_norm for expected in expected_titles) if expected_titles else False
            source_match = any(expected in source_norm for expected in expected_sources) if expected_sources else False
            keyword_match = any(keyword in content_norm for keyword in expected_keywords) if expected_keywords else False

            if title_match or source_match or keyword_match:
                relevant_chunk_count += 1
                if title_match:
                    matched_titles.add(chunk.title)
                if source_match:
                    matched_sources.add(chunk.source)

        return sorted(matched_titles), sorted(matched_sources), relevant_chunk_count

    def _recall_score(
        self,
        case: models.EvalBenchmarkCase,
        matched_titles: list[str],
        matched_sources: list[str],
        context_blocks: list[str],
    ) -> float:
        expected_reference_count = len(case.expected_titles) + len(case.expected_sources)
        if expected_reference_count > 0:
            matched_reference_count = len(matched_titles) + len(matched_sources)
            return round(min(1.0, matched_reference_count / expected_reference_count), 3)

        if case.expected_keywords:
            context_text = self._normalize(" ".join(context_blocks))
            matched_keywords = sum(1 for keyword in case.expected_keywords if self._normalize(keyword) in context_text)
            return round(matched_keywords / max(len(case.expected_keywords), 1), 3)

        return 1.0 if context_blocks else 0.0

    def _coverage_score(self, answer: str, expected_points: list[str]) -> float:
        if not expected_points:
            return 0.0

        answer_norm = self._normalize(answer)
        matched = sum(1 for point in expected_points if self._normalize(point) in answer_norm)
        return round(matched / len(expected_points), 3)

    def _grounding_score(self, answer: str, context_blocks: list[str]) -> float:
        answer_tokens = self._significant_tokens(answer)
        if not answer_tokens:
            return 0.0

        context_tokens = self._significant_tokens(" ".join(context_blocks))
        if not context_tokens:
            return 0.0

        supported = len(answer_tokens & context_tokens)
        return round(supported / len(answer_tokens), 3)

    def _aggregate_results(self, results: list[models.EvalCaseResult]) -> EvalAggregate:
        if not results:
            return EvalAggregate(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        total = len(results)
        return EvalAggregate(
            retrieval_hit_rate=round(sum(1 for item in results if item.retrieval_hit) / total, 3),
            avg_precision_at_k=round(sum(item.precision_at_k for item in results) / total, 3),
            avg_recall_at_k=round(sum(item.recall_at_k for item in results) / total, 3),
            avg_answer_coverage=round(sum(item.answer_coverage for item in results) / total, 3),
            avg_grounding_score=round(sum(item.grounding_score for item in results) / total, 3),
            avg_hallucination_risk=round(sum(item.hallucination_risk for item in results) / total, 3),
            avg_latency_ms=round(sum(item.latency_ms for item in results) / total, 2),
        )

    def _normalize(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def _significant_tokens(self, value: str) -> set[str]:
        tokens = re.findall(r"[a-z0-9]+", value.lower())
        return {token for token in tokens if len(token) > 2 and token not in STOPWORDS}
