# Grand Azure Bay — Complete Codebase Walkthrough

This document is the single reference for understanding the entire codebase. Read it top to bottom once and you will understand every file, every design decision, and every alternative that was considered and rejected. It follows a real user request from browser keystroke to database write.

---

## Mental Model — The Big Picture

```
Browser (Streamlit frontend)
    │  HTTP POST /chat/stream  (streaming, text/plain)
    ▼
FastAPI Server (app/api/server.py)
    │
    ├─ RequestIdMiddleware  ─── UUID per request → ContextVar → X-Request-Id header
    ├─ LatencyMiddleware    ─── logs latency_ms for every endpoint
    │
    ├─ pending_cancel intercept  ─── yes/no short-circuits graph entirely
    │
    ├─ Intent Classifier (LLM)  ─── structured output → IntentOutput.intent
    │
    ├── hotel_qa          → build_rag_prompt() → FAISS → llm.astream() → StreamingResponse
    │                                                   ↑ checks/writes diskcache first
    ├── general_interactions → build_general_prompt() → llm.astream() → StreamingResponse
    │
    └── create/view/cancel/unsafe → graph.invoke()
              │
              ├── intent_router_node  (pass-through if intent already set)
              ├── extract_reservation_node → merges fields across turns → tool_node
              ├── tool_node           → create/view/cancel → SQLite ops
              ├── general_node        (used only by /chat non-streaming)
              ├── rag_node            (used only by /chat non-streaming)
              └── reject_node         → "Access denied"
```

