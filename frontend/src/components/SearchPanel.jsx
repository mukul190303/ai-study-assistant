import { useState } from "react";

const API_URL =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export default function SearchPanel() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");

  async function handleSearch(event) {
    event.preventDefault();

    const text = question.trim();

    if (!text) {
      setError("Please enter a question.");
      return;
    }

    setSearching(true);
    setError("");
    setResult(null);

    try {
      const response = await fetch(`${API_URL}/api/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: text,
          top_k: 5,
          min_score: 0.2,
        }),
      });

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : `Search failed: HTTP ${response.status}`,
        );
      }

      if (!data || !Array.isArray(data.matches)) {
        throw new Error("The server returned an unexpected response.");
      }

      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setSearching(false);
    }
  }

  return (
    <section className="card">
      <h2>Search your study materials</h2>
      <p>Find relevant passages across your indexed PDFs.</p>

      <form className="search-form" onSubmit={handleSearch}>
        <label htmlFor="study-question">Your question</label>

        <textarea
          id="study-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="For example: What is continuous integration?"
          rows={3}
          maxLength={2000}
          disabled={searching}
          required
        />

        <button
          type="submit"
          disabled={searching || !question.trim()}
        >
          {searching ? "Searching…" : "Search PDFs"}
        </button>
      </form>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div>
          <p role="status">{result.message}</p>

          {result.matches.map((match) => (
            <article key={match.id} className="search-result">
              <div className="result-heading">
                <strong>
                  [{match.rank}] {match.source}
                </strong>

                <span>Page {match.page}</span>
              </div>

              <p className="result-content">{match.content}</p>

              <small>
                Retrieval similarity:{" "}
                {match.similarity_score.toFixed(3)}
              </small>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}