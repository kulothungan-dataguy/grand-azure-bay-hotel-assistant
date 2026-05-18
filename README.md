---
title: Grand Azure Bay API
emoji: 🏨
colorFrom: blue
colorTo: yellow
sdk: docker
pinned: false
---

# Grand Azure Bay Hotel — AI Reservation Assistant

An AI-powered hotel concierge built with **LangGraph**, **RAG (FAISS + GPT-4o-mini)**, and **FastAPI**. Guests can ask hotel questions, book rooms, view and cancel reservations through natural conversation — with a structured booking form, email-based ownership verification, and human escalation for unanswered questions.

---

## Live Demo

| Service | URL |
|---|---|
| Chat UI (Streamlit) | https://huggingface.co/spaces/Real-Kulothungan/grand-azure-bay |
| API (FastAPI) | https://huggingface.co/spaces/Real-Kulothungan/grand-azure-bay-api |
| API Docs | https://real-kulothungan-grand-azure-bay-api.hf.space/docs |

---

## Architecture

```
Guest
 │
 ▼
Streamlit Frontend  ──POST /chat/stream──►  FastAPI Server
                                                │
                                    ┌───────────▼───────────┐
                                    │  Intent Classifier    │  (GPT-4o-mini)
                                    └───────────┬───────────┘
                                                │
                    ┌───────────────────────────┼──────────────────────────┐
                    ▼                           ▼                          ▼
              hotel_qa                  create/view/cancel           general /
           RAG Node                      Extract Node               unsafe
        FAISS + GPT-4o-mini              Tool Node              reject / greet
              │                          SQLite DB
              ▼
         diskcache (24h TTL)
```

### Node summary

| Node | Responsibility |
|---|---|
| `intent_router` | Classifies query into 6 intents |
| `rag_node` | Retrieves from FAISS, answers with GPT-4o-mini, caches 24 h |
| `extract_reservation` | Extracts partial booking fields, merges with session state |
| `tool_node` | Creates / views / cancels reservations in SQLite |
| `general_node` | Friendly responses for greetings and small talk |
| `reject_node` | Blocks unsafe / adversarial queries |

---

## Key Features

- **Email-first flow** — email collected once at session start, auto-injected into all reservation operations
- **Structured booking form** — date pickers and dropdowns eliminate LLM date-parsing errors
- **Active-only reservations** — view and cancel show only CONFIRMED + future check-out dates
- **Human escalation** — "Ask a Human" button appears when the bot can't answer; query stored for staff via `/admin/escalations`
- **RAG with caching** — diskcache prevents duplicate LLM calls for repeated hotel questions
- **Safety guardrails** — prompt injection, SQL attempts, and bulk data requests are blocked
- **Streaming responses** — `/chat/stream` streams tokens for low perceived latency
- **Observability** — latency middleware, OpenAI token tracking, intent drift log, LLM fallback stats

---

## Setup

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI API key

### Install and run

```bash
git clone https://github.com/kulothungan-dataguy/grand-azure-bay-hotel-assistant.git
cd grand-azure-bay-hotel-assistant

uv venv && .venv\Scripts\activate     # Windows
# source .venv/bin/activate           # Mac/Linux

uv pip install -r requirements.txt

cp .env.example .env
# Add your OPENAI_API_KEY to .env

# Build the FAISS vector store
python -m app.rag.ingest

# Start the API
uvicorn app.api.server:app --reload --port 8000

# In a second terminal, start the UI
streamlit run frontend/app.py
```

Chat UI at `http://localhost:8501` · API docs at `http://localhost:8000/docs`

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| POST | `/chat` | Non-streaming chat |
| POST | `/chat/stream` | Streaming chat (used by UI) |
| POST | `/escalate` | Guest escalates unanswered question |
| GET | `/admin/escalations` | Staff view pending escalations |
| PATCH | `/admin/escalations/{id}/resolve` | Mark escalation resolved |
| GET | `/metrics/health` | Cache hit rate, LLM stats |
| GET | `/metrics/drift` | Intent distribution over time |

---

## Tests

```bash
pytest tests/ -v
pytest tests/test_rag_quality.py -v -s    # RAGAS evaluation
pytest tests/test_intent_accuracy.py -v -s
```

