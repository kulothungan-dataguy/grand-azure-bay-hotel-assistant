# Grand Azure Bay Hotel Assistant — Backlog

Items are grouped by theme and ordered by priority within each section.

---

## 🔴 Critical — Fix Before Production

### SEC-01 · No authentication on admin endpoints
**Files:** `app/api/server.py` (`/admin/escalations`, `/admin/cache`)  
Any guest can view all staff escalations (including other guests' queries) or wipe the RAG cache. Add API key header validation at minimum.

### ~~SEC-02 · Database connection leaks~~
**Files:** `app/db/operations.py` — all functions  
If a query throws after `get_connection()` but before `conn.close()`, the connection is never released. Replace with `try/finally` or a context manager throughout.
```python
# current (leaks on exception)
conn = get_connection()
cursor.execute(...)
conn.close()

# fix
conn = get_connection()
try:
    cursor.execute(...)
finally:
    conn.close()
```

### SEC-03 · No rate limiting on reservation lookup and cancel
**Files:** `app/tools/reservation_tools.py`  
Email + reservation ID is the only ownership check. No rate limit means brute-force enumeration of guest emails is possible. Add per-IP or per-conversation-ID rate limiting.

### ~~SEC-04 · Weak email validation in frontend~~
**Files:** `frontend/app.py:229`  
Manual `"@" in email and "." in email` check. `email-validator` is already in `requirements.txt` — use it:
```python
from email_validator import validate_email, EmailNotValidError
try:
    validate_email(email_input)
except EmailNotValidError:
    st.error("Please enter a valid email address.")
```

### ~~SEC-05 · PII sent to LLM unmasked~~
**Files:** `app/api/server.py:300`, `app/graph/nodes.py:59`  
Guest email is injected raw into the LLM system prompt. Any phone number or personal detail typed in chat goes to OpenAI/Groq unmodified. Use `presidio-analyzer` or a regex scrubber to replace PII with tokens before sending to the LLM.

---

## 🟠 High — Fix Before Scale

### ARCH-01 · In-memory session store resets on every restart
**Files:** `app/memory/store.py`  
`conversation_memory = {}` is a plain Python dict. All active conversations are lost on redeploy or crash. Replace with Redis (`redis-py`) or a lightweight SQLite-backed store for persistence across restarts.

### ARCH-02 · Session store grows unboundedly
**Files:** `app/memory/store.py`, `app/api/server.py`  
Conversations are never evicted. Under sustained load the dict grows forever. Add a TTL-based eviction (e.g. remove conversations not accessed in 24 hours) or use Redis with key expiry.

### ~~ARCH-03 · Streaming logic duplicated from graph nodes~~
**Files:** `app/api/server.py:262–317`, `app/graph/nodes.py:34–54, 216–234`  
`hotel_qa` and `general_interactions` logic is written twice — once in `nodes.py` (for non-streaming `/chat`) and again inline in `server.py` (for streaming `/chat/stream`). The duplication exists because LangGraph nodes can't `yield` mid-execution. Consolidate using `graph.astream_events()` with a node filter:
```python
async for event in graph.astream_events(state, version="v2"):
    if (event["event"] == "on_chat_model_stream"
            and event["metadata"]["langgraph_node"] in {"rag_node", "general_node"}):
        yield event["data"]["chunk"].content
```

### ~~ARCH-04 · Fragile cancellation confirmation via response text parsing~~
~~**Files:** `app/api/server.py:94–110`~~  
~~`_extract_pending_cancel` parses LLM-generated prose to detect a reservation ID for cancellation confirmation. If the bot rephrases the message the regex silently fails. Return a structured `pending_action` field in the API response instead of parsing free text.~~

### ~~ARCH-05 · `with_structured_output` bypasses fallback LLM~~
~~**Files:** `app/llm/provider.py:50`~~  
~~Intent classification and extraction calls go directly to OpenAI with no Groq fallback. If OpenAI is down, structured calls fail even though `invoke` and `astream` have fallback logic.~~

### ~~ARCH-06 · Sync fallback inside async stream breaks streaming for users~~
~~**Files:** `app/llm/provider.py:64`~~  
~~When OpenAI's `astream` fails and falls back to Groq, the entire response is returned as a single chunk instead of being streamed. Use `self.fallback_llm.astream(prompt)` instead.~~

### ~~ARCH-07 · No DB schema migration framework~~
~~**Files:** `app/db/models.py`~~  
~~Tables are created with `CREATE TABLE IF NOT EXISTS`. Any schema change (adding a column, index, constraint) has no versioning. Add Alembic for migration tracking before the schema needs to evolve.~~

---

## 🟡 Medium — Code Quality & Correctness

### ~~BUG-01 · No check-out > check-in validation on the API side~~
**Files:** `app/graph/nodes.py` (`tool_node`)  
The frontend validates that check-out > check-in, but a direct API call bypasses it. A reservation with check-out ≤ check-in can be created in the DB. Add an explicit check in `tool_node` before calling `create_reservation_tool`.

### ~~BUG-02 · Room type not validated on the API side~~
**Files:** `app/graph/nodes.py`, `app/tools/reservation_tools.py`  
Only the frontend `selectbox` constrains room type to `["Standard", "Deluxe", "Suite"]`. A direct API call can insert arbitrary strings. Add an enum check server-side.

### BUG-03 · `fallback_stats` counters are not thread-safe
**Files:** `app/llm/provider.py:15–18`  
Plain `dict[str, int]` incremented without locks. Under concurrent requests the counts can silently under-count. Use `threading.Lock` or `collections.Counter` with atomic operations, or switch to `prometheus_client` counters which are thread-safe by design.

### BUG-04 · Drift log grows forever with no rotation
**Files:** `app/api/server.py` (`_DRIFT_LOG`)  
Every request appends a JSON line to `.metrics/intent_log.jsonl`. There is no rotation or size cap. Under production load this file can grow to gigabytes. Add `logging.handlers.RotatingFileHandler` or cap to the last N entries on write.

### ~~BUG-05 · `create_reservation_tool` is a pass-through with no business value~~
**Files:** `app/tools/reservation_tools.py:20–42`  
No validation, no duplicate check, no availability logic — it just calls `operations.create_reservation()` and formats a string. Either add real business logic (duplicate detection, availability) or inline it into `operations.py` and remove the wrapper.

### ~~BUG-06 · `ingest.py` runs at module level with no error handling~~
**Files:** `app/rag/ingest.py:78–98`  
`PyPDFLoader("doc/hotel_rag_document_v2.pdf")` and `vectorstore.save_local(...)` run unconditionally on import. If the PDF is missing or the disk is full the process crashes with a raw exception. Wrap in `if __name__ == "__main__":` and add try/except with informative error messages.

### ~~PERF-01 · History trimming drops context with no summarisation~~
**Files:** `app/api/server.py` (~line 113)  
The sliding window keeps only the last 6 messages. A guest who asked about their booking 10 turns ago loses that context. Consider summarisation-based compaction: summarise old turns into a brief context string rather than discarding them.

### ~~PERF-02 · No circuit breaker for OpenAI failures~~
**Files:** `app/llm/provider.py`  
When OpenAI is down every request waits for the full HTTP timeout before falling back to Groq. A simple circuit breaker (fail-fast after N consecutive errors within a time window) would reduce latency for all users during an outage.

---

## 🔵 Low — Maintainability & Cleanup

### ~~CLEAN-01 · Dead graph nodes from the frontend's perspective~~
**Files:** `app/graph/nodes.py`, `app/graph/workflow.py`  
Since the frontend always calls `/chat/stream`, `rag_node`, `general_node`, and `intent_router_node` are never exercised by real users — only by direct `/chat` calls (tests, curl). If `/chat` is ever removed these nodes become dead code. Document this explicitly or consolidate via `astream_events` (see ARCH-03).

### CLEAN-02 · No request ID for end-to-end tracing
**Files:** `app/api/server.py`  
No `request_id` is threaded through LLM, DB, and cache calls. When a user reports a bad response there is no way to correlate the frontend log entry with the backend LLM call. Generate a UUID per request in middleware and attach it to all log entries for that request.

### ~~CLEAN-03 · Prompts scattered across multiple modules~~
**Files:** `app/rag/prompts.py`, `app/rag/intent_prompt.py`, `app/rag/extraction_prompt.py`  
Three separate files for prompts makes tuning difficult. Consolidate into a single `app/rag/prompts.py` with versioned constants (e.g. `INTENT_PROMPT_V2`) so prompt changes are easy to track and compare.

### CLEAN-04 · Magic numbers without rationale
**Files:** `app/api/server.py` (`_HISTORY_WINDOW = 6`), `app/rag/ingest.py` (chunk size)  
Add a comment explaining why each constant has its specific value so future maintainers know whether they can safely change it.

### CLEAN-05 · Incomplete type hints
**Files:** `app/db/operations.py`, `app/tools/reservation_tools.py`, `app/graph/nodes.py`  
Many function parameters use bare `dict` instead of `dict[str, Any]`. Function return types are often missing. Run `mypy --strict` and fix the gaps for better IDE support and earlier bug detection.

### CLEAN-06 · Inconsistent whitespace in `models.py` and `operations.py`
**Files:** `app/db/models.py`, `app/db/operations.py`  
Both files have excessive blank lines between statements inside functions. Apply `black` formatter across the project for consistent style.

### CLEAN-07 · Tests only cover `/chat`, not `/chat/stream`
**Files:** `tests/test_api.py`  
All tests use the non-streaming `/chat` endpoint. The streaming endpoint (`/chat/stream`) — the only path real users take — has zero test coverage. Add at minimum smoke tests that assert the stream returns non-empty content for each intent.

### CLEAN-08 · SQLite unsuitable for concurrent production load
**Files:** `app/db/database.py`  
SQLite serialises writes. Under concurrent reservation creation from multiple users, write throughput will degrade and WAL-mode issues can appear. Migrate to PostgreSQL before going to production with real traffic.

### CLEAN-09 · Docker Compose port mapping is undocumented
**Files:** `docker-compose.yml`  
`"8000:7860"` maps an external port to the internal Uvicorn port. This is valid but confusing. Add a comment or align the port numbers so it's clear which is the public-facing port.

### CLEAN-10 · `.env.example` documents Groq as primary LLM
**Files:** `.env.example`  
Comments say "Primary LLM — Groq" but `provider.py` tries OpenAI first. Update the example file to reflect the actual priority order.

---

## 💡 Features Not Yet Implemented

### ~~FEAT-01 · No duplicate booking detection~~
~~A guest can book the same room type for the same dates multiple times. Add a check in `create_reservation_tool` or `operations.py` to detect overlapping bookings for the same email.~~

### FEAT-02 · No conversation export for guests
Guests cannot download their chat history or a summary of their reservation. A `/conversation/{id}/export` endpoint returning plain text or PDF would be useful.

### FEAT-03 · No A/B testing infrastructure for prompts
Prompts are hardcoded with no mechanism to run two versions and compare intent accuracy or response quality. A simple flag in config and split logging would enable prompt experimentation.

### ~~FEAT-04 · No structured logging for LLM prompt/response pairs~~
Token counts are logged but not the actual prompts or responses. This makes debugging LLM failures (hallucinations, wrong intent, bad extraction) very difficult. Log the full prompt and response at DEBUG level with the request ID.

### ~~FEAT-05 · Replace chat input with structured UI during reservation flows~~
**Files:** `frontend/app.py`  
Currently when a guest says "I want to book a room" or "cancel my reservation", the bot asks follow-up questions through the chat input box — the guest has to type all details as free text. This is error-prone and slow.

**Booking flow:**  
When `create_reservation` intent is detected, lock the chat input box and show the booking form (the `show_booking_form` form already exists in the frontend) immediately — don't wait for the bot to ask. The form should include a **"Never mind"** button that cancels the flow and restores the chat input.

**Cancellation flow:**  
When the bot lists reservations to cancel, show a select dropdown or button group (the `cancel_res_ids` buttons already exist) instead of asking the guest to type a reservation ID. Add a **"Don't cancel"** button alongside each option so the guest can back out cleanly. After confirming or declining, hide the buttons and restore the chat input.

**After completion:**  
On successful booking or cancellation, re-enable the chat input automatically so the guest can continue the conversation without a page reload.

The building blocks (`show_booking_form`, `cancel_res_ids`) are already in the frontend — this is primarily a state management and UX wiring task, not a new feature from scratch.

---

## 📊 Metrics & Drift

### DRIFT-01 · Drift log is read entirely on every `/metrics/drift` call
**Files:** `app/api/server.py:388–389`  
Every call to `/metrics/drift` reads and parses the entire `.metrics/intent_log.jsonl` file from disk line by line. As the file grows (no rotation — see BUG-04) this gets slower with every request. Pre-aggregate counts periodically into a summary file, or keep a rolling in-memory counter and only flush to disk for persistence.

### DRIFT-02 · `metrics_health` opens the drift log file twice
**Files:** `app/api/server.py:450–452`  
```python
"drift_log_entries": sum(
    1 for _ in open(_DRIFT_LOG) if _DRIFT_LOG.exists()
) if _DRIFT_LOG.exists() else 0,
```
`_DRIFT_LOG.exists()` is checked twice (once in the `if` guard and once inside the generator condition — the inner one is always `True` and is a no-op). Also the file handle is never explicitly closed. Replace with:
```python
"drift_log_entries": sum(1 for _ in open(_DRIFT_LOG)) if _DRIFT_LOG.exists() else 0,
```

### DRIFT-03 · Drift threshold is hardcoded with no rationale
**Files:** `app/api/server.py:421`  
```python
if abs(r_pct - p_pct) > 10:   # 10 percentage points
```
The 10-point threshold is a magic number. For a low-traffic hotel bot, a 10-point swing could be statistical noise from very few requests. Move this to a config constant with a comment explaining the reasoning, and make it configurable via an environment variable so it can be tuned per deployment.

### DRIFT-04 · No alerting when drift is detected
**Files:** `app/api/server.py` (`metrics_drift`)  
`drift_alerts` is computed and returned in the API response, but nothing actively notifies anyone when drift occurs. The endpoint has to be polled manually. Add a background task or webhook call when a drift alert is generated — at minimum log it at `WARNING` level so it surfaces in log monitoring.

### DRIFT-05 · Drift comparison is only two windows — no historical trend
**Files:** `app/api/server.py:405–406`  
The drift endpoint compares `recent` vs `previous` — just two snapshots. This can't distinguish a gradual trend from a sudden spike. Store periodic snapshots (e.g. hourly aggregates) so trend direction can be observed over time.

### DRIFT-06 · Locust load test uses hardcoded shared conversation IDs
**Files:** `locustfile.py:9, 18, 27`  
```python
"conversation_id": "load-qa-1"      # all virtual users share this ID
"conversation_id": "load-create-1"
```
All virtual users write to the same conversation memory slot, so the load test is not simulating real multi-user load — it's testing one conversation being hammered. Each Locust task should generate a unique `conversation_id` per user instance:
```python
def on_start(self):
    self.conv_id = str(uuid.uuid4())
```

### DRIFT-07 · Locust only tests `/chat`, not `/chat/stream`
**Files:** `locustfile.py`  
All three Locust tasks hit the non-streaming `/chat` endpoint. The streaming endpoint is what real users hit and has a completely different code path (inline RAG, `astream`, `StreamingResponse`). Add a Locust task for `/chat/stream` using `stream=True` to measure real-world streaming latency under load.

---

## 🧪 Tests

### TEST-01 · `/chat/stream` endpoint has zero test coverage
**Files:** `tests/test_api.py`  
Every test hits `/chat`. The streaming endpoint — the only path real users take — is completely untested. Add smoke tests using `requests` with `stream=True` or FastAPI's `TestClient` streaming support to assert each intent returns non-empty streamed content.

### TEST-02 · Intent accuracy test reuses conversation IDs across queries
**Files:** `tests/test_intent_accuracy.py:43`  
```python
"conversation_id": f"intent-test-{query[:15]}"
```
Two different queries with the same first 15 characters share a conversation, meaning chat history from one query bleeds into the next. Use `uuid.uuid4()` per test case, matching the pattern in `test_api.py`.

### TEST-03 · RAGAS test has no mocking — requires live OpenAI API key
**Files:** `tests/test_rag_quality.py`  
`test_rag_quality` calls the real OpenAI API and uses real embeddings. This means it cannot run in CI without API credentials, is slow (~30s+), and costs money on every run. Mark it with `@pytest.mark.slow` or move it to a separate `tests/eval/` directory so it runs only on demand, not on every commit.

### TEST-04 · RAGAS test reuses conversation IDs across questions
**Files:** `tests/test_rag_quality.py:46`  
```python
"conversation_id": f"ragas-{case['question'][:20]}"
```
Same problem as TEST-02 — questions with similar openings share a conversation and chat history. Each evaluation sample should use a fresh `uuid.uuid4()` conversation ID.

### TEST-05 · No tests for `_is_confirmation` and `_is_denial`
**Files:** `app/api/server.py:84–90`, `tests/`  
These helpers drive the cancellation confirmation flow but have no unit tests. Edge cases like `"yes please"`, `"yeah"`, `"nope"`, `"no thanks"` are untested. A wrong match here either cancels a reservation the guest didn't want to cancel or silently ignores a confirmation. Add unit tests in `test_unit.py` covering affirmative, negative, and ambiguous inputs.

### TEST-06 · No tests for `_extract_pending_cancel`
**Files:** `app/api/server.py:94–110`, `tests/`  
`_extract_pending_cancel` parses the LLM response text to find a reservation ID for the pending cancellation flow. This regex-based parsing is fragile (see ARCH-04) and entirely untested. Add unit tests covering: ID present in response, ID absent, multiple IDs in response, malformed response.

### TEST-07 · No tests for the fallback LLM behaviour
**Files:** `app/llm/provider.py`, `tests/`  
There are no tests that simulate OpenAI failing and verify Groq is called as fallback. Add a test that mocks `primary_llm.invoke` to raise an exception and asserts the fallback response is returned and `fallback_stats["fallback_calls"]` increments.

### TEST-08 · No tests for metrics endpoints
**Files:** `tests/test_api.py`  
`/metrics/cache`, `/metrics/drift`, and `/metrics/health` are not tested beyond `test_metrics_health`. Add tests that: (a) assert cache stats update after a cache hit; (b) assert `/metrics/drift` returns `{"error": ...}` when no log exists; (c) assert `drift_alerts` is populated when intent distribution shifts.

### TEST-09 · Intent accuracy threshold has no regression tracking
**Files:** `tests/test_intent_accuracy.py:59`  
```python
assert accuracy >= 0.85
```
The 85% threshold is a floor, not a trend. If accuracy regresses from 95% to 86% across several releases, the test still passes and no one notices. Log the accuracy score as a metric to a file alongside the drift log so it can be trended over time.

### TEST-10 · Locust task weights do not reflect real traffic distribution
**Files:** `locustfile.py`  
Tasks are weighted `3:2:1` (hotel_qa : create : unsafe). In a real hotel chatbot, general interactions and view/cancel reservations are far more common than creates. Update weights to reflect realistic usage — this affects which bottlenecks surface during load testing.
