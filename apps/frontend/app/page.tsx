"use client";

import { FormEvent, useMemo, useState } from "react";

import { askQuestion, draftTicket, ingestDocument, sendFeedback, type ChatResponse, type TicketDraftResponse } from "@/lib/api";

export default function HomePage() {
  const [ingestForm, setIngestForm] = useState({ title: "", source: "", tags: "", content: "" });
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);
  const [isIngesting, setIsIngesting] = useState(false);

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
      const response = await askQuestion(question);
      setChatResult(response);
    } catch (error) {
      setChatResult({
        answer: `Query failed: ${(error as Error).message}`,
        citations: [],
        confidence: 0,
        latency_ms: 0,
        query_log_id: ""
      });
    } finally {
      setIsAsking(false);
    }
  }

  async function onTicketSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsDrafting(true);
    try {
      const response = await draftTicket(customerMessage);
      setTicketResult(response);
    } catch (error) {
      setTicketResult({
        draft_id: "",
        response: `Draft generation failed: ${(error as Error).message}`,
        citations: []
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

  return (
    <div className="grid two">
      <section className="card">
        <h2>Ingest Knowledge Base</h2>
        <p className="meta">Upload runbooks, SOPs, and ticket history to power retrieval.</p>
        <form onSubmit={onIngestSubmit}>
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
      </section>

      <section className="card">
        <h2>Ask the Copilot</h2>
        <p className="meta">RAG answer with sources and confidence score, with automatic web fallback if needed.</p>
        <form onSubmit={onAskSubmit}>
          <label htmlFor="question">Question</label>
          <textarea
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Why are customers seeing webhook timeout errors?"
            required
          />
          <button type="submit" disabled={isAsking}>
            {isAsking ? "Thinking..." : "Ask"}
          </button>
        </form>

        {chatResult ? (
          <div className="result">
            <p>{chatResult.answer}</p>
            <p className="meta">
              Confidence: <span className="badge">{chatResult.confidence}</span> | Latency: {chatResult.latency_ms} ms
            </p>

            {chatResult.citations.length > 0 ? <h4>Citations</h4> : null}
            {chatResult.citations.map((citation) => (
              <div key={citation.chunk_id} className="result">
                <strong>{citation.title}</strong>
                <p className="meta">{citation.source}</p>
                <p>{citation.snippet}...</p>
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
        <p className="meta">Generates a customer-facing response, ready for human approval.</p>

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
            <p>{ticketResult.response}</p>
            {ticketResult.citations.length > 0 ? <h4>Evidence used</h4> : null}
            {ticketResult.citations.map((citation) => (
              <div key={citation.chunk_id} className="result">
                <strong>{citation.title}</strong>
                <p className="meta">{citation.source}</p>
                <p>{citation.snippet}...</p>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}