| Suite | Result |
|---|---|
| API end-to-end (9 tests) | All passing |
| RAG Faithfulness | 1.00 |
| RAG Context Recall | 1.00 |
| RAG Answer Relevancy | 0.86 |
| Intent accuracy (15 queries) | 100% |

---

## Design Decisions

**LangGraph for orchestration**
The state machine makes routing explicit and testable. Adding a new intent (e.g. `modify_reservation`) requires only a new node and edge — no changes to existing logic.

**Intent classification before tool use**
Classifying intent first, then routing, is more reliable than letting the LLM decide mid-generation whether to call a tool. It also exposes a clean `intent` field in every API response.

**Structured booking form over free-text extraction**
LLM date extraction is unreliable (e.g. "17th May" → year 1717). The frontend form uses native date pickers, eliminating this class of errors entirely.

**Email-based ownership for reservations**
View and cancel require the guest's email to match the stored reservation email. Meaningful ownership check without requiring user accounts — appropriate for the scope.

**RAG answers strictly from context**
The prompt instructs the model to answer only from retrieved context. If unavailable, it escalates to a human rather than hallucinating. RAGAS faithfulness of 1.00 confirms this.

**Human escalation for knowledge gaps**
When the bot can't answer, the guest can escalate with one click. The query is stored in SQLite and visible to hotel staff at `/admin/escalations`. This is preferable to dead-end "contact front desk" messages.

**diskcache for RAG responses**
Module-level diskcache with 24 h TTL. Repeated hotel questions (check-in time, cancellation policy) are served instantly without an LLM call.

**OpenAI primary, Groq optional fallback**
Groq (llama-3.1-8b-instant) is used as a fallback if OpenAI fails. Configurable via `GROQ_API_KEY`. Ollama removed to keep deployment simple.

---

## Assumptions

- Single hotel property — the assistant only knows Grand Azure Bay Hotel.
- No user authentication — ownership is verified by email match, not login sessions.
- In-memory session store resets on server restart. Redis or DB-backed store needed for production.
- The FAISS index is pre-built and committed. Re-run `app/rag/ingest.py` if the hotel document changes.
- SQLite is sufficient for a demo and can be swapped for PostgreSQL by changing the connection string in `app/db/database.py`.

---

## Potential Improvements

**Full multi-turn context with sliding window**
Currently only user messages are stored in chat history — the assistant's responses are not. Storing both sides and trimming to the last 6 messages (3 exchanges) would let the bot reference its own previous answers ("as I mentioned, check-in is at 2 PM"), avoid repeating questions it already asked, and handle follow-ups like "tell me more about that" correctly. Trimming to 6 messages keeps prompt tokens bounded so latency and cost don't grow unboundedly over long sessions.

**Pre-populate booking form from previous reservation**
Since the last completed booking is already in session state, the booking form could pre-fill the guest name and room type from the previous reservation. The guest only needs to change what's different (e.g. new dates). This is particularly useful for repeat guests who book the same room type regularly.

**Redis-backed session store**
RAG responses are already cached on disk (diskcache, 24 h TTL). What is not persistent is the conversation session state — the `conversation_memory` dict (chat history, current reservation progress, user email) lives in Python memory and resets on every server restart, dropping active conversations. Replacing it with Redis would make sessions survive restarts and support horizontal scaling where multiple server instances need to share the same session state.

**Room availability and pricing in knowledge base**
The bot currently cannot answer "What are the room rates?" because pricing is not in the hotel document. Adding a structured rates table to the knowledge base (or a separate `/rates` endpoint backed by a DB table) would eliminate the most common escalation trigger.

**User accounts and JWT authentication**
Ownership is currently verified by email match alone — anyone who knows a guest's email can view or cancel their reservation. A proper auth flow (registration, login, JWT tokens) would be needed before deploying to real guests.

**Modify reservation intent**
Adding a `modify_reservation` intent to change dates or room type without cancelling and rebooking. In LangGraph this would be a new node and edge — no changes to existing nodes required.

---

## Deployment (Hugging Face Spaces)

This repo auto-deploys via GitHub Actions on every push to `master`:

- `hf-backend` branch → Docker Space (FastAPI)
- `hf-frontend` branch → Streamlit Space

Secrets required in each Space: `OPENAI_API_KEY`, `DATABASE_PATH`, `LANGCHAIN_API_KEY` (optional for LangSmith tracing).
