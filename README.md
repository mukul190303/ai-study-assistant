# AI Study Assistant

A full-stack study assistant that turns uploaded PDFs into searchable study materials and generates answers with page references using Retrieval-Augmented Generation (RAG).

The application combines a React frontend, FastAPI backend, local embedding model, Chroma vector database, and Groq-hosted LLM. Students can inspect retrieved passages, stream answers, and revisit saved conversations.

## Features

- **PDF library:** Upload PDFs up to 20 MiB and persist document metadata in SQLite.
- **Document validation:** Reject empty, invalid, and password-protected PDFs.
- **PDF indexing:** Extract page text, split it into overlapping chunks, and generate local embeddings.
- **Semantic search:** Retrieve relevant passages with filenames, page numbers, and cosine similarity scores.
- **Document-grounded answers:** Generate answers from retrieved excerpts and acknowledge insufficient information.
- **Streaming responses:** Display answer text as it arrives, with a Stop generating control.
- **Markdown formatting:** Render headings, lists, tables, and code blocks.
- **Source inspection:** Expand source excerpts to check whether answers are supported.
- **PDF deletion:** Remove the uploaded file, its document record, and its searchable chunks.
- **Saved conversations:** Store questions, answers, source excerpts, and generation status in SQLite.

Saved conversations currently preserve and group messages. Follow-up questions are not yet rewritten using conversation history.

## Technology stack

| Layer | Technology | Responsibility |
| --- | --- | --- |
| Frontend | React + Vite | Document library, search, answers, and conversation UI |
| Styling | CSS | Application layout and Markdown presentation |
| Markdown | react-markdown + remark-gfm | Render generated Markdown |
| Backend | Python + FastAPI | HTTP APIs and streaming responses |
| PDF processing | PyMuPDF | Validate PDFs and extract page text |
| Text splitting | LangChain Text Splitters | Tokenizer-aware chunking |
| Embeddings | Sentence Transformers | Local text and query embeddings |
| Embedding model | sentence-transformers/all-MiniLM-L6-v2 | Semantic representations |
| Vector database | ChromaDB | Persist embeddings and search chunks |
| LLM integration | LangChain ChatGroq | Call the Groq-hosted model |
| Default LLM | openai/gpt-oss-20b | Generate grounded answers |
| Application database | SQLite | Document and conversation records |

## How it works

### Indexing

1. The user uploads a PDF through React.
2. FastAPI validates it and stores the file under a generated document ID.
3. SQLite records its filename, page count, size, timestamp, and status.
4. The user indexes the document.
5. PyMuPDF extracts text separately from each page.
6. A tokenizer-aware splitter creates overlapping chunks, targeting 200 tokens with 40-token overlap.
7. Sentence Transformers generates normalized embeddings.
8. Chroma stores the text, embeddings, and source metadata in a cosine collection.

Chunk IDs are derived from the document ID, page index, and chunk index. Reindexing removes the previous chunks for that document before rebuilding them.

### Answer generation

1. React sends the question to the backend.
2. The backend limits search to documents marked `indexed`.
3. The same embedding model encodes the question.
4. Chroma retrieves the nearest matching chunks, optionally restricted to selected document IDs.
5. The backend filters matches using a cosine similarity threshold.
6. Retrieved excerpts are numbered and placed within a 12,000-character context budget.
7. The LLM generates a Markdown answer with inline references such as `[1]`.
8. The frontend receives sources, answer text, and completion or error events through a newline-delimited JSON stream.
9. The conversation service saves the question, answer, sources, and generation status.

Stored page indices are zero-based; displayed page numbers start at 1.

## Project layout

The current development setup has a nested frontend directory. Run npm commands in **`frontend/frontend`**, where the Vite application and its `package.json` live.