**Key insight:** `hotel_qa` and `general_interactions` bypass LangGraph entirely in the streaming path. This saves one full LLM call per request (the graph's `intent_router_node` would re-classify an intent we already know). Only reservation operations and unsafe queries go through the graph.

---

## 0. Repository Layout

```
grand-azure-bay-hotel-assistant/
├── app/
│   ├── api/server.py           # FastAPI app — all HTTP endpoints
│   ├── cache/store.py          # diskcache wrapper, cache key normalisation
│   ├── db/
│   │   ├── database.py         # SQLite connection factory
│   │   ├── models.py           # Alembic programmatic upgrade (create_tables)
│   │   └── operations.py       # SQL CRUD functions — only file that touches DB
│   ├── graph/
│   │   ├── nodes.py            # All LangGraph node functions + shared helpers
│   │   ├── router.py           # route_intent() — pure Python routing function
│   │   ├── state.py            # AssistantState TypedDict definition
│   │   └── workflow.py         # Graph wiring (StateGraph compile)
│   ├── llm/
│   │   ├── config.py           # OPENAI_MODEL constant
│   │   └── provider.py         # FallbackLLM + CircuitBreaker
│   ├── memory/store.py         # Redis-backed or in-memory conversation store
│   ├── rag/
│   │   ├── ingest.py           # PDF → sections → FAISS index (run once at build)
│   │   ├── prompts.py          # All 3 prompts; LangSmith Hub pull at startup
│   │   └── retriever.py        # FAISS load + retriever object
│   ├── schemas/
│   │   ├── api_schemas.py      # ChatRequest, ChatResponse, EscalationRequest
│   │   ├── intent_schema.py    # IntentOutput, ReservationIDOutput
│   │   └── reservation_schema.py # ReservationData (5 optional fields)
│   ├── tools/reservation_tools.py  # create/view/cancel tool functions
│   └── utils/
│       ├── logger.py           # JSON logger + request_id ContextVar
│       └── pii.py              # Email/phone scrubbing before LLM calls
├── migrations/
│   ├── env.py                  # Alembic env (offline + online modes)
│   ├── script.py.mako          # Migration file template
│   └── versions/
│       └── e84fb6801694_initial_schema.py  # reservations + escalations tables
├── frontend/app.py             # Streamlit UI — entire frontend in one file
├── tests/
│   ├── test_unit.py            # Pure unit tests (mock-free where possible)
│   ├── test_stream.py          # Smoke tests against live /chat/stream endpoint
│   ├── test_api.py             # Full API integration tests
│   ├── test_intent_accuracy.py # Intent classification accuracy suite
│   └── test_rag_quality.py     # RAGAS-based RAG quality evaluation
├── scripts/push_prompts.py     # One-shot: push prompts to LangSmith Hub
├── doc/hotel_rag_document_v2.pdf  # The hotel knowledge base (source of truth for RAG)
├── faiss_index/                # Built by ingest.py at Docker build time
├── .github/workflows/
│   ├── sync-hf-spaces.yml      # master → prod HF Spaces (grand-azure-bay-api, grand-azure-bay)
│   └── sync-hf-spaces-dev.yml  # dev → staging HF Spaces (grand-azure-bay-api-dev, grand-azure-bay-dev-staging)
├── Dockerfile                  # Builds index at image build time, runs uvicorn on 7860
├── docker-compose.yml          # Local dev: api on host:8000, frontend on host:8501
├── alembic.ini                 # Alembic config (script_location = migrations)
├── requirements.txt
└── .env.example                # Template — copy to .env locally, use Space Secrets in HF
```

---

## 1. Frontend — `frontend/app.py`

### What Streamlit is

Streamlit turns a Python script into a web app. **Every user interaction reruns the entire script from top to bottom.** There are no callbacks or event handlers — Streamlit re-executes everything and React diffs the output. This means you cannot store mutable state in module-level variables. Everything that must survive a rerun lives in `st.session_state`.

### API URL Resolution

```python
try:
    API_URL = st.secrets["API_URL"]
except (FileNotFoundError, KeyError):
    API_URL = os.getenv("API_URL", "http://localhost:8000")
```

Priority order: `st.secrets` (HF Spaces secrets tab) → env var → hardcoded localhost. The same frontend code works in all three environments without modification.

**Alternative considered:** Hardcoding the backend URL. Rejected — would require separate frontend builds per environment.

### Session State Keys

```python
st.session_state.conversation_id  # UUID — identifies this browser tab to the backend
st.session_state.messages          # List of {role, content, reservation_id} dicts — drives chat display
st.session_state.user_email        # Captured once at login; sent with every API request
st.session_state.pending_query     # Sidebar button clicks queue here; consumed by main loop
st.session_state.show_booking_form # Boolean — controls whether booking form renders
st.session_state.cancel_res_ids    # List of IDs for which cancel buttons render
st.session_state.escalate_query    # The unanswered query; shows "Ask a Human" button
```

Each `if key not in st.session_state:` guard runs every rerun but only initialises on first load.

### Email Gate (`st.stop()`)

```python
if not st.session_state.user_email:
    # render email form
    st.stop()   # ← halts script execution here; nothing below runs
```

`st.stop()` is the gate. Until the user provides an email, the chat interface never renders. After valid email is submitted, `st.rerun()` restarts the script, this time clearing the gate. The welcome message is injected directly into `st.session_state.messages` (no API call) so it appears instantly.

**Why capture email at the start?** The backend uses it as the default email for all reservation operations. Without it, the bot would have to ask for email every time a user wants to view or cancel a booking.

### The `send()` Function

The core function. Runs when the user submits a message.

```python
def send(query: str):
    # 1. Append user message to local history + display it immediately
    st.session_state.messages.append({"role": "user", "content": query})

    # 2. Show blinking cursor while waiting
    placeholder = st.empty()
    placeholder.markdown('<span class="blink-cursor">▋</span> *Thinking...*', ...)

    # 3. POST to /chat/stream with stream=True
    with requests.post(f"{API_URL}/chat/stream",
        json={"conversation_id": ..., "query": query, "user_email": ...},
        stream=True, timeout=60) as res:

        placeholder.empty()   # remove cursor

        def token_generator():
            for chunk in res.iter_content(chunk_size=None):
                if chunk:
                    yield chunk.decode("utf-8")

        reply = st.write_stream(token_generator())
        # st.write_stream() prints each yielded token to the screen as it arrives
```

`requests.post(stream=True)` keeps the HTTP connection open. `res.iter_content()` reads each chunk as the server sends it. `st.write_stream()` renders them progressively — this is the typewriter effect.

After streaming, `reply` holds the full concatenated response text. It's parsed for a reservation ID using `re.search(r"Reservation ID[:\s#]+(\d+)", reply)` because the streaming endpoint returns plain text (not JSON), so the ID must be extracted from prose.

### Booking Form Trigger

```python
_BOOKING_TRIGGERS = ["full name", "check-in date", "check-out date", "email address"]

def _is_booking_ask(text: str) -> bool:
    lower = text.lower()
    return sum(1 for p in _BOOKING_TRIGGERS if p in lower) >= 1  # ← threshold = 1
```

When the bot response contains any booking-related phrase, `show_booking_form` becomes `True`. On the next Streamlit rerun, the form renders.

**Why threshold=1?** The bot asks for one or two fields at a time conversationally (e.g. "Could you share your full name?"). It never asks for all four fields in a single message. An earlier threshold of `>= 2` meant the form never appeared. Fixed to `>= 1`.

### Booking Form

```python
if st.session_state.show_booking_form:
    with st.form("booking_form", clear_on_submit=True):
        name = st.text_input("Full Name *")
        room_type = st.selectbox("Room Type", ["Standard", "Deluxe", "Suite"])
        check_in = st.date_input("Check-in Date", value=today + timedelta(days=1))
        check_out = st.date_input("Check-out Date", value=today + timedelta(days=2))
        submitted = st.form_submit_button("Confirm Booking", type="primary")
        cancelled = st.form_submit_button("Never mind")
```

`st.form` batches inputs — no rerun happens until submit is clicked. Email is intentionally absent: `st.session_state.user_email` is used automatically.

On submit, the form constructs a structured natural language query:
```python
st.session_state.pending_query = (
    f"Book a room for {name}, email {st.session_state.user_email}, "
    f"room type {room_type}, check-in {check_in}, check-out {check_out}"
)
st.rerun()
```

The explicit ISO dates (`2026-05-21`) in this string ensure the extraction LLM never has to guess dates. Unambiguous input = reliable extraction.

**Chat input hidden during booking form:**
```python
_chat_locked = st.session_state.show_booking_form or bool(st.session_state.cancel_res_ids)
if not _chat_locked:
    if user_input := st.chat_input("Ask about the hotel or manage your reservation…"):
        send(user_input)
```

The chat input is **not rendered at all** (not just disabled) when the booking form is active. `disabled=True` still shows a greyed-out box; omitting the render removes it entirely.

---

## 2. API Server — `app/api/server.py`

### Startup

```python
app = FastAPI()
create_tables()   # runs Alembic upgrade to "head" — idempotent, safe to call every startup
```

`create_tables()` calls `alembic.command.upgrade(cfg, "head")` programmatically. If the DB is already at the latest migration, it's a no-op.

### Middleware Stack

Middleware is applied in reverse registration order (last registered = outermost wrapper):

```python
app.add_middleware(LatencyMiddleware)    # registered first → runs second (inner)
app.add_middleware(RequestIdMiddleware)  # registered second → runs first (outer)
```

**RequestIdMiddleware:**
```python
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = str(uuid.uuid4())
        token = request_id_var.set(rid)      # inject into ContextVar
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = rid   # echo back to client
            return response
        finally:
            request_id_var.reset(token)      # clean up after request completes
```

`request_id_var` is a `contextvars.ContextVar` from `app/utils/logger.py`. Every log line emitted during this request reads the ContextVar and includes `request_id`. This lets you grep all logs for a single request across the entire handler chain.

**Alternative considered:** Thread-local storage. Rejected — the server is async (uvicorn + asyncio); threads don't map to requests. `contextvars` is the correct async-safe mechanism.

**LatencyMiddleware:**
```python
class LatencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info("http_request", extra={"path": ..., "latency_ms": latency_ms})
        return response
```

`time.perf_counter()` is used over `time.time()` because `perf_counter` has nanosecond resolution and is monotonic (unaffected by system clock adjustments).

### Memory Initialisation

```python
def _get_or_init_memory(conversation_id: str) -> dict:
    mem = conversation_memory.get(conversation_id)
    if mem is None:
        mem = {
            "chat_history": [],
            "history_summary": "",   # compact text of overflowed messages
            "current_reservation": None,
            "pending_cancel": None,
        }
        conversation_memory.save(conversation_id, mem)
    return mem
```

`conversation_memory` is the store from `app/memory/store.py` — either Redis or in-memory. Always call `.get()` (returns None on miss) then `.save()` after mutations. Never use `conversation_memory[cid] =` directly — Redis requires an explicit serialisation step that `.save()` handles.

### History Windowing + Summarisation

```python
_HISTORY_WINDOW = 6   # 3 full turn-pairs (user + assistant each)

def _append_assistant_reply(conversation_id: str, memory: dict, text: str) -> None:
    memory["chat_history"].append({"role": "assistant", "content": text})
    if len(memory["chat_history"]) > _HISTORY_WINDOW:
        overflow = memory["chat_history"][:-_HISTORY_WINDOW]
        compact = " | ".join(
            f"{'Guest' if m['role'] == 'user' else 'Bot'}: {m['content'][:120]}"
            for m in overflow
        )
        existing = memory.get("history_summary", "")
        memory["history_summary"] = f"{existing} | {compact}".strip(" |") if existing else compact
        memory["chat_history"] = memory["chat_history"][-_HISTORY_WINDOW:]
    conversation_memory.save(conversation_id, memory)
```

Old messages are not silently dropped. They're compressed into `history_summary` — a pipe-delimited string of 120-char excerpts. This string is prepended to the intent prompt as a system message so the LLM has long-term context even after many turns. **This function is the single save point** — every code path calls it last.

**Alternative considered:** Summarising with an LLM call. Rejected — adds latency and cost. Simple truncation to 120 chars per message is good enough for intent context.

### Cancellation Confirmation Short-Circuit

Before calling any LLM or graph, the server checks:

```python
pending = memory.get("pending_cancel")
if pending:
    if _is_confirmation(query):    # "yes", "confirm", "ok", "go ahead", etc.
        result = cancel_reservation_tool(pending["reservation_id"], pending["email"])
        memory["pending_cancel"] = None
        # stream result back
    elif _is_denial(query):        # "no", "never mind", "stop", etc.
        memory["pending_cancel"] = None
        # stream "your reservation is still active"
```

This intercepts the yes/no confirmation step **without an LLM call**. The sets `_CONFIRM` and `_DENY` cover the full vocabulary of affirmation and negation. If the query matches neither (e.g. a completely different question), the intercept is skipped and normal intent classification proceeds.

### Intent Classification

```python
summary = memory.get("history_summary", "")
history_for_prompt = (
    [{"role": "system", "content": f"Earlier conversation summary: {summary}"}]
    + memory["chat_history"]
    if summary else memory["chat_history"]
)
intent_result = llm.with_structured_output(IntentOutput).invoke(
    INTENT_PROMPT.format(chat_history=history_for_prompt, query=query)
)
intent = intent_result.intent
```

`with_structured_output(IntentOutput)` forces the LLM to return `{"intent": "<one of 6 values>"}`. This uses OpenAI's response_format / function-calling API under the hood. The model physically cannot return a freeform string — Pydantic validates the JSON and raises if the value isn't one of the 6 known intents.

### Routing After Classification

```python
if intent == "hotel_qa":
    # RAG path — streaming, no graph
elif intent == "general_interactions":
    # inline prompt — streaming, no graph
else:
    response = graph.invoke({...})   # reservation/unsafe → graph
```

`hotel_qa` and `general_interactions` use shared helper functions from `nodes.py` (`check_rag_cache`, `build_rag_prompt`, `build_general_prompt`) rather than duplicating logic. The graph path uses `graph.invoke()` which is synchronous — it runs its nodes and returns the final state dict.

### Drift Logging

```python
_DRIFT_LOG = Path(".metrics/intent_log.jsonl")

def _log_drift(intent: str, query_len: int) -> None:
    entry = json.dumps({"ts": time.time(), "intent": intent, "query_len": query_len})
    with open(_DRIFT_LOG, "a") as f:
        f.write(entry + "\n")
```

Every classified intent is appended to a JSONL file. The `/metrics/drift` endpoint reads this file, splits it into two windows (recent N vs previous N), and computes intent distribution. If any intent shifts by >10 percentage points between windows, it raises a `drift_alerts` list. This catches things like "hotel_qa dropping from 60% to 20%" which might indicate users started asking questions the bot can't answer.

---

## 3. Conversation Memory — `app/memory/store.py`

Two implementations behind the same interface:

```python
class _InMemoryStore:
    """Dict-backed. Fast, zero dependencies. Resets on server restart."""
    def get(self, cid: str) -> dict | None
    def save(self, cid: str, data: dict) -> None

class _RedisStore:
    """Redis-backed. Survives restarts. TTL-based eviction.
    Key format: hotel:conv:<conversation_id>
    Value: JSON-serialised dict
    TTL: refreshed on every write (active sessions never expire mid-flow)"""
    def get(self, cid: str) -> dict | None
    def save(self, cid: str, data: dict) -> None
```

Startup auto-detection:
```python
def _build_store():
    url = os.getenv("REDIS_URL")
    if url and _has_redis:
        try:
            store = _RedisStore(url)
            store._r.ping()    # connection test
            return store
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — falling back to in-memory", exc)
    return _InMemoryStore()

conversation_memory = _build_store()   # module-level singleton
```

**Why explicit `.save()` instead of returning a mutable dict?**
With Redis, `get()` deserialises JSON into a new dict object. Mutations to that dict don't automatically propagate back to Redis. You must explicitly call `save()`. With in-memory, mutations to the returned reference would auto-update, but we use the same `.save()` pattern for consistency. Every mutation path ends with `conversation_memory.save()`.

**TTL:** `CONV_TTL_SECONDS` env var (default 86400 = 24 hours). Refreshed on every write. A conversation that goes 24 hours without activity is automatically evicted.

**Alternative considered:** PostgreSQL session store. Rejected — adds infrastructure complexity. Redis is purpose-built for this pattern.

---

## 4. LLM Provider — `app/llm/provider.py`

### FallbackLLM

```python
class FallbackLLM:
    def __init__(self):
        self.primary_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_tokens=1024)
        self.fallback_llm = ChatGroq(model="llama-3.1-8b-instant", ...) if GROQ_API_KEY else None
```

- `temperature=0` — deterministic output. The model always picks the highest-probability token. Critical for structured extraction (same input = same output) and intent classification (no random variation).
- `max_tokens=1024` — prevents runaway responses. Without this cap, `with_structured_output()` calls were hitting the model's 16K context limit when the extraction prompt went wrong, causing `LengthFinishReasonError`.

### Circuit Breaker

```python
_FAILURE_THRESHOLD = 3    # open circuit after 3 consecutive OpenAI failures
_RECOVERY_TIMEOUT = 30    # wait 30 seconds before probing OpenAI again (HALF_OPEN)

class _CircuitBreaker:
    """Three-state: CLOSED → OPEN → HALF_OPEN → CLOSED"""
    def is_open(self) -> bool: ...       # OPEN → HALF_OPEN after timeout
    def record_success(self): ...        # resets to CLOSED, clears failures
    def record_failure(self): ...        # increments; opens circuit at threshold
```

States:
- **CLOSED** — normal. All calls go to OpenAI.
- **OPEN** — OpenAI is broken. Skip it, go straight to Groq. Check time.
- **HALF_OPEN** — timeout expired. Try OpenAI once. Success → CLOSED. Failure → OPEN again.

Without a circuit breaker, every request during an OpenAI outage would wait for a timeout before failing over to Groq, adding 10–30 seconds of latency per request.

**Alternative considered:** `tenacity` retry library. Rejected — retries add latency for the calling user. Circuit breaker fails fast and routes to a working fallback immediately.

### Fallback Patterns

```python
# Synchronous invoke — used for intent classification, extraction, structured output
def invoke(self, prompt):
    if _circuit.is_open:
        return self._use_fallback(prompt)    # immediate Groq call
    try:
        result = self.primary_llm.invoke(prompt)
        _circuit.record_success()
        return result
    except Exception:
        _circuit.record_failure()
        return self._use_fallback(prompt)   # Groq call after OpenAI failure

# Async streaming — used for RAG and general responses
async def astream(self, prompt):
    if _circuit.is_open:
        async for chunk in self._astream_fallback(prompt):
            yield chunk
        return
    try:
        async for chunk in self.primary_llm.astream(prompt):
            yield chunk
        _circuit.record_success()
    except Exception:
        _circuit.record_failure()
        async for chunk in self._astream_fallback(prompt):
            yield chunk
```

Fallback on `astream` still streams token by token from Groq — the user experience degrades to a slower model but retains the typewriter effect.

### Structured Output Fallback

```python
def with_structured_output(self, schema):
    return _FallbackStructuredOutput(
        primary=self.primary_llm.with_structured_output(schema),
        fallback=self.fallback_llm.with_structured_output(schema) if self.fallback_llm else None,
    )
```

`_FallbackStructuredOutput.invoke()` tries OpenAI first; on exception, tries Groq. Both support structured output via their respective function-calling APIs.

---

## 5. LangGraph — `app/graph/`

### What LangGraph Is

LangGraph is a library for stateful multi-step LLM workflows. Think of it as a flowchart where:
- **Nodes** are Python functions that receive state and return partial state updates
- **Edges** define which node runs next (static) or a function that decides (conditional)
- **State** is a `TypedDict` that flows through the graph, merged at each step

### State — `app/graph/state.py`

```python
class AssistantState(TypedDict):
    query: str                          # current user message
    intent: Optional[str]               # classified intent (6 values)
    response: Optional[str]             # final answer text
    reservation_data: Optional[dict]    # extracted booking fields (accumulates across turns)
    chat_history: Optional[list]        # last 6 messages
    current_reservation: Optional[dict] # partial booking or email context
    reservation_id: Optional[int]       # ID of newly created reservation
    reservation_list: Optional[list]    # list of reservations for display
    pending_cancel: Optional[dict]      # {"reservation_id": int, "email": str}
```

Nodes return **partial dicts** — only the keys they want to update. LangGraph merges the partial dict with existing state. Keys not returned by a node are unchanged.

### Workflow — `app/graph/workflow.py`

```python
builder = StateGraph(AssistantState)
builder.add_node("intent_router", intent_router_node)
builder.add_node("rag_node", rag_node)
builder.add_node("tool_node", tool_node)
builder.add_node("general_node", general_node)
builder.add_node("reject_node", reject_node)
builder.add_node("extract_reservation", extract_reservation_node)

builder.set_entry_point("intent_router")
builder.add_conditional_edges("intent_router", route_intent)  # function decides next node
builder.add_edge("extract_reservation", "tool_node")          # always → tool_node
# all other nodes → END
```

**Important note in the code:** `rag_node` and `general_node` are only exercised by the non-streaming `/chat` endpoint (used in tests and direct API calls). The streaming `/chat/stream` endpoint bypasses the graph for these intents. This means in production (all traffic goes through `/chat/stream`), `rag_node` and `general_node` are never called via the graph.

### Router — `app/graph/router.py`

```python
def route_intent(state: AssistantState):
    intent = state["intent"]
    if intent == "hotel_qa":           return "rag_node"
    elif intent == "create_reservation": return "extract_reservation"
    elif intent in ["view_reservation", "cancel_reservation"]: return "tool_node"
    elif intent == "general_interactions": return "general_node"
    else:                              return "reject_node"
```

Pure Python. No LLM. Reads the `intent` field and returns the next node name as a string.

### `intent_router_node`

```python
def intent_router_node(state: AssistantState):
    if state.get("intent"):
        return {}    # already classified by server.py — pass through, no LLM call
    # else classify (used only by /chat non-streaming endpoint)
    result = llm.with_structured_output(IntentOutput).invoke(intent_prompt)
    return {"intent": result.intent}
```

The `return {}` guard prevents double classification. The streaming endpoint classifies intent before calling `graph.invoke()` and passes it in state. This node checks for it and skips if present.

### `extract_reservation_node`

```python
def extract_reservation_node(state: AssistantState):
    existing_reservation = state.get("current_reservation")
    chat_history = state.get("chat_history", []) if existing_reservation else []
    # Only use chat history mid-booking. Fresh bookings use current message only
    # (prevents stale values from a previous completed booking leaking in)

    extracted_data = llm.with_structured_output(ReservationData).invoke(
        EXTRACTION_PROMPT.format(today=today, chat_history=chat_history, query=query)
    )
    new_data = extracted_data.model_dump()

    if existing_reservation:
        # Merge: keep old values, overwrite with new non-null values
        merged_data = {**existing_reservation, **{k: v for k, v in new_data.items() if v is not None}}
    else:
        merged_data = new_data

    return {"reservation_data": merged_data}
```

This is the multi-turn booking brain. `ReservationData` has 5 optional fields. The LLM extracts whatever the user provided in the current message (nulls for everything else). The merge logic accumulates fields across turns. Turn 1: `{name: "Kulo", ...nulls}`. Turn 2 (after form submission): `{name: "Kulo", room_type: "Deluxe", check_in: "2026-05-21", check_out: "2026-05-22", email: "k@x.com"}`.

### `tool_node` — create_reservation path

```python
def tool_node(state):
    if intent == "create_reservation":
        data = state["reservation_data"]
        ask = _missing_fields_response(data)
        if ask:
            return {"response": ask}   # asks for missing fields, exits
        # validate room type, dates
        result = create_reservation_tool(...)
        return {"response": result["message"], "reservation_id": result["reservation_id"]}
```

`_missing_fields_response()` checks all 5 required fields. Returns a natural language question listing only what's still missing. Returns `None` when all fields are present (booking proceeds).

### `tool_node` — cancel_reservation path

```python
elif intent == "cancel_reservation":
    lookup = _extract_lookup_info(query, chat_history)   # LLM extracts ID from current msg
    # ...
    if lookup.reservation_id is None and email:
        # No ID given — list all active reservations
        # If only 1: show details + "Are you sure? Yes/No"
        # If multiple: list them all + "Which ID?"
        return {"response": ..., "pending_cancel": {"reservation_id": r["reservation_id"], "email": email}}
    # ID given: verify email ownership, then ask confirmation
    return {"response": "Are you sure...", "pending_cancel": {...}}
```

Cancellation is a 2-step flow: (1) identify which reservation, (2) confirm. The `pending_cancel` dict is stored in memory by the server after the graph returns. The next message is intercepted by the server's confirmation check before any LLM is invoked.

---

## 6. Prompts — `app/rag/prompts.py`

All three prompts live here. They are resolved **once at server startup** and cached as module-level strings. No per-request overhead.

### LangSmith Hub Integration

```python
def _pull(repo: str, fallback: str) -> str:
    if not os.getenv("LANGCHAIN_API_KEY"):
        return fallback   # LangSmith not configured → use hardcoded default
    try:
        variant = os.getenv("PROMPT_VARIANT", "latest")
        ref = f"{repo}:{variant}" if variant != "latest" else repo
        obj = hub.pull(ref)
        template = getattr(obj, "template", None) or obj.messages[0].prompt.template
        return template
    except Exception:
        return fallback   # any error → fall back gracefully

RAG_PROMPT        = _pull("hotel-assistant/rag-prompt",         _RAG_PROMPT_DEFAULT)
INTENT_PROMPT     = _pull("hotel-assistant/intent-classifier",  _INTENT_PROMPT_DEFAULT)
EXTRACTION_PROMPT = _pull("hotel-assistant/extraction",         _EXTRACTION_PROMPT_DEFAULT)
```

The `PROMPT_VARIANT` env var enables A/B testing: set it to `"v2"` and the server pulls the `v2`-tagged version from LangSmith Hub. Without it, `"latest"` always gets the most recent push.

**How to push new prompt versions:**
```bash
python scripts/push_prompts.py --tag v2
```
This script pushes all 3 prompts to LangSmith Hub and optionally tags them.

**Alternative considered:** Promptfoo (offline eval CLI). Rejected — Promptfoo is for offline batch evaluation. LangSmith is for runtime tracing + prompt versioning. They serve different purposes; we chose LangSmith because it also gives us request-level observability.

### The RAG Prompt

```
You are a friendly hotel concierge assistant for Grand Azure Bay Hotel.

Answer using the provided context. If the context has related information but not the 
exact detail asked (e.g. guest asks for a street address but context has city and 
distance landmarks), share what IS available and note what is missing.
Only say "I don't have that information — please contact our front desk." if the 
context has nothing relevant at all.

Context: {context}
Question: {question}
```

Key instruction: "share what IS available." Without this, the LLM would say "I don't know" for questions where the document has partial info (e.g. city name but no street number). This instruction reduces unnecessary escalations.

### The Intent Prompt

Key rules in the prompt (the non-obvious ones):
- `unsafe` only covers bulk data requests ("dump all reservations", "list all users") or SQL injection. A guest asking about their OWN bookings is `view_reservation`, not `unsafe`.
- "If the assistant previously asked for email and the user is providing it, classify as the same intent as the previous turn." Without this rule, `"realkulothungan@gmail.com"` would be classified as `general_interactions`.
- `general_interactions` includes personal info questions ("what is my email", "what's my name") — these are NOT `view_reservation`.

### The Extraction Prompt

```
Extract reservation details. Return null for any field not explicitly stated. Do not guess.

Today's date is {today}. Use this to resolve relative dates:
- "tomorrow" = one day after today
- "next Monday" = the coming Monday

Important: A duration alone ("2 days", "a week") without an explicit start date does NOT 
tell you when check-in is. Return null for both check_in_date and check_out_date in that case.
```

The duration rule was added after observing the LLM inferring `check_in=today, check_out=today+2` from "I want to book for 2 days." This silently bypassed the missing-fields check and created a booking with incorrect dates.

---

## 7. RAG Pipeline

### Concept

RAG (Retrieval Augmented Generation): instead of asking the LLM to answer from training memory (which can hallucinate), you:
1. Convert documents into searchable vector chunks stored in FAISS
2. When a question arrives, find the most relevant chunks
3. Give those chunks to the LLM as context
4. The LLM answers only from the provided context

### Ingestion — `app/rag/ingest.py`

Run once at Docker build time (`RUN python -m app.rag.ingest` in Dockerfile). Locally, run manually after updating the PDF.

The ingestion uses a **heading-aware section splitter** instead of the standard `RecursiveCharacterTextSplitter`:
```python
_HEADING_RE = re.compile(r'^[A-Z][^\n]{3,59}$')   # 4–60 chars, starts with capital, no terminal punct

def _parse_sections(pages):
    # Splits on headings detected by regex
    # Each section = heading text + body text until next heading
    # Result: 15 semantically coherent sections
```

**Alternative considered:** `RecursiveCharacterTextSplitter(chunk_size=500, overlap=100)`. Tested but rejected — it splits mid-sentence at arbitrary character counts, breaking semantic coherence. The heading-aware splitter keeps "Dining Experience" with all its dining content in one chunk.

The embedding model is `sentence-transformers/all-MiniLM-L6-v2`:
- 22MB, runs locally, no API cost
- 384-dimensional vectors
- **Alternative considered:** `text-embedding-3-small` (OpenAI). More accurate but costs money per token and requires an API call at query time. The local model is fast enough for a 15-section knowledge base.

After rebuilding, the script also calls `rag_cache.clear()` so stale cached answers don't persist.

### Retriever — `app/rag/retriever.py`

```python
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
vectorstore = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
```

`k=3` returns the 3 most similar chunks by cosine similarity. When `retriever.invoke("what is check-in time?")` is called:
1. Query is embedded into a 384-d vector
2. FAISS finds the 3 stored vectors closest by cosine similarity
3. Returns original text of those chunks

`allow_dangerous_deserialization=True` is required for loading FAISS from disk (it uses pickle). This is safe here because the index is self-generated at build time from our own PDF, not from user input.

---

## 8. Smart Cache — `app/cache/store.py`

```python
rag_cache = diskcache.Cache(".rag_cache", statistics=True)
```

`diskcache` stores cache entries on disk. Unlike in-memory caching, it survives server restarts and is bounded in size. `statistics=True` tracks hits/misses — the `/metrics/cache` and `/metrics/health` endpoints expose these counts.

**Alternative considered:** `functools.lru_cache`. Rejected — in-memory only (resets on restart), no TTL support, no statistics.

**Alternative considered:** Redis for caching too. Rejected — overkill. diskcache is simpler and the cache data (LLM responses) is larger than session data; disk is appropriate.

```python
def make_cache_key(query: str) -> str:
    normalized = re.sub(r"[^\w\s]", "", query.lower().strip())
    normalized = re.sub(r"\s+", " ", normalized)
    return hashlib.md5(normalized.encode()).hexdigest()
```

Normalisation before hashing: strips punctuation, lowercases, collapses whitespace. "What's the check-in time?" and "what is check in time" produce the same MD5 key.

```python
_FALLBACK_PHRASES = ["i don't have that information", "please contact our front desk", ...]

def is_cacheable(response: str) -> bool:
    return not any(phrase in response.lower() for phrase in _FALLBACK_PHRASES)
```

Quality gate: never cache a fallback response. If the bot couldn't answer, the next identical question should hit the LLM again (the retriever might find better context on a fresh run, or the knowledge base may have been updated).

**Cache TTL:** 86400 seconds (24 hours), set in `save_rag_response()`.

---

## 9. Tools — `app/tools/reservation_tools.py`

### `_is_active(r: dict) -> bool`

```python
def _is_active(r: dict) -> bool:
    try:
        return (
            r["status"] == "CONFIRMED"
            and date.fromisoformat(str(r["check_out_date"])) >= date.today()
        )
    except (ValueError, TypeError):
        return False
```

A reservation is active if: (1) status is CONFIRMED (not CANCELLED), AND (2) check-out date is today or in the future. The `try/except` handles malformed date strings defensively — returns False instead of crashing the entire listing operation.

### `create_reservation_tool()`

Checks for conflicting existing reservations before inserting:
```python
existing = get_reservations_by_email(email)
for r in existing:
    if r["status"] == "CONFIRMED":
        r_in = date.fromisoformat(str(r["check_in_date"]))
        r_out = date.fromisoformat(str(r["check_out_date"]))
        if check_in < r_out and check_out > r_in:   # overlap detection
            return {"message": "You already have a reservation for those dates...", "reservation_id": None}
```

The overlap condition `check_in < r_out and check_out > r_in` is the standard interval overlap test.

### `view_reservation_tool()`

Two modes:
1. `reservation_id is None and email` — list all active reservations by email
2. `reservation_id and email` — get specific reservation, verify email ownership

Email ownership check: `reservation["email"].lower() != requester_email.lower()`. Lowercased comparison — the DB stores whatever case the user typed, so "User@Hotel.com" and "user@hotel.com" must compare equal.

---

## 10. Database — `app/db/`

### Connection — `app/db/database.py`

```python
DATABASE_NAME = os.getenv("DATABASE_PATH", "hotel.db")

def get_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row    # rows behave like dicts: row["email"] instead of row[2]
    return conn
```

`DATABASE_PATH` env var allows different paths per environment. HF Spaces uses a persistent volume mounted at a fixed path; locally it's `hotel.db` in the working directory.

Every `get_connection()` call opens a new connection. The `finally: conn.close()` pattern in every operation function ensures connections are always closed, preventing connection leaks. This is appropriate for SQLite (which serialises writes anyway); a PostgreSQL setup would use a connection pool.

### Migrations — `migrations/versions/e84fb6801694_initial_schema.py`

```python
def upgrade() -> None:
    op.create_table("reservations",
        sa.Column("reservation_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("guest_name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("room_type", sa.Text, nullable=False),
        sa.Column("check_in_date", sa.Text, nullable=False),   # ISO 8601 string
        sa.Column("check_out_date", sa.Text, nullable=False),
        sa.Column("status", sa.Text, server_default="CONFIRMED"),
        sa.Column("created_at", sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table("escalations", ...)

def downgrade() -> None:
    op.drop_table("escalations")
    op.drop_table("reservations")
```

Dates stored as `TEXT` (ISO format) because SQLite has no native date type. Alembic tracks which migrations have run in the `alembic_version` table — calling `upgrade("head")` on an already-migrated DB is a safe no-op.

**Alternative considered:** Raw `CREATE TABLE IF NOT EXISTS` in models.py. Was the original implementation. Replaced with Alembic because `IF NOT EXISTS` can't handle schema changes (adding columns, indexes) to existing tables. Alembic generates an upgrade/downgrade script for every schema change.

### Operations — `app/db/operations.py`

All SQL is parameterised with `?` placeholders — never string-interpolated. This prevents SQL injection entirely. The `LOWER(email) = LOWER(?)` in `get_reservations_by_email()` handles case-insensitive lookup at the DB level.

---

## 11. Schemas — `app/schemas/`

### `ChatRequest`

```python
class ChatRequest(BaseModel):
    conversation_id: str
    query: str
    user_email: Optional[str] = None
```

Note: `query` has no length constraints (BUG-08 in BACKLOG.md — a known gap). Should be `Field(..., min_length=1, max_length=4000)`.

### `IntentOutput`

```python
class IntentOutput(BaseModel):
    intent: str
```

Note: `intent` accepts any string (BUG-09 in BACKLOG.md). Should be `Literal["hotel_qa", "create_reservation", ...]` to reject hallucinated intent names at the Pydantic level.

### `ReservationData`

```python
class ReservationData(BaseModel):
    guest_name: Optional[str] = None
    email: Optional[str] = None
    room_type: Optional[str] = None
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None
```

All fields optional. The extraction LLM fills what it can; nulls mean "not yet provided." The merge logic in `extract_reservation_node` accumulates non-null values across turns.

---

## 12. Logging — `app/utils/logger.py`

```python
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

class _JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {"ts": ..., "level": ..., "msg": ...}
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid    # injected into every log line in this request
        for key, val in record.__dict__.items():
            if key not in _SKIP_KEYS and not key.startswith("_"):
                payload[key] = val         # any extra= fields from logger.info(...)
        return json.dumps(payload)
```

Every log line is structured JSON. Fields from `logger.info("msg", extra={"intent": "hotel_qa"})` appear as top-level keys. Production log aggregators (Datadog, CloudWatch Insights, Grafana Loki) can query on any field.

`request_id_var` is set by `RequestIdMiddleware` at the start of each request and reset in `finally`. Any code that calls `logger.*` during that request automatically gets `request_id` in its output, enabling full request tracing without passing the ID explicitly through function arguments.

---

## 13. PII Scrubbing — `app/utils/pii.py`

```python
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(r'\+?\d[\d\s\-().]{7,}\d')

def scrub_pii(text: str) -> str:
    text = _EMAIL_RE.sub('[EMAIL]', text)
    text = _PHONE_RE.sub('[PHONE]', text)
    return text
```

Applied in `build_rag_prompt()` and `build_general_prompt()` before the query is sent to the LLM. Email addresses and phone numbers are replaced with placeholders. This prevents PII from appearing in LangSmith traces and LLM provider logs.

**Not applied to:** structured output prompts (intent classification, extraction). Those prompts deliberately need the email to extract it as a field.

---

## 14. Escalation Flow

When the bot says "I don't have that information — please contact our front desk":

1. Frontend detects the phrase in `reply` → sets `st.session_state.escalate_query = query`
2. On next rerun, an "Ask a Human" button renders
3. User clicks → frontend POSTs to `POST /escalate`:
   ```json
   {"conversation_id": "...", "query": "What are the room rates?", "guest_email": "..."}
   ```
4. Server writes to `escalations` table with `status='PENDING'`
5. Hotel staff: `GET /admin/escalations` → see all pending queries
6. Staff: `PATCH /admin/escalations/{id}/resolve` → sets `status='RESOLVED'`

**Known gap (FEAT-06 in BACKLOG.md):** No staff notification (email/webhook) on escalation creation. An escalation can sit unread indefinitely. The admin endpoint requires staff to poll manually.

---

## 15. CI/CD & Deployment

### Branches and Environments

| Branch | Purpose | HF Space |
|---|---|---|
| `master` | Production | `grand-azure-bay-api` (backend), `grand-azure-bay` (frontend) |
| `dev` | Development/staging | `grand-azure-bay-api-dev` (backend), `grand-azure-bay-dev-staging` (frontend) |
| `hf-backend` | Production backend sync branch | — |
| `hf-frontend` | Production frontend sync branch | — |
| `hf-backend-dev` | Dev backend sync branch | — |
| `hf-frontend-dev` | Dev frontend sync branch | — |

### Sync Workflow Pattern (both `sync-hf-spaces.yml` and `sync-hf-spaces-dev.yml`)

```yaml
- name: Merge master/dev into hf-backend/hf-backend-dev and push to HF
  run: |
    git fetch origin
    git checkout hf-backend-dev
    git merge origin/dev --no-edit -X ours     # our changes win on conflict
    git push origin hf-backend-dev             # update GitHub branch
    git remote add hf https://...:${{ secrets.HF_TOKEN }}@huggingface.co/spaces/...
    git push hf hf-backend-dev:main --force    # push to HF Space's main branch
```

The `hf-backend` / `hf-backend-dev` branches exist as staging areas. HF Spaces deploy from their `main` branch. We force-push our sync branch to HF's `main`.

`-X ours` on merge means "if there's a merge conflict, our (sync branch) version wins." This prevents HF-side auto-generated files from blocking the merge.

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python -m app.rag.ingest    # builds faiss_index/ at image build time
EXPOSE 7860
CMD ["uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "7860"]
```

The FAISS index is built during `docker build`, not at startup. This keeps startup time short (no embedding model download at boot). The index is baked into the image.

**Port:** 7860 is the HF Spaces convention. `docker-compose.yml` maps `8000:7860` so `http://localhost:8000` works locally.

**Known gap (SEC-07 in BACKLOG.md):** No `USER` directive — container runs as root.

### Environment Variables

| Variable | Where set | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | HF Space Secret / `.env` | Primary LLM |
| `GROQ_API_KEY` | HF Space Secret / `.env` | Fallback LLM |
| `REDIS_URL` | HF Space Variable / `.env` | Session store (in-memory if unset) |
| `CONV_TTL_SECONDS` | Optional | Redis TTL (default 86400) |
| `LANGCHAIN_API_KEY` | HF Space Secret / `.env` | Enables LangSmith tracing + Hub pull |
| `LANGCHAIN_TRACING_V2` | `.env.example` | Must be `true` alongside API key |
| `PROMPT_VARIANT` | HF Space Variable / `.env` | Hub version tag (default: `latest`) |
| `LOG_LEVEL` | Optional | `DEBUG`/`INFO`/`WARNING`/`ERROR` |
| `DATABASE_PATH` | HF Space Variable | SQLite file path (persistent volume) |
| `API_URL` | Frontend HF Space Secret | Backend URL for the Streamlit app |

---

## 16. End-to-End Trace: "I want to book a Deluxe room"

1. User types in browser → `send("I want to book a Deluxe room")` in `frontend/app.py`
2. Frontend POSTs to `/chat/stream` with `{conversation_id, query, user_email}`
3. **Server:** `_get_or_init_memory()` returns/creates session dict
4. **Server:** user message appended to `chat_history`
5. **Server:** `user_email` from payload stored in `memory["user_email"]`; injected into `current_reservation`
6. **Server:** no `pending_cancel` → skip confirmation intercept
7. **Server:** intent classification LLM call → `intent = "create_reservation"`
8. **Server:** not `hotel_qa` or `general_interactions` → `graph.invoke({..., intent: "create_reservation", ...})`
9. **Graph:** `intent_router_node` → `state.get("intent")` is set → `return {}` (no LLM call)
10. **Graph:** `route_intent` → `"extract_reservation"`
11. **Graph:** `extract_reservation_node` → no existing reservation → LLM extracts from current message only
    - LLM output: `{guest_name: null, email: null, room_type: "Deluxe", check_in_date: null, check_out_date: null}`
    - `email` injected from `current_reservation`: `{..., email: "guest@x.com"}`
12. **Graph:** `tool_node` → `_missing_fields_response({room_type: "Deluxe", email: "guest@x.com"})` → missing: `guest_name, check_in_date, check_out_date` → returns "Could you please share your full name, check-in date and check-out date?"
13. **Server:** `current_reservation` updated with partial data: `{room_type: "Deluxe", email: "guest@x.com"}`
14. **Server:** `_append_assistant_reply()` → saves to Redis/memory
15. **Server:** `StreamingResponse` yields the ask string
16. **Frontend:** `_is_booking_ask("could you please share your full name")` → "full name" in text → `show_booking_form = True`
17. **Frontend:** booking form renders (name input, room type dropdown pre-selectable, date pickers)
18. User fills form: name="Kulothungan", room_type="Deluxe", check_in="2026-05-25", check_out="2026-05-27"
19. Form submit → `pending_query = "Book a room for Kulothungan, email guest@x.com, room type Deluxe, check-in 2026-05-25, check-out 2026-05-27"`
20. `st.rerun()` → `send(pending_query)`
21. **Server:** same flow → extraction → all 5 fields present → `create_reservation_tool(...)` → DB insert → `reservation_id = 7`
22. **Frontend:** reply contains "Reservation ID: 7" → regex extracts `7` → green pill rendered

---

## 17. Key Numbers and Constants

| Thing | Value | Where |
|---|---|---|
| Primary LLM | `gpt-4o-mini` | `app/llm/config.py` → `OPENAI_MODEL` |
| Fallback LLM | `llama-3.1-8b-instant` (Groq) | `app/llm/provider.py` |
| `temperature` | `0` (deterministic) | `app/llm/provider.py` |
| `max_tokens` | `1024` | `app/llm/provider.py` |
| Embedding model | `all-MiniLM-L6-v2` (22MB, local) | `app/rag/retriever.py`, `app/rag/ingest.py` |
| Vector dimensions | 384 | (model property) |
| RAG top-k | 3 chunks | `app/rag/retriever.py` |
| Cache TTL | 86400s (24 hours) | `app/graph/nodes.py:save_rag_response` |
| Session TTL | 86400s (24 hours) | `app/memory/store.py:_CONV_TTL` |
| History window | 6 messages (3 turn-pairs) | `app/api/server.py:_HISTORY_WINDOW` |
| Circuit breaker threshold | 3 failures | `app/llm/provider.py:_FAILURE_THRESHOLD` |
| Circuit recovery timeout | 30 seconds | `app/llm/provider.py:_RECOVERY_TIMEOUT` |
| Server port | 7860 (container) / 8000 (host) | `Dockerfile` / `docker-compose.yml` |
| Frontend port | 8501 | `docker-compose.yml` |
| Intents | 6: hotel_qa, create_reservation, view_reservation, cancel_reservation, general_interactions, unsafe | `app/rag/prompts.py` |
| Valid room types | Standard, Deluxe, Suite | `app/graph/nodes.py:_VALID_ROOM_TYPES` |
| DB | SQLite (`hotel.db` or `DATABASE_PATH`) | `app/db/database.py` |
| Drift alert threshold | 10 percentage-point shift | `app/api/server.py:metrics_drift` |
