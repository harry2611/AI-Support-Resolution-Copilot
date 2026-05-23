from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import SyncRunRequest, SyncRunResponse, SyncStatusResponse
from app.services.sync import sync_manager

router = APIRouter(prefix="/sync", tags=["sync"])


def _to_response(run) -> SyncRunResponse:
    return SyncRunResponse(
        run_id=str(run.id),
        connector=run.connector,
        status=run.status,
        total_fetched=run.total_fetched,
        total_ingested=run.total_ingested,
        total_skipped=run.total_skipped,
        total_chunks=run.total_chunks,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_message=run.error_message,
    )


@router.post("/run", response_model=list[SyncRunResponse])
def run_sync(payload: SyncRunRequest) -> list[SyncRunResponse]:
    try:
        runs = sync_manager.run_sync(payload.connector)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return [_to_response(run) for run in runs]


@router.get("/runs", response_model=list[SyncRunResponse])
def list_sync_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[SyncRunResponse]:
    rows = sync_manager.list_runs(limit=limit)
    return [_to_response(run) for run in rows]


@router.get("/status", response_model=SyncStatusResponse)
def sync_status() -> SyncStatusResponse:
    status = sync_manager.scheduler_status()
    return SyncStatusResponse(**status)