| Path | Purpose |
| --- | --- |
| `backend/main.py` | FastAPI app, database initialization, and API routes |
| `backend/rag_service.py` | Embedding model, Chroma collection, indexing, and retrieval |
| `backend/llm_service.py` | Prompt construction, answer generation, and streaming |
| `backend/conversation_service.py` | SQLite conversation persistence |
| `backend/.env` | Backend environment variables; do not commit |
| `backend/data/uploads/` | Uploaded PDFs |
| `backend/data/chroma/` | Persistent vector database |
| `backend/data/study_assistant.db` | SQLite database |
| `frontend/frontend/src/App.jsx` | Main React screen |
| `frontend/frontend/src/components/DocumentLibrary.jsx` | Upload, index, and delete documents |
| `frontend/frontend/src/components/SearchPanel.jsx` | Inspect semantic search results |
| `frontend/frontend/src/components/AskPanel.jsx` | Stream answers and select conversations |
| `frontend/frontend/src/components/ConversationHistory.jsx` | Browse saved questions and answers |
| `frontend/frontend/src/App.css` | Component and Markdown styles |
| `.gitignore` | Exclude secrets, dependencies, and runtime data |

## Local setup

### Prerequisites

- Python with support for the listed backend dependencies; Python 3.11 is a suitable starting environment.
- Node.js and npm compatible with the Vite version in the frontend project.
- A Groq account and API key with access to the configured model.
- Internet access for the initial embedding-model download and LLM requests.

The following commands use **Windows Command Prompt** and assume you are starting in the project root.

### 1. Set up the backend

```bat
cd backend
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install "fastapi[standard]" python-dotenv python-multipart pymupdf sentence-transformers chromadb langchain-text-splitters langchain-groq
```

If the virtual environment already exists, activate it without recreating it.

Create `backend/.env`:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-20b
```

Get an API key from [Groq Console](https://console.groq.com/keys). Restart the backend after changing its environment configuration.

Start FastAPI from the `backend` directory:

```bat
fastapi dev main.py
```

- Backend: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Health check: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- Interactive API documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

The backend creates its data directories and database tables during startup. Embeddings run locally; a Groq key is needed for LLM-generated answers, not for indexing or semantic search.

### 2. Set up the frontend

Open a second terminal in the project root:

```bat
cd frontend\frontend
npm install
npm install react-markdown remark-gfm
npm run dev
```

Open the URL printed by Vite, usually [http://localhost:5173](http://localhost:5173). Keep both terminals running.

The frontend defaults to `http://127.0.0.1:8000`. To override it, create an `.env` file in the **inner frontend directory**:

```env
VITE_API_URL=http://127.0.0.1:8000
```

Restart Vite after changing frontend environment variables. Never place the Groq key in a `VITE_` variable: frontend environment values are exposed to the browser.

If Vite selects another port, add that exact frontend origin to `allow_origins` in `backend/main.py`.

## Usage

1. Check that the backend connection indicator is green.
2. Upload a text-based study PDF.
3. Click **Index PDF** and wait for the `indexed` status.
4. Use **Search PDFs** to inspect matching passages.
5. Use **Ask your PDFs** to generate a cited answer.
6. Expand sources to check supporting text.
7. Use **Stop generating** to cancel the browser request and keep the partial answer visible.
8. Reopen a saved conversation from the conversation selector.
9. Use **Delete PDF** to remove a document from the library and future searches.

Document states include `uploaded`, `indexing`, `indexed`, and `failed`. Deletion uses `deleting` and `delete_failed` states so incomplete operations can be retried. Conversation turns use `generating`, `completed`, `interrupted`, and `failed`.

## API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/` | Basic API information |
| GET | `/api/health` | Server health response |
| GET | `/api/documents` | List uploaded documents |
| POST | `/api/documents` | Upload one PDF using a multipart `file` field |
| POST | `/api/documents/{document_id}/index` | Index or reindex a PDF |
| DELETE | `/api/documents/{document_id}` | Delete file, vector chunks, and document record |
| POST | `/api/search` | Retrieve matching PDF passages |
| POST | `/api/ask` | Generate a complete, non-streaming answer |
| POST | `/api/ask/stream` | Stream an answer and save its conversation turn |
| GET | `/api/conversations` | List saved conversations |
| GET | `/api/conversations/{conversation_id}` | Read a conversation and its turns |

### Search request

