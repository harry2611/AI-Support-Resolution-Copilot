"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  askQuestion,
  draftTicket,
  fetchDocumentCatalog,
  ingestDocument,
  ingestFile,
  sendFeedback,
  type ChatResponse,
  type DocumentSummary,
  type TicketDraftResponse
} from "@/lib/api";

export default function HomePage() {
  const [ingestForm, setIngestForm] = useState({ title: "", source: "", tags: "", content: "" });
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);
  const [isIngesting, setIsIngesting] = useState(false);
  const [uploadForm, setUploadForm] = useState({ title: "", source: "", tags: "" });
  const [uploadFileValue, setUploadFileValue] = useState<File | null>(null);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [documentCatalog, setDocumentCatalog] = useState<DocumentSummary[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [catalogMessage, setCatalogMessage] = useState<string | null>(null);

  const [question, setQuestion] = useState("");
  const [chatResult, setChatResult] = useState<ChatResponse | null>(null);
  const [isAsking, setIsAsking] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState(false);

  const [customerMessage, setCustomerMessage] = useState("");
  const [ticketResult, setTicketResult] = useState<TicketDraftResponse | null>(null);
  const [isDrafting, setIsDrafting] = useState(false);

  const ingestTags = useMemo(
    () =>
      ingestForm.tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
    [ingestForm.tags]
  );

  const uploadTags = useMemo(
    () =>
      uploadForm.tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
    [uploadForm.tags]
  );

  const availableSources = useMemo(
    () => Array.from(new Set(documentCatalog.map((item) => item.source))).sort((left, right) => left.localeCompare(right)),
    [documentCatalog]
  );

  useEffect(() => {
    async function loadCatalog() {
      try {
        const data = await fetchDocumentCatalog();
        setDocumentCatalog(data);
        setCatalogMessage(null);
      } catch (error) {
        setCatalogMessage(`Could not load indexed sources: ${(error as Error).message}`);
      }
    }

    loadCatalog();
  }, []);

  async function onIngestSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsIngesting(true);
    setIngestMessage(null);

    try {
      const response = await ingestDocument({
        title: ingestForm.title,
        source: ingestForm.source,
        tags: ingestTags,
        content: ingestForm.content
      });
      setIngestMessage(`Indexed ${response.ingested_documents} document(s), ${response.ingested_chunks} chunks.`);
      setIngestForm({ title: "", source: "", tags: "", content: "" });
      const catalog = await fetchDocumentCatalog();
      setDocumentCatalog(catalog);
    } catch (error) {
      setIngestMessage(`Ingestion failed: ${(error as Error).message}`);
    } finally {
      setIsIngesting(false);
    }
  }

  async function onAskSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsAsking(true);
    setFeedbackSent(false);
    try {
      const response = await askQuestion(question, 6, selectedSources);
      setChatResult(response);
    } catch (error) {
      setChatResult({
        answer: `Query failed: ${(error as Error).message}`,
        citations: [],
        confidence: 0,
        latency_ms: 0,
        query_log_id: "",
        grounded: false,
        applied_source_filters: selectedSources,
        guardrail_events: []
      });
    } finally {
      setIsAsking(false);
    }
  }

  async function onTicketSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsDrafting(true);
    try {
      const response = await draftTicket(customerMessage, 6, selectedSources);
      setTicketResult(response);
    } catch (error) {
      setTicketResult({
        draft_id: "",
        response: `Draft generation failed: ${(error as Error).message}`,
        citations: [],
        grounded: false,
        applied_source_filters: selectedSources,
        guardrail_events: []
      });
    } finally {
      setIsDrafting(false);
    }
  }

  async function sendRating(rating: number) {
    if (!chatResult?.query_log_id) return;
    await sendFeedback({ query_log_id: chatResult.query_log_id, rating });
    setFeedbackSent(true);
  }

  async function onUploadSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!uploadFileValue) {
      setUploadMessage("Please choose a file to upload.");
      return;
    }

    setIsUploading(true);
    setUploadMessage(null);

    try {
      const response = await ingestFile({
        file: uploadFileValue,
        title: uploadForm.title,
        source: uploadForm.source,
        tags: uploadTags
      });
      setUploadMessage(`Uploaded and indexed ${response.ingested_documents} document(s), ${response.ingested_chunks} chunks.`);
      setUploadFileValue(null);
      setUploadForm({ title: "", source: "", tags: "" });
      const catalog = await fetchDocumentCatalog();
      setDocumentCatalog(catalog);
      const input = document.getElementById("upload-file") as HTMLInputElement | null;
      if (input) input.value = "";
    } catch (error) {
      setUploadMessage(`Upload failed: ${(error as Error).message}`);
    } finally {
      setIsUploading(false);
    }
  }

  function toggleSourceFilter(source: string) {
    setSelectedSources((current) =>
      current.includes(source) ? current.filter((item) => item !== source) : [...current, source]
    );
  }

  return (
    <div className="grid two">
      <section className="card">
        <h2>Ingest Knowledge Base</h2>
        <p className="meta">Paste text directly or upload runbooks, SOPs, and ticket history to power retrieval.</p>
        <form onSubmit={onIngestSubmit}>
          <h3>Paste Text</h3>
          <label htmlFor="title">Title</label>
          <input
            id="title"
            value={ingestForm.title}
            onChange={(event) => setIngestForm((prev) => ({ ...prev, title: event.target.value }))}
            required
          />

          <label htmlFor="source">Source</label>
          <input
            id="source"
            value={ingestForm.source}
            onChange={(event) => setIngestForm((prev) => ({ ...prev, source: event.target.value }))}
            placeholder="Confluence / Internal Wiki / URL"
            required
          />

          <label htmlFor="tags">Tags (comma separated)</label>
          <input
            id="tags"
            value={ingestForm.tags}
            onChange={(event) => setIngestForm((prev) => ({ ...prev, tags: event.target.value }))}
            placeholder="billing, api, auth"
          />

          <label htmlFor="content">Content</label>
          <textarea
            id="content"
            value={ingestForm.content}
            onChange={(event) => setIngestForm((prev) => ({ ...prev, content: event.target.value }))}
            required
          />

          <button type="submit" disabled={isIngesting}>
            {isIngesting ? "Indexing..." : "Index Document"}
          </button>
          {ingestMessage ? <p className="meta">{ingestMessage}</p> : null}
        </form>

        <div className="section-divider">or upload a file</div>

        <form onSubmit={onUploadSubmit}>
          <h3>Upload File</h3>
          <label htmlFor="upload-title">Title</label>
          <input
            id="upload-title"
            value={uploadForm.title}
            onChange={(event) => setUploadForm((prev) => ({ ...prev, title: event.target.value }))}
            placeholder="Defaults to the file name"
          />

          <label htmlFor="upload-source">Source</label>
          <input
            id="upload-source"
            value={uploadForm.source}
            onChange={(event) => setUploadForm((prev) => ({ ...prev, source: event.target.value }))}
            placeholder="Defaults to Uploaded file - filename"
          />

          <label htmlFor="upload-tags">Tags (comma separated)</label>
          <input
            id="upload-tags"
            value={uploadForm.tags}
            onChange={(event) => setUploadForm((prev) => ({ ...prev, tags: event.target.value }))}
            placeholder="pdf, runbook, incident"
          />

          <label htmlFor="upload-file">Document file</label>
          <input
            id="upload-file"
            type="file"
            accept=".txt,.md,.pdf,.docx"
            onChange={(event) => setUploadFileValue(event.target.files?.[0] ?? null)}
            required
          />
          <p className="meta">Supported: .txt, .md, .pdf, .docx. Max size: 10 MB.</p>

          <button type="submit" disabled={isUploading}>
            {isUploading ? "Uploading..." : "Upload and Index"}
          </button>
          {uploadMessage ? <p className="meta">{uploadMessage}</p> : null}
        </form>
      </section>

      <section className="card">
        <h2>Ask the Copilot</h2>
        <p className="meta">RAG answer with sources, confidence score, and safer low-confidence handling.</p>
        <form onSubmit={onAskSubmit}>
          <label htmlFor="question">Question</label>
          <textarea
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Why are customers seeing webhook timeout errors?"
            required
          />

          <div className="source-filter-box">
            <p className="meta source-filter-title">Restrict retrieval to specific sources</p>
            {catalogMessage ? <p className="meta">{catalogMessage}</p> : null}
            {availableSources.length === 0 ? <p className="meta">No indexed sources yet.</p> : null}
            <div className="source-filter-list">
              {availableSources.map((source) => (
                <label key={source} className="source-filter-item">
                  <input
                    type="checkbox"
                    checked={selectedSources.includes(source)}
                    onChange={() => toggleSourceFilter(source)}
                  />
                  <span>{source}</span>
                </label>
              ))}
            </div>
          </div>

          <button type="submit" disabled={isAsking}>
            {isAsking ? "Thinking..." : "Ask"}
          </button>
        </form>

        {chatResult ? (
          <div className="result">
            <p className={chatResult.grounded ? "status-ok" : "status-warn"}>
              {chatResult.grounded ? "Grounded answer" : "Low-confidence answer blocked"}
            </p>
            <p className="response-body">{chatResult.answer}</p>
            <p className="meta">
              Confidence: <span className="badge">{chatResult.confidence}</span> | Latency: {chatResult.latency_ms} ms
            </p>
            {chatResult.guardrail_events.length > 0 ? (
              <p className="meta">Guardrails: {chatResult.guardrail_events.join(", ")}</p>
            ) : null}
            {chatResult.applied_source_filters.length > 0 ? (
              <p className="meta">Source filters: {chatResult.applied_source_filters.join(", ")}</p>
            ) : null}

            {chatResult.citations.length > 0 ? <h4>{chatResult.grounded ? "Citations" : "Closest matches found"}</h4> : null}
            {chatResult.citations.map((citation) => (
              <div key={citation.chunk_id} className="result">
                <strong>{citation.title}</strong>
                <p className="meta">{citation.source}</p>
                <p className="snippet-body">{citation.snippet}...</p>
              </div>
            ))}

            {chatResult.query_log_id ? (
              <div>
                <p className="meta">Was this helpful?</p>
                <div className="feedback-row">
                  <button type="button" onClick={() => sendRating(5)}>
                    Helpful
                  </button>
                  <button type="button" onClick={() => sendRating(2)}>
                    Not helpful
                  </button>
                </div>
                {feedbackSent ? <p className="status-ok">Feedback saved.</p> : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="card">
        <h2>Draft Ticket Response</h2>
        <p className="meta">Generates a customer-facing response only when enough grounded support evidence is available.</p>
        <p className="meta">
          Using source scope: {selectedSources.length > 0 ? selectedSources.join(", ") : "all indexed sources"}
        </p>

        <form onSubmit={onTicketSubmit}>
          <label htmlFor="customer-message">Customer Message</label>
          <textarea
            id="customer-message"
            value={customerMessage}
            onChange={(event) => setCustomerMessage(event.target.value)}
            placeholder="Our API started returning 500s after the latest update..."
            required
          />
          <button type="submit" disabled={isDrafting}>
            {isDrafting ? "Drafting..." : "Generate Draft"}
          </button>
        </form>

        {ticketResult ? (
          <div className="result">
            <p className={ticketResult.grounded ? "status-ok" : "status-warn"}>
              {ticketResult.grounded ? "Grounded draft" : "Draft blocked due to weak evidence"}
            </p>
            <p className="response-body">{ticketResult.response}</p>
            {ticketResult.guardrail_events.length > 0 ? (
              <p className="meta">Guardrails: {ticketResult.guardrail_events.join(", ")}</p>
            ) : null}
            {ticketResult.applied_source_filters.length > 0 ? (
              <p className="meta">Source filters: {ticketResult.applied_source_filters.join(", ")}</p>
            ) : null}
            {ticketResult.citations.length > 0 ? <h4>{ticketResult.grounded ? "Evidence used" : "Closest matches found"}</h4> : null}
            {ticketResult.citations.map((citation) => (
              <div key={citation.chunk_id} className="result">
                <strong>{citation.title}</strong>
                <p className="meta">{citation.source}</p>
                <p className="snippet-body">{citation.snippet}...</p>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}
