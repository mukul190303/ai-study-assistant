import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pymupdf
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from uuid import UUID

from rag_service import (
    INDEX_LOCK,
    get_collection,
    index_pdf,
    retrieve_chunks,
)
from pydantic import BaseModel, Field
from llm_service import (
    LLMConfigurationError,
    answer_from_matches,
    build_context,
    get_llm,
    stream_answer_events,
)
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "study_assistant.db"

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MiB


def connect_db():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection
def set_document_status(document_id: str, status: str):
    connection = connect_db()

    try:
        with connection:
            connection.execute(
                "UPDATE documents SET status = ? WHERE id = ?",
                (status, document_id),
            )
    finally:
        connection.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    connection = connect_db()
    try:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                UPDATE documents
                SET status = 'failed'
                WHERE status = 'indexing'
            """)
    finally:
        connection.close()

    yield


app = FastAPI(
    title="AI Study Assistant",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.get("/")
def root():
    return {"message": "AI Study Assistant API is running"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/documents")
def list_documents():
    connection = connect_db()
    try:
        rows = connection.execute("""
            SELECT * FROM documents
            ORDER BY uploaded_at DESC, id
        """).fetchall()

        return {"documents": [dict(row) for row in rows]}
    finally:
        connection.close()


@app.post("/api/documents", status_code=201)
def upload_document(file: UploadFile):
    # Keep the original name only for display.
    # The filesystem path always uses our generated document ID.
    filename = (file.filename or "").replace("\\", "/").split("/")[-1]

    document_id = uuid4().hex
    temporary_path = UPLOAD_DIR / f"{document_id}.part"
    saved_path = UPLOAD_DIR / f"{document_id}.pdf"
    committed = False

    try:
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(400, "Please upload a PDF file.")

        size_bytes = 0

        with temporary_path.open("xb") as destination:
            while chunk := file.file.read(1024 * 1024):
                size_bytes += len(chunk)

                if size_bytes > MAX_FILE_SIZE:
                    raise HTTPException(
                        413, "The PDF must be no larger than 20 MiB."
                    )

                destination.write(chunk)

        if size_bytes == 0:
            raise HTTPException(400, "The uploaded file is empty.")

        try:
            with pymupdf.open(temporary_path) as pdf:
                if not pdf.is_pdf:
                    raise HTTPException(400, "The file is not a valid PDF.")

                if pdf.needs_pass:
                    raise HTTPException(
                        400, "Password-protected PDFs are not supported yet."
                    )

                page_count = pdf.page_count

                if page_count == 0:
                    raise HTTPException(400, "The PDF contains no pages.")

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                400, "The PDF could not be opened. It may be damaged."
            ) from exc

        temporary_path.replace(saved_path)

        document = {
            "id": document_id,
            "filename": filename,
            "page_count": page_count,
            "size_bytes": size_bytes,
            "status": "uploaded",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }

        connection = connect_db()
        try:
            with connection:
                connection.execute("""
                    INSERT INTO documents (
                        id, filename, page_count, size_bytes,
                        status, uploaded_at
                    )
                    VALUES (
                        :id, :filename, :page_count, :size_bytes,
                        :status, :uploaded_at
                    )
                """, document)
        finally:
            connection.close()

        committed = True
        return document

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Document upload failed")
        raise HTTPException(
            500, "Could not save the document. Please try again."
        ) from exc
    finally:
        file.file.close()
        temporary_path.unlink(missing_ok=True)

        if not committed:
            saved_path.unlink(missing_ok=True)
@app.post("/api/documents/{document_id}/index")
def index_document(document_id: UUID):
    # UUID validation prevents arbitrary filesystem paths.
    document_key = document_id.hex

    if not INDEX_LOCK.acquire(blocking=False):
        raise HTTPException(
            409,
            "Another document is being indexed. Please try again shortly.",
        )

    try:
        connection = connect_db()

        try:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?",
                (document_key,),
            ).fetchone()
        finally:
            connection.close()

        if row is None:
            raise HTTPException(404, "Document not found.")

        pdf_path = UPLOAD_DIR / f"{document_key}.pdf"

        if not pdf_path.is_file():
            raise HTTPException(404, "The saved PDF is missing.")

        set_document_status(document_key, "indexing")

        try:
            chunk_count = index_pdf(
                document_id=document_key,
                filename=row["filename"],
                pdf_path=pdf_path,
            )

            set_document_status(document_key, "indexed")

        except ValueError as exc:
            set_document_status(document_key, "failed")
            raise HTTPException(400, str(exc)) from exc

        except Exception as exc:
            logger.exception("PDF indexing failed")
            set_document_status(document_key, "failed")

            raise HTTPException(
                500,
                "Indexing failed. Check the backend terminal and retry.",
            ) from exc

        return {
            **dict(row),
            "status": "indexed",
            "chunk_count": chunk_count,
        }

    finally:
        INDEX_LOCK.release()
class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.2, ge=-1, le=1)

    # None means search all indexed documents.
    document_ids: list[UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )


@app.post("/api/search")
def search_documents(request: SearchRequest):
    question = request.question.strip()

    if not question:
        raise HTTPException(400, "Please enter a question.")

    # Reuse the lock so retrieval cannot read an index mid-rebuild.
    if not INDEX_LOCK.acquire(blocking=False):
        raise HTTPException(
            409,
            "The search service is busy. Please try again shortly.",
        )

    try:
        connection = connect_db()

        try:
            rows = connection.execute(
                "SELECT id FROM documents WHERE status = 'indexed'"
            ).fetchall()
        finally:
            connection.close()

        indexed_ids = {row["id"] for row in rows}

        if request.document_ids is not None:
            selected_ids = list(dict.fromkeys(
                document_id.hex
                for document_id in request.document_ids
            ))

            if any(
                document_id not in indexed_ids
                for document_id in selected_ids
            ):
                raise HTTPException(
                    400,
                    "Every selected document must exist and be indexed.",
                )

        else:
            selected_ids = sorted(indexed_ids)

        if not selected_ids:
            return {
                "question": question,
                "matches": [],
                "message": "Upload and index a PDF before searching.",
            }

        try:
            matches = retrieve_chunks(
                question=question,
                document_ids=selected_ids,
                top_k=request.top_k,
                min_score=request.min_score,
            )

        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        except Exception as exc:
            logger.exception("Document search failed")

            raise HTTPException(
                500,
                "Search failed. Check the backend terminal.",
            ) from exc

        return {
            "question": question,
            "matches": matches,
            "message": (
                f"Found {len(matches)} matching passages."
                if matches
                else "No passages met the similarity threshold."
            ),
        }

    finally:
        INDEX_LOCK.release()

@app.post("/api/ask/stream")
def ask_documents_stream(request: SearchRequest):
    search_result = search_documents(request)

    context, sources = build_context(search_result["matches"])

    llm = None

    if sources:
        try:
            llm = get_llm()

        except LLMConfigurationError as exc:
            raise HTTPException(
                503,
                "Set GROQ_API_KEY in backend/.env and restart the server.",
            ) from exc

        except Exception as exc:
            logger.exception("Could not initialize the LLM")

            raise HTTPException(
                503,
                "Could not initialize the LLM. Check the backend terminal.",
            ) from exc

    return StreamingResponse(
        stream_answer_events(
            question=search_result["question"],
            context=context,
            sources=sources,
            llm=llm,
        ),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
@app.post("/api/ask")
def ask_documents(request: SearchRequest):
    # Reuse the existing search validation and indexed-document filtering.
    search_result = search_documents(request)

    try:
        result = answer_from_matches(
            question=search_result["question"],
            matches=search_result["matches"],
        )

    except LLMConfigurationError as exc:
        raise HTTPException(
            503,
            "The LLM is not configured. Set GROQ_API_KEY "
            "in backend/.env and restart the server.",
        ) from exc

    except Exception as exc:
        logger.exception("Answer generation failed")

        raise HTTPException(
            502,
            "Answer generation failed. Check your Groq key, "
            "model access, quota, and backend terminal.",
        ) from exc

    return {
        "question": search_result["question"],
        **result,
    }
@app.delete("/api/documents/{document_id}")
def delete_document(document_id: UUID):
    document_key = document_id.hex

    if not INDEX_LOCK.acquire(blocking=False):
        raise HTTPException(
            409,
            "The document service is busy. Please try again shortly.",
        )

    try:
        connection = connect_db()

        try:
            row = connection.execute(
                "SELECT id FROM documents WHERE id = ?",
                (document_key,),
            ).fetchone()
        finally:
            connection.close()

        if row is None:
            raise HTTPException(404, "Document not found.")

        # Exclude this document from new searches during deletion.
        set_document_status(document_key, "deleting")

        try:
            get_collection().delete(
                where={"document_id": document_key}
            )

            (UPLOAD_DIR / f"{document_key}.pdf").unlink(
                missing_ok=True
            )

            connection = connect_db()

            try:
                with connection:
                    connection.execute(
                        "DELETE FROM documents WHERE id = ?",
                        (document_key,),
                    )
            finally:
                connection.close()

        except Exception as exc:
            logger.exception("Document deletion failed")
            set_document_status(document_key, "delete_failed")

            raise HTTPException(
                500,
                "Deletion was not completed. Retry deleting the document.",
            ) from exc

        return {"deleted_id": document_key}

    finally:
        INDEX_LOCK.release()