```json
{
  "question": "How are containers different from virtual machines?",
  "top_k": 5,
  "min_score": 0.2
}
```

Add a non-empty `document_ids` array containing IDs returned by `/api/documents` to restrict the search. Every selected document must be indexed.

### Streaming answer request

```json
{
  "question": "How are containers different from virtual machines?",
  "top_k": 5,
  "min_score": 0.2,
  "conversation_id": null
}
```

Use `null` to start a conversation. Pass the ID returned in the stream to append another turn to it. The stream uses `application/x-ndjson` with `conversation`, `sources`, `delta`, `done`, and `error` events. Network chunks are not guaranteed to correspond to individual events; the frontend buffers text until a complete line arrives.

## Data handling and limitations

- **Local development:** This version has no authentication or per-user data isolation. Run it as a single local backend process; its indexing/search/deletion lock is process-local.
- **PDF content:** Scanned PDFs require OCR, which is not implemented. Mixed PDFs may have image-only pages skipped during text extraction.
- **Grounding:** A syllabus listing a topic may not contain enough material to explain it. Upload explanatory notes for detailed answers.
- **Retrieval scores:** Cosine similarity is not answer confidence. The default threshold is a starting point and needs evaluation against representative questions.
- **Citations:** Inline references are generated by the LLM and are not automatically checked for factual support.
- **Context:** The context budget is character-based, not an exact token budget. Long questions exceeding the embedding model's token limit are rejected.
- **Reindexing:** Rebuilding an index replaces the previous chunks. A failed rebuild can leave the document without a usable index until retried.
- **Deletion:** File, SQLite, and Chroma operations are not one transaction. Failed deletions can be retried. Answers already in progress may use passages retrieved before deletion.
- **Conversation retention:** Deleting a PDF does not remove source excerpts already saved in conversation history.
- **Streaming:** Stop cancels the browser request; provider-side cancellation and interrupted-turn persistence may take time. A process crash can lose unsaved partial text.
- **External processing:** Retrieved excerpts and questions are sent to Groq for answer generation. Embeddings are generated locally.
- **Dependency versions:** The setup commands do not pin Python packages. For reproducible installs, capture versions from a working environment in a requirements file and retain the frontend lockfile.

## Troubleshooting

| Issue | Check |
| --- | --- |
| `Missing script: "dev"` | Run npm inside `frontend/frontend`, not the outer frontend directory. |
| Frontend cannot connect | Start FastAPI, verify `VITE_API_URL`, and check the allowed CORS origin. |
| Index button is missing | Ensure its JSX is inside the returned document list in `DocumentLibrary.jsx`. |
| Circular import from `rag_service` | Keep service definitions in `rag_service.py`; import them from `main.py`, never from the service into itself. |
| No readable PDF text | Use a text-based PDF or apply OCR before uploading. |
| Unrelated search results | Inspect excerpts, scope search to the intended PDF, and evaluate `top_k` and `min_score`. |
| LLM configuration error | Check `backend/.env`, model access, and Groq quota; restart the backend. |
| Collection configuration mismatch | Use a new collection name and reindex documents rather than mixing embedding or chunking configurations. |
| Busy response (`409`) | Wait for indexing, search, or deletion to finish and retry. |

## Development checks

From the backend directory:

```bat
python -m py_compile main.py rag_service.py llm_service.py conversation_service.py
```

From the inner frontend directory:

```bat
npm run lint
npm run build
```

These check Python syntax, frontend lint rules, and the production frontend build. They do not replace end-to-end validation of retrieval quality, citations, persistence, cancellation, and deletion.

## Roadmap

- Conversation-aware query rewriting and follow-up answers.
- Study summaries, quizzes, and flashcards.
- Document selection in the answer UI.
- OCR support for scanned notes.
- Hybrid keyword/vector retrieval and reranking.
- Retrieval and answer-quality evaluation.
- Background indexing with progress reporting.
- Authentication and per-user document isolation.
- Conversation deletion and retention controls.
- Docker packaging and deployment configuration.

## Author

Mukul Dev Singh

