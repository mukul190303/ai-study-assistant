import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_URL =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export default function AskPanel() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const controllerRef = useRef(null);

  useEffect(() => {
    return () => controllerRef.current?.abort();
  }, []);

  async function handleAsk(event) {
    event.preventDefault();

    const text = question.trim();
    if (!text || controllerRef.current) return;

    const controller = new AbortController();
    controllerRef.current = controller;

    setAsking(true);
    setError("");
    setStatus("Searching PDFs…");
    setResult({ answer: "", sources: [] });

    let reader;
    let completed = false;

    function processLine(line) {
      if (!line.trim()) return;

      const event = JSON.parse(line);

      if (event.type === "sources") {
        setResult((current) => ({
          ...current,
          sources: event.sources,
        }));
        setStatus("Generating answer…");
      } else if (event.type === "delta") {
        setResult((current) => ({
          ...current,
          answer: current.answer + event.text,
        }));
      } else if (event.type === "done") {
        completed = true;
        setStatus("Complete");
      } else if (event.type === "error") {
        throw new Error(event.message);
      }
    }

    try {
      const response = await fetch(`${API_URL}/api/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: text,
          top_k: 5,
          min_score: 0.2,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => null);

        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : `Request failed: HTTP ${response.status}`,
        );
      }

      if (!response.body) {
        throw new Error("Streaming is unavailable in this browser.");
      }

      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();

        if (done) {
          buffer += decoder.decode();
          break;
        }

        buffer += decoder.decode(value, { stream: true });

        // A network chunk can contain part of an event or several events.
        let newline;

        while ((newline = buffer.indexOf("\n")) !== -1) {
          processLine(buffer.slice(0, newline));
          buffer = buffer.slice(newline + 1);
        }
      }

      if (buffer.trim()) {
        processLine(buffer);
      }

      if (!completed) {
        throw new Error("The connection ended before the answer completed.");
      }
    } catch (err) {
      if (controller.signal.aborted) {
        setStatus("Stopped — the answer may be incomplete.");
      } else {
        setError(err.message);
        setStatus("Failed — the answer may be incomplete.");
      }
    } finally {
      if (reader) {
        try {
          await reader.cancel();
        } catch {
          // The connection may already be closed.
        }
        reader.releaseLock();
      }

      controllerRef.current = null;
      setAsking(false);
    }
  }

  return (
    <section className="card">
      <h2>Ask your PDFs</h2>
      <p>Get cited answers from your indexed study materials.</p>

      <form className="search-form" onSubmit={handleAsk}>
        <label htmlFor="ask-question">Your question</label>

        <textarea
          id="ask-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="What is DevOps?"
          rows={3}
          maxLength={2000}
          disabled={asking}
          required
        />

        <div className="ask-actions">
          <button
            type="submit"
            disabled={asking || !question.trim()}
          >
            {asking ? "Generating…" : "Ask"}
          </button>

          {asking && (
            <button
              type="button"
              className="stop-button"
              onClick={() => controllerRef.current?.abort()}
            >
              Stop generating
            </button>
          )}
        </div>
      </form>

      {status && <p role="status">{status}</p>}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="answer-panel">
          {result.answer && (
            <div className="answer-text">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {result.answer}
              </ReactMarkdown>
            </div>
          )}

          {result.sources.length > 0 && (
            <div className="answer-sources">
              <h3>Retrieved sources</h3>

              {result.sources.map((source) => (
                <details key={source.id} className="source-details">
                  <summary>
                    [{source.reference}] {source.source} — Page{" "}
                    {source.page}
                  </summary>

                  <p className="result-content">{source.content}</p>
                </details>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}