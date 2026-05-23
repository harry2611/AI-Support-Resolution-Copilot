from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, evals, feedback, ingest, metrics, sync, tickets
from app.config import get_settings
from app.database import init_db
from app.services.sync import sync_manager

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(tickets.router, prefix=settings.api_prefix)
app.include_router(metrics.router, prefix=settings.api_prefix)
app.include_router(feedback.router, prefix=settings.api_prefix)
app.include_router(sync.router, prefix=settings.api_prefix)
app.include_router(evals.router, prefix=settings.api_prefix)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    sync_manager.start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    sync_manager.shutdown_scheduler()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
