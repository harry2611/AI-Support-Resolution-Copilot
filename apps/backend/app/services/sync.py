from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.services.connectors import BaseConnector, ConfluenceConnector, ExternalDocument, NotionConnector
from app.services.ingestion import chunk_text
from app.services.llm import LLMService

logger = logging.getLogger(__name__)
settings = get_settings()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SyncCounters:
    fetched: int = 0
    ingested: int = 0
    skipped: int = 0
    chunks: int = 0


class SyncManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scheduler = BackgroundScheduler(timezone="UTC")

    def start_scheduler(self) -> None:
        if not settings.sync_scheduler_enabled:
            logger.info("Sync scheduler disabled by configuration")
            return

        if not self._scheduler.running:
            self._scheduler.add_job(
                self.run_all_connectors_sync,
                trigger=IntervalTrigger(minutes=settings.sync_interval_minutes),
                id="external_connector_sync",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            self._scheduler.start()
            logger.info("Sync scheduler started. Interval: %s minute(s)", settings.sync_interval_minutes)

        if settings.sync_on_startup:
            try:
                self.run_all_connectors_sync()
            except Exception as exc:  # pragma: no cover - startup safety log
                logger.warning("Startup sync failed: %s", exc)

    def shutdown_scheduler(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Sync scheduler stopped")

    def scheduler_status(self) -> dict:
        last_run = None
        with SessionLocal() as db:
            last_run = db.execute(select(models.SyncRun).order_by(models.SyncRun.started_at.desc()).limit(1)).scalar_one_or_none()

        return {
            "scheduler_enabled": settings.sync_scheduler_enabled,
            "scheduler_running": self._scheduler.running,
            "interval_minutes": settings.sync_interval_minutes,
            "connectors_enabled": self.enabled_connectors(),
            "last_run_started_at": last_run.started_at if last_run else None,
        }

    def list_runs(self, limit: int = 20) -> list[models.SyncRun]:
        safe_limit = max(1, min(limit, 100))
        with SessionLocal() as db:
            return (
                db.execute(select(models.SyncRun).order_by(models.SyncRun.started_at.desc()).limit(safe_limit))
                .scalars()
                .all()
            )

    def run_all_connectors_sync(self) -> list[models.SyncRun]:
        return self.run_sync("all")

    def run_sync(self, connector_name: str = "all") -> list[models.SyncRun]:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("A sync job is already running")
        try:
            connectors = self._select_connectors(connector_name)
            if not connectors:
                raise RuntimeError("No enabled connectors configured")
            run_ids: list = []
            with SessionLocal() as db:
                for connector in connectors:
                    run = self._run_single_connector_sync(db, connector)
                    run_ids.append(run.id)

            with SessionLocal() as db:
                rows = (
                    db.execute(
                        select(models.SyncRun)
                        .where(models.SyncRun.id.in_(run_ids))
                        .order_by(models.SyncRun.started_at.asc())
                    )
                    .scalars()
                    .all()
                )
                return rows
        finally:
            self._lock.release()

    def enabled_connectors(self) -> list[str]:
        enabled = []
        for connector in self._connector_instances():
            if connector.is_enabled():
                enabled.append(connector.name)
        return enabled

    def _select_connectors(self, connector_name: str) -> list[BaseConnector]:
        normalized = connector_name.strip().lower()
        all_connectors = self._connector_instances()
        enabled = [connector for connector in all_connectors if connector.is_enabled()]
        if normalized in {"", "all"}:
            return enabled
        return [connector for connector in enabled if connector.name == normalized]

    def _connector_instances(self) -> list[BaseConnector]:
        return [ConfluenceConnector(settings), NotionConnector(settings)]

    def _run_single_connector_sync(self, db, connector: BaseConnector) -> models.SyncRun:
        run = models.SyncRun(
            connector=connector.name,
            status="running",
            total_fetched=0,
            total_ingested=0,
            total_skipped=0,
            total_chunks=0,
            started_at=_utc_now(),
            metadata_json={},
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        try:
            external_docs = connector.fetch_documents()
            counters = self._sync_documents(db, connector.name, external_docs)
            run.status = "success"
            run.total_fetched = counters.fetched
            run.total_ingested = counters.ingested
            run.total_skipped = counters.skipped
            run.total_chunks = counters.chunks
            run.metadata_json = {"connector": connector.name}
            run.finished_at = _utc_now()
            db.commit()
            db.refresh(run)
            return run
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:1000]
            run.finished_at = _utc_now()
            db.commit()
            db.refresh(run)
            logger.exception("Connector sync failed: %s", connector.name)
            return run

    def _sync_documents(self, db, connector_name: str, external_docs: list[ExternalDocument]) -> SyncCounters:
        counters = SyncCounters(fetched=len(external_docs))
        llm_service = LLMService()

        for external_doc in external_docs:
            normalized_content = " ".join(external_doc.content.split()).strip()
            if not normalized_content:
                counters.skipped += 1
                continue

            content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
            state = db.execute(
                select(models.SourceDocumentState).where(
                    models.SourceDocumentState.connector == connector_name,
                    models.SourceDocumentState.external_id == external_doc.external_id,
                )
            ).scalar_one_or_none()

            unchanged = state is not None and state.content_hash == content_hash
            if unchanged:
                state.last_synced_at = _utc_now()
                if external_doc.updated_at:
                    state.external_updated_at = external_doc.updated_at
                counters.skipped += 1
                continue

            chunks = chunk_text(
                normalized_content,
                chunk_size=settings.chunk_size,
                overlap=settings.chunk_overlap,
            )
            if not chunks:
                counters.skipped += 1
                continue

            embeddings = llm_service.embed_texts(chunks)
            version = (state.current_version + 1) if state else 1
            source_value = external_doc.source_url[:255] if external_doc.source_url else f"{connector_name}:external"

            tags = list(dict.fromkeys([*external_doc.tags, connector_name, f"{connector_name}:v{version}"]))
            document = models.Document(
                title=external_doc.title[:255],
                source=source_value,
                content=normalized_content,
                tags=tags,
            )
            db.add(document)
            db.flush()

            for chunk_index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
                db.add(
                    models.DocumentChunk(
                        document_id=document.id,
                        chunk_index=chunk_index,
                        content=chunk,
                        embedding=embedding,
                        metadata_json={
                            "connector": connector_name,
                            "external_id": external_doc.external_id,
                            "source_url": external_doc.source_url,
                            "version": version,
                            **external_doc.metadata,
                        },
                    )
                )

            if not state:
                state = models.SourceDocumentState(
                    connector=connector_name,
                    external_id=external_doc.external_id,
                    source_url=external_doc.source_url[:1024],
                    title=external_doc.title[:255],
                    content_hash=content_hash,
                    current_version=version,
                    latest_document_id=document.id,
                    external_updated_at=external_doc.updated_at,
                    last_synced_at=_utc_now(),
                )
                db.add(state)
            else:
                state.source_url = external_doc.source_url[:1024]
                state.title = external_doc.title[:255]
                state.content_hash = content_hash
                state.current_version = version
                state.latest_document_id = document.id
                state.external_updated_at = external_doc.updated_at
                state.last_synced_at = _utc_now()

            counters.ingested += 1
            counters.chunks += len(chunks)

        db.commit()
        return counters


sync_manager = SyncManager()
