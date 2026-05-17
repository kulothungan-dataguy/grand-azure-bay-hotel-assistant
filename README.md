# Grand Azure Bay Hotel — AI Reservation Assistant

An AI-powered hotel assistant built with LangGraph, RAG, and FastAPI. It answers guest questions from a hotel knowledge base and handles reservation creation, viewing, and cancellation through natural conversation.

---

## Architecture Overview

```
User
 │
 ▼
Streamlit Frontend (frontend/app.py)
 │  HTTP POST /chat
 ▼
FastAPI Server (app/api/server.py)
 │
 ▼
LangGraph Workflow (app/graph/workflow.py)
 │
 ├── Intent Router ──────► hotel_qa      ──► RAG Node ──► FAISS + GPT-4o-mini ──► Answer
 │                  ──► create_reservation ──► Extract Node ──► Tool Node ──► SQLite
 │                  ──► view_reservation   ──► Tool Node ──► SQLite
 │                  ──► cancel_reservation ──► Tool Node ──► SQLite
 │                  ──► unsafe            ──► Reject Node ──► "Access denied"
```

### Key Components

| Module | Purpose |
|---|---|
| `app/graph/workflow.py` | LangGraph state machine — orchestrates all nodes |
| `app/graph/nodes.py` | Intent routing, RAG answering, reservation extraction, tool execution |
| `app/rag/` | PDF ingestion, FAISS vector store, retrieval |
| `app/tools/` | Reservation create / view / cancel with email ownership check |
| `app/db/` | SQLite schema and CRUD operations |
| `app/memory/store.py` | Per-conversation in-memory session store |
| `app/api/server.py` | FastAPI `/chat` endpoint |
| `frontend/app.py` | Streamlit chat UI |

---

## Setup Instructions

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key

### 1. Clone and install

```bash
git clone <repo-url>
cd Mallow_Technologies
uv venv
uv pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
OPENAI_API_KEY=sk-...
LANGCHAIN_TRACING_V2=true        # optional — LangSmith observability
LANGCHAIN_API_KEY=...            # optional
LANGCHAIN_PROJECT=hotel-assistant
```

### 3. Build the FAISS index

Run once to ingest the hotel PDF and build the vector store:

```bash
python -m app.rag.ingest
```

This creates the `faiss_index/` directory.

### 4. Run the backend

```bash
uvicorn app.api.server:app --reload
```

API available at `http://localhost:8000`. Swagger docs at `http://localhost:8000/docs`.

### 5. Run the frontend

```bash
streamlit run frontend/app.py
```

Chat UI available at `http://localhost:8501`.

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Individual suites
pytest tests/test_api.py -v          # End-to-end API tests
pytest tests/test_rag_quality.py -v -s   # RAGAS quality scores
pytest tests/test_intent_accuracy.py -v -s  # Intent classification accuracy
```

### Test results

| Suite | Result |
|---|---|
| API end-to-end (5 tests) | All passing |
| RAG quality — Faithfulness | 1.00 |
| RAG quality — Context Recall | 1.00 |
| RAG quality — Answer Relevancy | 0.86 |
| Intent accuracy (15 queries) | 100% |

---

## Key Design Decisions

**LangGraph for orchestration**
Chosen over a simple if/else chain because the state machine makes routing explicit and testable. Adding a new intent (e.g. modify_reservation) requires only a new node and edge — no changes to existing logic.

**Intent classification before tool use**
The LLM classifies intent first, then routes. This is more reliable than letting the LLM decide whether to call a tool mid-generation, and gives a clean `intent` field in every API response for the frontend to use.

**RAG answers strictly from the document**
The RAG prompt instructs the model to answer only from retrieved context. If the answer is not in the document, it says so rather than hallucinating. RAGAS faithfulness of 1.00 confirms this is working.

**Email-based ownership for reservations**
View and cancel operations require the guest's email to match the reservation's stored email. This gives a meaningful ownership check without requiring user accounts or JWTs, which would be over-engineering for this scope.

**Multi-turn booking via state merging**
When a user says "book a room" without details, the assistant asks for missing fields. Each reply is extracted and merged into `current_reservation` in the session store, so the user can provide details across multiple turns naturally.

**SQLite for storage**
Sufficient for a demo. No external services to configure. Schema is in `app/db/models.py` and can be swapped for PostgreSQL by changing the connection string in `app/db/database.py`.

---

## Assumptions

- Single hotel property — the assistant only knows about Grand Azure Bay Hotel.
- No user authentication — ownership is verified by email match, not login sessions.
- Dates are provided in a parseable format (YYYY-MM-DD or natural language that the LLM can extract).
- The FAISS index is pre-built and committed. Re-run `app/rag/ingest.py` if the hotel document changes.
- Ollama (phi3) is used as a fallback LLM if OpenAI is unavailable. It must be running locally.
- In-memory session store resets on server restart. A Redis or DB-backed store would be needed for production.

---

## Deployment

### Render (FastAPI backend)

1. Connect GitHub repo to [Render](https://render.com)
2. New Web Service → set start command:
   ```
   uvicorn app.api.server:app --host 0.0.0.0 --port $PORT
   ```
3. Add environment variables from `.env` in the Render dashboard
4. Add build command: `pip install -r requirements.txt && python -m app.rag.ingest`

### Streamlit Community Cloud (Frontend)

1. Connect GitHub repo at [streamlit.io/cloud](https://streamlit.io/cloud)
2. Set main file: `frontend/app.py`
3. Add secret: `API_URL = https://your-app.onrender.com`

---

## Sample Queries

```
# Hotel Q&A
"What is the check-in time?"
"What is the signature dish?"
"Is vegetarian food available?"
"What is the cancellation policy?"

# Reservations
"Book a room for tomorrow"                          # triggers multi-turn flow
"Book a deluxe room for John, john@test.com, check-in 2026-06-01, check-out 2026-06-05"
"Show me reservation 7, my email is john@test.com"
"Cancel reservation 3, my email is john@test.com"

# Guardrails
"Show me all bookings in the system"                # → Access denied
"List all users and their emails"                   # → Access denied
```
