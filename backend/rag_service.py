import logging
from functools import lru_cache
from pathlib import Path
from threading import Lock

import chromadb
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer


logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# A new collection avoids mixing this app with your notebook's index.
COLLECTION_NAME = "study_documents_minilm_v1"

# One indexing job at a time in this local server process.
INDEX_LOCK = Lock()


@lru_cache(maxsize=1)
def get_embedding_model():
    return SentenceTransformer(MODEL_NAME)


@lru_cache(maxsize=1)
def get_chroma_client():
    return chromadb.PersistentClient(
        path=str(DATA_DIR / "chroma")
    )


@lru_cache(maxsize=1)
def get_collection():
    collection = get_chroma_client().get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=None,
        metadata={
            "hnsw:space": "cosine",
            "embedding_model": MODEL_NAME,
            "chunking_profile": "tokens_200_overlap_40",
        },
    )

    metadata = collection.metadata or {}

    if (
        metadata.get("hnsw:space") != "cosine"
        or metadata.get("embedding_model") != MODEL_NAME
        or metadata.get("chunking_profile")
        != "tokens_200_overlap_40"
    ):
        raise RuntimeError(
            "Collection configuration mismatch. "
            "Use a new collection name and reindex."
        )

    return collection


def index_pdf(document_id: str, filename: str, pdf_path: Path):
    model = get_embedding_model()

    splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
        model.tokenizer,
        chunk_size=200,
        chunk_overlap=40,
        separators=["\n\n", "\n", " ", ""],
    )

    chunks = []

    with pymupdf.open(pdf_path) as pdf:
        if pdf.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")

        for page_index, page in enumerate(pdf):
            text = page.get_text("text").strip()

            if not text:
                continue

            for chunk_index, text_chunk in enumerate(
                splitter.split_text(text)
            ):
                if not text_chunk.strip():
                    continue

                # Check the actual final chunk against the model limit.
                token_count = len(
                    model.tokenizer.encode(
                        text_chunk,
                        add_special_tokens=True,
                        truncation=False,
                    )
                )

                if token_count > model.max_seq_length:
                    raise ValueError(
                        "A text chunk exceeded the embedding model limit."
                    )

                chunks.append({
                    "id": (
                        f"{document_id}:"
                        f"{page_index}:{chunk_index}"
                    ),
                    "text": text_chunk,
                    "metadata": {
                        "document_id": document_id,
                        "source_file": filename,
                        # Store zero-based pages; display page + 1 later.
                        "page": page_index,
                        "chunk_index": chunk_index,
                    },
                })

    if not chunks:
        raise ValueError(
            "No readable text found. "
            "This PDF may contain scanned images and require OCR."
        )

    collection = get_collection()
    batch_size = min(
        128,
        get_chroma_client().get_max_batch_size(),
    )

    try:
        # Remove previous chunks for this document before rebuilding it.
        collection.delete(where={"document_id": document_id})

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            texts = [chunk["text"] for chunk in batch]

            embeddings = model.encode(
                texts,
                batch_size=32,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )

            collection.upsert(
                ids=[chunk["id"] for chunk in batch],
                documents=texts,
                metadatas=[
                    chunk["metadata"] for chunk in batch
                ],
                embeddings=embeddings.tolist(),
            )

    except Exception:
        # Avoid leaving a partially indexed document after a normal failure.
        try:
            collection.delete(
                where={"document_id": document_id}
            )
        except Exception:
            logger.exception("Could not remove partial document index")
        raise

    return len(chunks)
def retrieve_chunks(
    question: str,
    document_ids: list[str],
    top_k: int = 5,
    min_score: float = 0.2,
):
    question = question.strip()

    if not question:
        raise ValueError("Please enter a question.")

    if not document_ids:
        return []

    model = get_embedding_model()

    token_count = len(
        model.tokenizer.encode(
            question,
            add_special_tokens=True,
            truncation=False,
        )
    )

    if token_count > model.max_seq_length:
        raise ValueError(
            "Your question is too long for the embedding model. "
            "Please shorten it."
        )

    collection = get_collection()
    total_chunks = collection.count()

    if total_chunks == 0:
        return []

    query_embedding = model.encode(
        [question],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    results = collection.query(
        query_embeddings=query_embedding.tolist(),
        n_results=min(top_k, total_chunks),
        where={
            "document_id": {
                "$in": document_ids,
            }
        },
        include=["documents", "metadatas", "distances"],
    )

    matches = []

    for chunk_id, text, metadata, distance in zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        if not text or metadata is None:
            continue

        # Our collection uses cosine distance.
        score = max(-1.0, min(1.0, 1.0 - float(distance)))

        if score < min_score:
            continue

        matches.append({
            "id": chunk_id,
            "document_id": metadata["document_id"],
            "source": metadata["source_file"],
            # Human-readable pages start at 1.
            "page": int(metadata["page"]) + 1,
            "content": text,
            "similarity_score": score,
            "rank": len(matches) + 1,
        })

    return matches
