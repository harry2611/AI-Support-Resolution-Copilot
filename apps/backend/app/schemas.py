from datetime import datetime

from pydantic import BaseModel, Field


class DocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class IngestRequest(BaseModel):
    documents: list[DocumentInput] = Field(default_factory=list)


class IngestResponse(BaseModel):
    ingested_documents: int
    ingested_chunks: int


class DocumentSummary(BaseModel):
    title: str
    source: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime


class Citation(BaseModel):
    chunk_id: str
    title: str
    source: str
    snippet: str
    score: float


class ChatRequest(BaseModel):
    question: str = Field(min_length=3)
    top_k: int = Field(default=6, ge=1, le=12)
    source_filters: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: float
    latency_ms: int
    query_log_id: str
    grounded: bool
    applied_source_filters: list[str] = Field(default_factory=list)
    guardrail_events: list[str] = Field(default_factory=list)


class TicketDraftRequest(BaseModel):
    customer_message: str = Field(min_length=3)
    top_k: int = Field(default=6, ge=1, le=12)
    source_filters: list[str] = Field(default_factory=list)


class TicketDraftResponse(BaseModel):
    draft_id: str
    response: str
    citations: list[Citation]
    grounded: bool
    applied_source_filters: list[str] = Field(default_factory=list)
    guardrail_events: list[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    query_log_id: str
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


class MetricsResponse(BaseModel):
    total_queries: int
    avg_latency_ms: float
    avg_confidence: float
    drafts_pending_review: int
    documents_indexed: int
    avg_feedback_rating: float | None


class SyncRunRequest(BaseModel):
    connector: str = Field(default="all")


class SyncRunResponse(BaseModel):
    run_id: str
    connector: str
    status: str
    total_fetched: int
    total_ingested: int
    total_skipped: int
    total_chunks: int
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None = None


class SyncStatusResponse(BaseModel):
    scheduler_enabled: bool
    scheduler_running: bool
    interval_minutes: int
    connectors_enabled: list[str]
    last_run_started_at: datetime | None


class EvalBenchmarkCaseInput(BaseModel):
    name: str = Field(min_length=3, max_length=255)
    question: str = Field(min_length=5)
    expected_titles: list[str] = Field(default_factory=list)
    expected_sources: list[str] = Field(default_factory=list)
    expected_keywords: list[str] = Field(default_factory=list)
    expected_answer_points: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class EvalBenchmarkCaseResponse(EvalBenchmarkCaseInput):
    case_id: str
    created_at: datetime


class EvalBenchmarkCreateRequest(BaseModel):
    cases: list[EvalBenchmarkCaseInput] = Field(default_factory=list)


class EvalBenchmarkCreateResponse(BaseModel):
    created_cases: int


class EvalRunRequest(BaseModel):
    label: str = Field(default="manual-eval", min_length=3, max_length=255)
    top_k: int = Field(default=6, ge=1, le=12)
    case_ids: list[str] = Field(default_factory=list)


class RagasStyleMetrics(BaseModel):
    answer_relevance: float
    faithfulness: float
    context_precision: float
    context_recall: float


class EvalSummaryResponse(BaseModel):
    run_id: str
    label: str
    status: str
    top_k: int
    total_cases: int
    retrieval_hit_rate: float
    avg_precision_at_k: float
    avg_recall_at_k: float
    avg_answer_coverage: float
    avg_grounding_score: float
    avg_hallucination_risk: float
    avg_latency_ms: float
    started_at: datetime
    finished_at: datetime | None
    ragas_style_metrics: RagasStyleMetrics | None = None
    langsmith_tracing_enabled: bool = False
    langsmith_project: str | None = None


class EvalCaseResultResponse(BaseModel):
    result_id: str
    benchmark_case_id: str
    case_name: str
    question: str
    generated_answer: str
    retrieval_hit: bool
    precision_at_k: float
    recall_at_k: float
    answer_coverage: float
    grounding_score: float
    hallucination_risk: float
    confidence: float
    latency_ms: int
    matched_titles: list[str]
    matched_sources: list[str]
    citations: list[Citation]
    notes: str | None
    ragas_style_metrics: RagasStyleMetrics | None = None


class EvalRunDetailResponse(EvalSummaryResponse):
    results: list[EvalCaseResultResponse]
