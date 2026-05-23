export type Citation = {
  chunk_id: string;
  title: string;
  source: string;
  snippet: string;
  score: number;
};

export type ChatResponse = {
  answer: string;
  citations: Citation[];
  confidence: number;
  latency_ms: number;
  query_log_id: string;
};

export type TicketDraftResponse = {
  draft_id: string;
  response: string;
  citations: Citation[];
};

export type MetricsResponse = {
  total_queries: number;
  avg_latency_ms: number;
  avg_confidence: number;
  drafts_pending_review: number;
  documents_indexed: number;
  avg_feedback_rating: number | null;
};

export type SyncRun = {
  run_id: string;
  connector: string;
  status: string;
  total_fetched: number;
  total_ingested: number;
  total_skipped: number;
  total_chunks: number;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
};

export type SyncStatus = {
  scheduler_enabled: boolean;
  scheduler_running: boolean;
  interval_minutes: number;
  connectors_enabled: string[];
  last_run_started_at: string | null;
};

export type EvalBenchmarkCase = {
  case_id: string;
  name: string;
  question: string;
  expected_titles: string[];
  expected_sources: string[];
  expected_keywords: string[];
  expected_answer_points: string[];
  tags: string[];
  created_at: string;
};

export type EvalSummary = {
  run_id: string;
  label: string;
  status: string;
  top_k: number;
  total_cases: number;
  retrieval_hit_rate: number;
  avg_precision_at_k: number;
  avg_recall_at_k: number;
  avg_answer_coverage: number;
  avg_grounding_score: number;
  avg_hallucination_risk: number;
  avg_latency_ms: number;
  started_at: string;
  finished_at: string | null;
};

export type EvalCaseResult = {
  result_id: string;
  benchmark_case_id: string;
  case_name: string;
  question: string;
  generated_answer: string;
  retrieval_hit: boolean;
  precision_at_k: number;
  recall_at_k: number;
  answer_coverage: number;
  grounding_score: number;
  hallucination_risk: number;
  confidence: number;
  latency_ms: number;
  matched_titles: string[];
  matched_sources: string[];
  citations: Citation[];
  notes: string | null;
};

export type EvalRunDetail = EvalSummary & {
  results: EvalCaseResult[];
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function ingestDocument(payload: {
  title: string;
  source: string;
  tags: string[];
  content: string;
}) {
  return apiFetch<{ ingested_documents: number; ingested_chunks: number }>("/api/ingest/documents", {
    method: "POST",
    body: JSON.stringify({ documents: [payload] })
  });
}

export async function askQuestion(question: string, top_k = 6) {
  return apiFetch<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({ question, top_k })
  });
}

export async function draftTicket(customer_message: string, top_k = 6) {
  return apiFetch<TicketDraftResponse>("/api/tickets/draft", {
    method: "POST",
    body: JSON.stringify({ customer_message, top_k })
  });
}

export async function sendFeedback(payload: { query_log_id: string; rating: number; comment?: string }) {
  return apiFetch<{ status: string }>("/api/feedback", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function fetchMetrics() {
  return apiFetch<MetricsResponse>("/api/metrics");
}

export async function runSync(connector = "all") {
  return apiFetch<SyncRun[]>("/api/sync/run", {
    method: "POST",
    body: JSON.stringify({ connector })
  });
}

export async function fetchSyncRuns(limit = 20) {
  return apiFetch<SyncRun[]>(`/api/sync/runs?limit=${limit}`);
}

export async function fetchSyncStatus() {
  return apiFetch<SyncStatus>("/api/sync/status");
}

export async function createEvalCases(cases: Array<{
  name: string;
  question: string;
  expected_titles: string[];
  expected_sources: string[];
  expected_keywords: string[];
  expected_answer_points: string[];
  tags: string[];
}>) {
  return apiFetch<{ created_cases: number }>("/api/evals/cases", {
    method: "POST",
    body: JSON.stringify({ cases })
  });
}

export async function fetchEvalCases() {
  return apiFetch<EvalBenchmarkCase[]>("/api/evals/cases");
}

export async function runEval(payload: { label: string; top_k?: number; case_ids?: string[] }) {
  return apiFetch<EvalSummary>("/api/evals/run", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function fetchEvalRuns(limit = 10) {
  return apiFetch<EvalSummary[]>(`/api/evals/runs?limit=${limit}`);
}

export async function fetchEvalRunDetail(runId: string) {
  return apiFetch<EvalRunDetail>(`/api/evals/runs/${runId}`);
}
