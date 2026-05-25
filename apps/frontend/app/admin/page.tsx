"use client";

import { useEffect, useState } from "react";

import {
  createEvalCases,
  fetchEvalCases,
  fetchEvalRunDetail,
  fetchEvalRuns,
  fetchMetrics,
  fetchSyncRuns,
  fetchSyncStatus,
  runEval,
  runSync,
  type EvalBenchmarkCase,
  type EvalRunDetail,
  type EvalSummary,
  type MetricsResponse,
  type SyncRun,
  type SyncStatus
} from "@/lib/api";

const initialMetrics: MetricsResponse = {
  total_queries: 0,
  avg_latency_ms: 0,
  avg_confidence: 0,
  drafts_pending_review: 0,
  documents_indexed: 0,
  avg_feedback_rating: null
};

const initialEvalForm = {
  name: "",
  question: "",
  expectedTitles: "",
  expectedSources: "",
  expectedKeywords: "",
  expectedAnswerPoints: "",
  tags: ""
};

function splitCsv(input: string) {
  return input
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function AdminPage() {
  const [metrics, setMetrics] = useState<MetricsResponse>(initialMetrics);
  const [syncRuns, setSyncRuns] = useState<SyncRun[]>([]);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [evalCases, setEvalCases] = useState<EvalBenchmarkCase[]>([]);
  const [evalRuns, setEvalRuns] = useState<EvalSummary[]>([]);
  const [selectedEvalRun, setSelectedEvalRun] = useState<EvalRunDetail | null>(null);
  const [evalForm, setEvalForm] = useState(initialEvalForm);
  const [evalRunLabel, setEvalRunLabel] = useState("manual-benchmark");
  const [isRunningSync, setIsRunningSync] = useState(false);
  const [isCreatingEvalCase, setIsCreatingEvalCase] = useState(false);
  const [isRunningEval, setIsRunningEval] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadAdminData() {
      try {
        setError(null);
        const [metricsData, statusData, runData, caseData, evalRunData] = await Promise.all([
          fetchMetrics(),
          fetchSyncStatus(),
          fetchSyncRuns(15),
          fetchEvalCases(),
          fetchEvalRuns(10)
        ]);
        setMetrics(metricsData);
        setSyncStatus(statusData);
        setSyncRuns(runData);
        setEvalCases(caseData);
        setEvalRuns(evalRunData);

        if (evalRunData.length > 0) {
          const detail = await fetchEvalRunDetail(evalRunData[0].run_id);
          setSelectedEvalRun(detail);
        }
      } catch (err) {
        setError((err as Error).message);
      }
    }

    loadAdminData();
  }, []);

  async function refreshEvalData(selectedRunId?: string) {
    const [caseData, runData] = await Promise.all([fetchEvalCases(), fetchEvalRuns(10)]);
    setEvalCases(caseData);
    setEvalRuns(runData);

    const runId = selectedRunId ?? runData[0]?.run_id;
    if (runId) {
      const detail = await fetchEvalRunDetail(runId);
      setSelectedEvalRun(detail);
    } else {
      setSelectedEvalRun(null);
    }
  }

  async function onRunSync(connector: string) {
    setIsRunningSync(true);
    setError(null);
    try {
      await runSync(connector);
      const [statusData, runData] = await Promise.all([fetchSyncStatus(), fetchSyncRuns(15)]);
      setSyncStatus(statusData);
      setSyncRuns(runData);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsRunningSync(false);
    }
  }

  async function onCreateEvalCase() {
    setIsCreatingEvalCase(true);
    setError(null);
    try {
      await createEvalCases([
        {
          name: evalForm.name,
          question: evalForm.question,
          expected_titles: splitCsv(evalForm.expectedTitles),
          expected_sources: splitCsv(evalForm.expectedSources),
          expected_keywords: splitCsv(evalForm.expectedKeywords),
          expected_answer_points: splitCsv(evalForm.expectedAnswerPoints),
          tags: splitCsv(evalForm.tags)
        }
      ]);
      setEvalForm(initialEvalForm);
      await refreshEvalData(selectedEvalRun?.run_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsCreatingEvalCase(false);
    }
  }

  async function onRunEval() {
    setIsRunningEval(true);
    setError(null);
    try {
      const run = await runEval({ label: evalRunLabel, top_k: 6 });
      await refreshEvalData(run.run_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsRunningEval(false);
    }
  }

  async function onSelectEvalRun(runId: string) {
    setError(null);
    try {
      const detail = await fetchEvalRunDetail(runId);
      setSelectedEvalRun(detail);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="grid admin-grid">
      <section className="card">
        <h2>Ops Dashboard</h2>
        <p className="meta">Support-copilot KPIs and model behavior signals.</p>

        {error ? <p className="meta">Failed to load data: {error}</p> : null}

        <div className="metric">
          <span>Total Queries</span>
          <strong>{metrics.total_queries}</strong>
        </div>
        <div className="metric">
          <span>Average Latency (ms)</span>
          <strong>{metrics.avg_latency_ms}</strong>
        </div>
        <div className="metric">
          <span>Average Confidence</span>
          <strong>{metrics.avg_confidence}</strong>
        </div>
        <div className="metric">
          <span>Drafts Pending Review</span>
          <strong>{metrics.drafts_pending_review}</strong>
        </div>
        <div className="metric">
          <span>Documents Indexed</span>
          <strong>{metrics.documents_indexed}</strong>
        </div>
        <div className="metric">
          <span>Average Feedback Rating</span>
          <strong>{metrics.avg_feedback_rating ?? "n/a"}</strong>
        </div>
      </section>

      <section className="card">
        <h2>Connector Sync</h2>
        <p className="meta">Run manual sync or monitor scheduled ingestion.</p>

        <div className="metric">
          <span>Scheduler</span>
          <strong>{syncStatus?.scheduler_running ? "running" : "stopped"}</strong>
        </div>
        <div className="metric">
          <span>Interval (minutes)</span>
          <strong>{syncStatus?.interval_minutes ?? "n/a"}</strong>
        </div>
        <div className="metric">
          <span>Enabled Connectors</span>
          <strong>{syncStatus?.connectors_enabled.join(", ") || "none"}</strong>
        </div>

        <div className="feedback-row wrap-row">
          <button type="button" disabled={isRunningSync} onClick={() => onRunSync("all")}>
            Sync All
          </button>
          <button type="button" disabled={isRunningSync} onClick={() => onRunSync("confluence")}>
            Sync Confluence
          </button>
          <button type="button" disabled={isRunningSync} onClick={() => onRunSync("notion")}>
            Sync Notion
          </button>
        </div>

        <h3>Recent Sync Runs</h3>
        {syncRuns.length === 0 ? <p className="meta">No sync runs yet.</p> : null}
        {syncRuns.map((run) => (
          <div key={run.run_id} className="result">
            <p>
              <strong>{run.connector}</strong> | {run.status}
            </p>
            <p className="meta">
              fetched {run.total_fetched}, ingested {run.total_ingested}, skipped {run.total_skipped}, chunks {run.total_chunks}
            </p>
            <p className="meta">started {new Date(run.started_at).toLocaleString()}</p>
            {run.error_message ? <p className="meta">error: {run.error_message}</p> : null}
          </div>
        ))}
      </section>

      <section className="card">
        <h2>Evaluation Lab</h2>
        <p className="meta">Benchmark retrieval precision, answer coverage, hallucination risk, and RAGAs-style quality signals.</p>

        <label htmlFor="eval-name">Benchmark case name</label>
        <input
          id="eval-name"
          value={evalForm.name}
          onChange={(event) => setEvalForm((current) => ({ ...current, name: event.target.value }))}
          placeholder="Webhook timeout debugging benchmark"
        />

        <label htmlFor="eval-question">Evaluation question</label>
        <textarea
          id="eval-question"
          value={evalForm.question}
          onChange={(event) => setEvalForm((current) => ({ ...current, question: event.target.value }))}
          placeholder="What should support check first when webhook failures spike after a deploy?"
        />

        <label htmlFor="eval-expected-titles">Expected titles (comma separated)</label>
        <input
          id="eval-expected-titles"
          value={evalForm.expectedTitles}
          onChange={(event) => setEvalForm((current) => ({ ...current, expectedTitles: event.target.value }))}
          placeholder="Webhook Timeout Runbook v1"
        />

        <label htmlFor="eval-expected-sources">Expected sources (comma separated)</label>
        <input
          id="eval-expected-sources"
          value={evalForm.expectedSources}
          onChange={(event) => setEvalForm((current) => ({ ...current, expectedSources: event.target.value }))}
          placeholder="Internal Wiki - Support Ops"
        />

        <label htmlFor="eval-expected-keywords">Expected retrieval keywords (comma separated)</label>
        <input
          id="eval-expected-keywords"
          value={evalForm.expectedKeywords}
          onChange={(event) => setEvalForm((current) => ({ ...current, expectedKeywords: event.target.value }))}
          placeholder="dns, tls certificate, firewall, rollback"
        />

        <label htmlFor="eval-expected-answer-points">Expected answer points (comma separated)</label>
        <input
          id="eval-expected-answer-points"
          value={evalForm.expectedAnswerPoints}
          onChange={(event) => setEvalForm((current) => ({ ...current, expectedAnswerPoints: event.target.value }))}
          placeholder="verify DNS, check TLS certificate, review recent deploys"
        />

        <label htmlFor="eval-tags">Tags (comma separated)</label>
        <input
          id="eval-tags"
          value={evalForm.tags}
          onChange={(event) => setEvalForm((current) => ({ ...current, tags: event.target.value }))}
          placeholder="webhooks, reliability"
        />

        <div className="feedback-row wrap-row">
          <button type="button" disabled={isCreatingEvalCase} onClick={onCreateEvalCase}>
            Add Benchmark Case
          </button>
        </div>

        <div className="eval-run-form">
          <label htmlFor="eval-run-label">Run label</label>
          <input
            id="eval-run-label"
            value={evalRunLabel}
            onChange={(event) => setEvalRunLabel(event.target.value)}
            placeholder="weekly-regression-check"
          />
          <button type="button" disabled={isRunningEval || evalCases.length === 0} onClick={onRunEval}>
            Run Benchmark
          </button>
        </div>

        <h3>Benchmark Cases</h3>
        {evalCases.length === 0 ? <p className="meta">No eval cases yet. Add one to start benchmarking.</p> : null}
        {evalCases.slice(0, 6).map((item) => (
          <div key={item.case_id} className="result">
            <p>
              <strong>{item.name}</strong>
            </p>
            <p className="meta">{item.question}</p>
            <p className="meta">
              titles: {item.expected_titles.join(", ") || "n/a"} | sources: {item.expected_sources.join(", ") || "n/a"}
            </p>
          </div>
        ))}
      </section>

      <section className="card">
        <h2>Eval Runs</h2>
        <p className="meta">Stored run summaries and per-case analysis.</p>

        {evalRuns.length === 0 ? <p className="meta">No eval runs yet.</p> : null}
        {evalRuns.map((run) => (
          <div key={run.run_id} className="result clickable" onClick={() => onSelectEvalRun(run.run_id)}>
            <p>
              <strong>{run.label}</strong> | {run.status}
            </p>
            <p className="meta">
              hit rate {run.retrieval_hit_rate}, precision@k {run.avg_precision_at_k}, recall@k {run.avg_recall_at_k}
            </p>
            <p className="meta">
              grounding {run.avg_grounding_score}, hallucination risk {run.avg_hallucination_risk}, latency {run.avg_latency_ms} ms
            </p>
            {run.ragas_style_metrics ? (
              <p className="meta">
                answer relevance {run.ragas_style_metrics.answer_relevance}, faithfulness {run.ragas_style_metrics.faithfulness}
              </p>
            ) : null}
          </div>
        ))}

        {selectedEvalRun ? (
          <>
            <h3>Selected Run: {selectedEvalRun.label}</h3>
            <div className="metric">
              <span>Total Cases</span>
              <strong>{selectedEvalRun.total_cases}</strong>
            </div>
            <div className="metric">
              <span>Retrieval Hit Rate</span>
              <strong>{selectedEvalRun.retrieval_hit_rate}</strong>
            </div>
            <div className="metric">
              <span>Average Precision@k</span>
              <strong>{selectedEvalRun.avg_precision_at_k}</strong>
            </div>
            <div className="metric">
              <span>Average Recall@k</span>
              <strong>{selectedEvalRun.avg_recall_at_k}</strong>
            </div>
            <div className="metric">
              <span>Answer Coverage</span>
              <strong>{selectedEvalRun.avg_answer_coverage}</strong>
            </div>
            <div className="metric">
              <span>Grounding Score</span>
              <strong>{selectedEvalRun.avg_grounding_score}</strong>
            </div>
            <div className="metric">
              <span>Hallucination Risk</span>
              <strong>{selectedEvalRun.avg_hallucination_risk}</strong>
            </div>
            {selectedEvalRun.ragas_style_metrics ? (
              <>
                <div className="metric">
                  <span>Answer Relevance</span>
                  <strong>{selectedEvalRun.ragas_style_metrics.answer_relevance}</strong>
                </div>
                <div className="metric">
                  <span>Faithfulness</span>
                  <strong>{selectedEvalRun.ragas_style_metrics.faithfulness}</strong>
                </div>
                <div className="metric">
                  <span>Context Precision</span>
                  <strong>{selectedEvalRun.ragas_style_metrics.context_precision}</strong>
                </div>
                <div className="metric">
                  <span>Context Recall</span>
                  <strong>{selectedEvalRun.ragas_style_metrics.context_recall}</strong>
                </div>
              </>
            ) : null}
            <div className="metric">
              <span>LangSmith Tracing</span>
              <strong>
                {selectedEvalRun.langsmith_tracing_enabled
                  ? `enabled${selectedEvalRun.langsmith_project ? ` (${selectedEvalRun.langsmith_project})` : ""}`
                  : "disabled"}
              </strong>
            </div>

            <h3>Case Results</h3>
            {selectedEvalRun.results.map((result) => (
              <div key={result.result_id} className="result">
                <p>
                  <strong>{result.case_name}</strong> | hit {result.retrieval_hit ? "yes" : "no"}
                </p>
                <p className="meta">{result.question}</p>
                <p className="meta">
                  precision {result.precision_at_k}, recall {result.recall_at_k}, grounding {result.grounding_score}, hallucination risk{" "}
                  {result.hallucination_risk}
                </p>
                {result.ragas_style_metrics ? (
                  <p className="meta">
                    answer relevance {result.ragas_style_metrics.answer_relevance}, faithfulness {result.ragas_style_metrics.faithfulness},
                    context precision {result.ragas_style_metrics.context_precision}, context recall{" "}
                    {result.ragas_style_metrics.context_recall}
                  </p>
                ) : null}
                <p>{result.generated_answer}</p>
                {result.notes ? <p className="meta">notes: {result.notes}</p> : null}
              </div>
            ))}
          </>
        ) : null}
      </section>
    </div>
  );
}
