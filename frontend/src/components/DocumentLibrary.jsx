import { useEffect, useRef, useState } from "react";

const API_URL =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

async function readResponse(response) {
  const data = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : `Request failed: HTTP ${response.status}`,
    );
  }

  if (!data) {
    throw new Error("The server returned an empty response.");
  }

  return data;
}

export default function DocumentLibrary() {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [indexingId, setIndexingId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const fileInput = useRef(null);
  const busy =
  uploading || indexingId !== null || deletingId !== null;

  useEffect(() => {
    const controller = new AbortController();

    async function loadDocuments() {
      try {
        const response = await fetch(`${API_URL}/api/documents`, {
          signal: controller.signal,
        });

        const data = await readResponse(response);

        if (!Array.isArray(data.documents)) {
          throw new Error("The server returned an invalid document list.");
        }

        setDocuments(data.documents);
      } catch (err) {
        if (err.name !== "AbortError") {
          setError(err.message);
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    loadDocuments();

    return () => controller.abort();
  }, []);

  async function handleUpload(event) {
    event.preventDefault();
    setError("");
    setMessage("");

    const file = fileInput.current?.files?.[0];

    if (!file) {
      setError("Select a PDF first.");
      return;
    }

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Please select a PDF file.");
      return;
    }

    if (file.size > 20 * 1024 * 1024) {
      setError("The PDF must be no larger than 20 MiB.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    setUploading(true);

    try {
      const response = await fetch(`${API_URL}/api/documents`, {
        method: "POST",
        body: formData,
      });

      const uploadedDocument = await readResponse(response);

      setDocuments((current) => [uploadedDocument, ...current]);
      setMessage(`${uploadedDocument.filename} uploaded successfully.`);

      if (fileInput.current) {
        fileInput.current.value = "";
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }

  async function handleIndex(documentId) {
    setError("");
    setMessage("");
    setIndexingId(documentId);

    try {
      const response = await fetch(
        `${API_URL}/api/documents/${documentId}/index`,
        { method: "POST" },
      );

      const updatedDocument = await readResponse(response);

      setDocuments((current) =>
        current.map((doc) =>
          doc.id === documentId ? updatedDocument : doc,
        ),
      );

      setMessage(
        `${updatedDocument.filename} indexed successfully: ` +
          `${updatedDocument.chunk_count} chunks.`,
      );
    } catch (err) {
      setError(err.message);

      // Refresh the actual status after a failed indexing request.
      try {
        const response = await fetch(`${API_URL}/api/documents`);
        const data = await readResponse(response);

        if (Array.isArray(data.documents)) {
          setDocuments(data.documents);
        }
      } catch {
        setError(
          `${err.message} Refresh the page to reload document status.`,
        );
      }
    } finally {
      setIndexingId(null);
    }
  }

  async function handleDelete(doc) {
  const confirmed = window.confirm(
    `Delete "${doc.filename}" and its searchable chunks?`,
  );

  if (!confirmed) return;

  setError("");
  setMessage("");
  setDeletingId(doc.id);

  try {
    const response = await fetch(
      `${API_URL}/api/documents/${doc.id}`,
      { method: "DELETE" },
    );

    await readResponse(response);

    setDocuments((current) =>
      current.filter((item) => item.id !== doc.id),
    );

    setMessage(`${doc.filename} deleted.`);
  } catch (err) {
    setError(err.message);

    try {
      const response = await fetch(`${API_URL}/api/documents`);
      const data = await readResponse(response);

      if (Array.isArray(data.documents)) {
        setDocuments(data.documents);
      }
    } catch {
      setError(`${err.message} Refresh to reload document status.`);
    }
  } finally {
    setDeletingId(null);
  }
}
  return (
    <section className="card">
      <h2>Your study library</h2>
      <p>Upload a study PDF, then index it to make it searchable.</p>

      <form className="upload-form" onSubmit={handleUpload}>
        <label htmlFor="study-pdf">Choose a PDF</label>

        <input
          id="study-pdf"
          ref={fileInput}
          type="file"
          accept=".pdf,application/pdf"
          disabled={busy || loading}
        />

        <button type="submit" disabled={busy || loading}>
          {uploading ? "Uploading…" : "Upload PDF"}
        </button>
      </form>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {message && (
        <p className="success" role="status">
          {message}
        </p>
      )}

      {loading ? (
        <p>Loading your documents…</p>
      ) : documents.length === 0 ? (
        <p>No documents uploaded yet.</p>
      ) : (
        <ul className="document-list">
          {documents.map((doc) => (
            <li key={doc.id} className="document-item">
              <div>
                <strong>{doc.filename}</strong>

                <p>
                  {doc.page_count} pages ·{" "}
                  {(doc.size_bytes / (1024 * 1024)).toFixed(2)} MiB
                </p>
              </div>

              <div className="document-actions">
                <span className="document-status">
                  {deletingId === doc.id
                    ? "deleting"
                    : indexingId === doc.id
                      ? "indexing"
                      : doc.status}
                </span>

                <button
                  type="button"
                  onClick={() => handleIndex(doc.id)}
                  disabled={busy}
                >
                  {indexingId === doc.id
                    ? "Indexing…"
                    : doc.status === "indexed"
                      ? "Reindex PDF"
                      : doc.status === "failed"
                        ? "Retry indexing"
                        : "Index PDF"}
                </button>
                <button
                  type="button"
                  className="delete-button"
                  onClick={() => handleDelete(doc)}
                  disabled={busy}
                >
                  {deletingId === doc.id ? "Deleting…" : "Delete PDF"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}