import { useEffect, useState } from "react";
import DocumentLibrary from "./components/DocumentLibrary";
import "./App.css";
import SearchPanel from "./components/SearchPanel";
import AskPanel from "./components/AskPanel";

const API_URL =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

function App() {
  const [status, setStatus] = useState("checking");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();

    async function checkBackend() {
      try {
        const response = await fetch(`${API_URL}/api/health`, {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`Backend returned HTTP ${response.status}`);
        }

        const data = await response.json();

        if (data.status !== "ok") {
          throw new Error("Unexpected health response");
        }

        setStatus("connected");
      } catch (err) {
        if (err.name === "AbortError") return;

        setStatus("disconnected");
        setError(err.message);
      }
    }

    checkBackend();

    return () => controller.abort();
  }, []);

  return (
    <main className="container">
      <header>
        <p className="eyebrow">YOUR PERSONAL LEARNING SPACE</p>
        <h1>AI Study Assistant</h1>
        <p className="subtitle">
          Turn your study materials into answers, summaries, and practice.
        </p>
      </header>

      <section className="card">
        <h2>Backend connection</h2>

        <p className={`status ${status}`} role="status">
          {status === "checking" && "Checking connection…"}
          {status === "connected" && "Connected to FastAPI"}
          {status === "disconnected" && "Could not connect to FastAPI"}
        </p>

        {error && (
          <p className="error">
            {error}. Check that your backend is running on {API_URL}.
          </p>
        )}
      </section>

      <DocumentLibrary />
      <AskPanel />
      <SearchPanel />
      
    </main>
  );
}

export default App;