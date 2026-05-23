from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    Citation,
    EvalBenchmarkCaseResponse,
    EvalBenchmarkCreateRequest,
    EvalBenchmarkCreateResponse,
    EvalCaseResultResponse,
    EvalRunDetailResponse,
    EvalRunRequest,
    EvalSummaryResponse,
)
from app.services.evals import EvalService
from app.services.llm import LLMService

router = APIRouter(prefix="/evals", tags=["evals"])


@router.post("/cases", response_model=EvalBenchmarkCreateResponse)
def create_eval_cases(payload: EvalBenchmarkCreateRequest, db: Session = Depends(get_db)) -> EvalBenchmarkCreateResponse:
    if not payload.cases:
        raise HTTPException(status_code=400, detail="No evaluation cases provided")

    service = EvalService(db, LLMService())
    created = service.create_cases([case.model_dump() for case in payload.cases])
    return EvalBenchmarkCreateResponse(created_cases=created)


@router.get("/cases", response_model=list[EvalBenchmarkCaseResponse])
def list_eval_cases(db: Session = Depends(get_db)) -> list[EvalBenchmarkCaseResponse]:
    service = EvalService(db, LLMService())
    cases = service.list_cases()
    return [
        EvalBenchmarkCaseResponse(
            case_id=str(case.id),
            name=case.name,
            question=case.question,
            expected_titles=case.expected_titles,
            expected_sources=case.expected_sources,
            expected_keywords=case.expected_keywords,
            expected_answer_points=case.expected_answer_points,
            tags=case.tags,
            created_at=case.created_at,
        )
        for case in cases
    ]


@router.post("/run", response_model=EvalSummaryResponse)
def run_eval(payload: EvalRunRequest, db: Session = Depends(get_db)) -> EvalSummaryResponse:
    service = EvalService(db, LLMService())
    try:
        run = service.run_benchmark(payload.label, payload.top_k, payload.case_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to run evaluation: {exc}") from exc

    return EvalSummaryResponse(
        run_id=str(run.id),
        label=run.label,
        status=run.status,
        top_k=run.top_k,
        total_cases=run.total_cases,
        retrieval_hit_rate=run.retrieval_hit_rate,
        avg_precision_at_k=run.avg_precision_at_k,
        avg_recall_at_k=run.avg_recall_at_k,
        avg_answer_coverage=run.avg_answer_coverage,
        avg_grounding_score=run.avg_grounding_score,
        avg_hallucination_risk=run.avg_hallucination_risk,
        avg_latency_ms=run.avg_latency_ms,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


@router.get("/runs", response_model=list[EvalSummaryResponse])
def list_eval_runs(limit: int = 10, db: Session = Depends(get_db)) -> list[EvalSummaryResponse]:
    service = EvalService(db, LLMService())
    runs = service.list_runs(limit=limit)
    return [
        EvalSummaryResponse(
            run_id=str(run.id),
            label=run.label,
            status=run.status,
            top_k=run.top_k,
            total_cases=run.total_cases,
            retrieval_hit_rate=run.retrieval_hit_rate,
            avg_precision_at_k=run.avg_precision_at_k,
            avg_recall_at_k=run.avg_recall_at_k,
            avg_answer_coverage=run.avg_answer_coverage,
            avg_grounding_score=run.avg_grounding_score,
            avg_hallucination_risk=run.avg_hallucination_risk,
            avg_latency_ms=run.avg_latency_ms,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
        for run in runs
    ]


@router.get("/runs/{run_id}", response_model=EvalRunDetailResponse)
def get_eval_run(run_id: str, db: Session = Depends(get_db)) -> EvalRunDetailResponse:
    service = EvalService(db, LLMService())
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")

    results = service.list_run_results(run_id)
    return EvalRunDetailResponse(
        run_id=str(run.id),
        label=run.label,
        status=run.status,
        top_k=run.top_k,
        total_cases=run.total_cases,
        retrieval_hit_rate=run.retrieval_hit_rate,
        avg_precision_at_k=run.avg_precision_at_k,
        avg_recall_at_k=run.avg_recall_at_k,
        avg_answer_coverage=run.avg_answer_coverage,
        avg_grounding_score=run.avg_grounding_score,
        avg_hallucination_risk=run.avg_hallucination_risk,
        avg_latency_ms=run.avg_latency_ms,
        started_at=run.started_at,
        finished_at=run.finished_at,
        results=[
            EvalCaseResultResponse(
                result_id=str(result.id),
                benchmark_case_id=str(case.id),
                case_name=case.name,
                question=result.question,
                generated_answer=result.generated_answer,
                retrieval_hit=result.retrieval_hit,
                precision_at_k=result.precision_at_k,
                recall_at_k=result.recall_at_k,
                answer_coverage=result.answer_coverage,
                grounding_score=result.grounding_score,
                hallucination_risk=result.hallucination_risk,
                confidence=result.confidence,
                latency_ms=result.latency_ms,
                matched_titles=result.matched_titles,
                matched_sources=result.matched_sources,
                citations=[
                    Citation(
                        chunk_id=item["chunk_id"],
                        title=item["title"],
                        source=item["source"],
                        snippet=item["snippet"],
                        score=item["score"],
                    )
                    for item in result.citations_json
                ],
                notes=result.notes,
            )
            for result, case in results
        ],
    )
