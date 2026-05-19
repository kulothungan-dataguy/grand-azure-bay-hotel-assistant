# Grand Azure Bay — Complete Codebase Walkthrough

This document follows a single user request from the moment they type in the browser to the moment they see a response. Every file, every concept, and every important line is explained along the way.

---

## Mental Model — The Big Picture

```
Browser (Streamlit)
    │  HTTP POST /chat/stream
    ▼
FastAPI Server  ──► Intent Classifier (LLM)
    │
    ├── hotel_qa          ──► RAG Pipeline ──► FAISS ──► LLM ──► Cache
    ├── create_reservation ──► LangGraph ──► Extract Node ──► Tool Node ──► SQLite
    ├── view_reservation   ──► LangGraph ──► Tool Node ──► SQLite
    ├── cancel_reservation ──► LangGraph ──► Tool Node ──► SQLite
    ├── general_interactions ──► LLM (inline, no graph)
    └── unsafe            ──► LangGraph ──► Reject Node ──► "Access denied"
```

Think of the system as a **switchboard**. Every message comes in, gets labelled with an intent, and gets routed to the right handler. The LangGraph graph is only used for reservation operations and unsafe queries — hotel questions and greetings bypass it entirely for speed.

---

## 1. Frontend — `frontend/app.py`

### What Streamlit is

Streamlit is a Python library that turns a Python script into a web app. Every time the user interacts (types, clicks a button), the **entire script reruns from top to bottom**. This is important — it means you cannot store state in regular variables. Everything that must survive a rerun lives in `st.session_state`.

### Imports and API URL

```python
import re
import streamlit as st
import requests
import uuid
import os
import time
from datetime import date, timedelta

try:
    API_URL = st.secrets["API_URL"]
except (FileNotFoundError, KeyError):
    API_URL = os.getenv("API_URL", "http://localhost:8000")
```

- `st.secrets` is Streamlit's secure config — on Hugging Face Spaces this reads from the Space's secrets tab
- Falls back to environment variable, then hardcoded localhost
- This means the same frontend code works locally and in production without changes

### Session State Initialisation

```python
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_query" not in st.session_state:
    st.session_state.pending_query = None
if "show_booking_form" not in st.session_state:
    st.session_state.show_booking_form = False
if "cancel_res_ids" not in st.session_state:
    st.session_state.cancel_res_ids = []
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "escalate_query" not in st.session_state:
    st.session_state.escalate_query = None
```

Each `if` guard runs on every page load. The `not in` check means it only initialises once — subsequent reruns skip it because the key already exists.

| Key | Purpose |
|---|---|
| `conversation_id` | A UUID that identifies this browser session to the backend |
| `messages` | Full chat history displayed on screen |
| `pending_query` | Sidebar button clicks store their query here; the main loop picks it up |
| `show_booking_form` | Whether to render the booking form below the chat |
| `cancel_res_ids` | List of reservation IDs to show cancel buttons for |
| `user_email` | Captured once at start, sent with every API request |
| `escalate_query` | The unanswered query to escalate to a human |

### Email Capture (Welcome Screen)

```python
if not st.session_state.user_email:
    with st.chat_message("assistant", avatar="🏨"):
        st.markdown("Welcome to **Grand Azure Bay Hotel**! ...")
    with st.form("email_form", clear_on_submit=True):
        col1, col2 = st.columns([4, 1])
        with col1:
            email_input = st.text_input("Your email address", ...)
        with col2:
            email_submitted = st.form_submit_button("Continue", type="primary")
    if email_submitted:
        if "@" in email_input and "." in email_input:
            st.session_state.user_email = email_input.strip()
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Welcome! How can I assist you today?...",
            })
            st.rerun()
        else:
            st.error("Please enter a valid email address.")
    st.stop()   # ← nothing below this runs until email is provided
```

`st.stop()` is key — it halts the script at that point so the chat interface never renders until email is provided. `st.rerun()` after a valid email forces the script to restart, this time with `user_email` set, so `st.stop()` is not hit and the chat loads.

No API call is made here — the welcome message is injected directly into `st.session_state.messages` as a local client-side message.

### The `send()` Function

This is the core of the frontend. It runs when the user submits a message.

```python
def send(query: str):
    # 1. Add user message to local chat history and display it
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(query)

    # 2. Show thinking indicator while waiting
    with st.chat_message("assistant", avatar="🏨"):
        placeholder = st.empty()
        placeholder.markdown('<span class="blink-cursor">▋</span> *Thinking...*',
                             unsafe_allow_html=True)
        t_start = time.time()
```

`st.empty()` creates a placeholder that can be replaced. We put the blinking cursor there, then replace it with the streamed response when it arrives.

```python
        try:
            with requests.post(
                f"{API_URL}/chat/stream",
                json={
                    "conversation_id": st.session_state.conversation_id,
                    "query": query,
                    "user_email": st.session_state.user_email,
                },
                stream=True,
                timeout=60,
            ) as res:
```

`stream=True` tells the `requests` library not to download the full response at once — it keeps the connection open and reads chunks as they arrive. This is what enables the typewriter effect.

```python
                placeholder.empty()   # remove thinking cursor

                def token_generator():
                    for chunk in res.iter_content(chunk_size=None):
                        if chunk:
                            yield chunk.decode("utf-8")

                reply = st.write_stream(token_generator())
```

`st.write_stream()` is a Streamlit function that accepts a generator and prints each yielded value to the screen as it arrives. `token_generator()` is that generator — it reads chunks from the HTTP response and yields them one by one.

```python
                elapsed = time.time() - t_start
                st.markdown(f'<span class="latency-pill">⚡ {elapsed:.1f}s</span>',
                            unsafe_allow_html=True)

                _rid_match = re.search(r"Reservation ID[:\s#]+(\d+)", reply or "")
                rid = int(_rid_match.group(1)) if _rid_match else None
```

After streaming completes, `reply` holds the full text. We use regex to extract the reservation ID from the text (e.g. "Reservation ID: 61") and show it as a green pill badge. This was added because the streaming endpoint returns plain text, not JSON — so we parse the ID from the prose.

### Post-send State Updates

```python
    # Booking form: appears when bot asks for name/dates
    st.session_state.show_booking_form = _is_booking_ask(reply)

    # Cancel buttons: only when user explicitly said "cancel"
    if _is_cancel_query(query) and "reservation" in reply.lower():
        st.session_state.cancel_res_ids = re.findall(r"#(\d+)", reply)
    else:
        st.session_state.cancel_res_ids = []

    # Escalation button: when bot couldn't answer
    reply_lower = (reply or "").lower()
    if any(t in reply_lower for t in _ESCALATION_TRIGGERS):
        st.session_state.escalate_query = query
    else:
        st.session_state.escalate_query = None
```

These flags control what appears below the chat after a response. Since Streamlit reruns the whole script after `send()` returns, these session state values persist and the corresponding UI blocks render on the next cycle.

### Booking Form

```python
if st.session_state.show_booking_form:
    with st.form("booking_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Full Name *")
            room_type = st.selectbox("Room Type", ["Standard", "Deluxe", "Suite"])
        with col2:
            today = date.today()
            check_in = st.date_input("Check-in Date", value=today + timedelta(days=1),
                                     min_value=today)
            check_out = st.date_input("Check-out Date", value=today + timedelta(days=2),
                                      min_value=today)
        submitted = st.form_submit_button("Confirm Booking", type="primary")
```

`st.form` groups inputs so they only trigger a rerun on submit, not on every keystroke. `clear_on_submit=True` resets the fields after submission.

The email field is intentionally absent — `st.session_state.user_email` is used automatically:

```python
    if submitted:
        # validation
        st.session_state.pending_query = (
            f"Book a room for {name.strip()}, email {st.session_state.user_email}, "
            f"room type {room_type}, check-in {check_in}, check-out {check_out}"
        )
        st.rerun()
```

The form constructs a well-formatted natural language query with exact ISO dates (`2026-05-19`) and puts it in `pending_query`. On `st.rerun()`, the script hits:

```python
if st.session_state.pending_query:
    q = st.session_state.pending_query
    st.session_state.pending_query = None
    send(q)
```

This picks up the pending query and calls `send()` — which sends it to the API. The API then extracts the fields from this clean structured sentence, which works reliably because the dates are already formatted.

---

## 2. API Server — `app/api/server.py`

### FastAPI Basics

FastAPI is a Python web framework. You define endpoints with decorators (`@app.post`, `@app.get`). It automatically validates request/response bodies using Pydantic schemas and generates OpenAPI docs at `/docs`.

### Module-Level Initialisation

```python
app = FastAPI()
create_tables()   # create DB tables if they don't exist
```

`create_tables()` runs once when the server starts. It creates the `reservations` and `escalations` tables in SQLite if they don't already exist (the `CREATE TABLE IF NOT EXISTS` pattern).

### Latency Middleware

```python
class LatencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info("http_request", extra={
            "path": request.url.path,
            "latency_ms": latency_ms,
        })
        return response

app.add_middleware(LatencyMiddleware)
```

Middleware wraps every request. `call_next` runs the actual endpoint handler. We measure time before and after, then log it. This gives us latency for every endpoint automatically — we don't have to add timing code to each handler.

### Memory Store

```python
# app/memory/store.py
conversation_memory = {}
```

The simplest possible session store — a Python dict. Keys are `conversation_id` strings (UUIDs from the frontend). Values are dicts containing:

```python
{
    "chat_history": [
        {"role": "user",      "content": "What time is check-in?"},
        {"role": "assistant", "content": "Check-in is at 2:00 PM."},
        # ... trimmed to last 6 messages (_HISTORY_WINDOW = 6)
    ],
    "current_reservation": None,   # partial booking data during multi-turn
    "user_email": "guest@example.com",
    "pending_cancel": None,        # set when awaiting cancel confirmation
}
```

Both the user's message and the assistant's reply are stored in `chat_history` after every turn. The helper `_append_assistant_reply(memory, text)` appends the assistant message and then trims the list to the last 6 entries (3 full exchanges) so prompt tokens stay bounded regardless of how long the conversation runs. This is called from every exit path in both `/chat` and `/chat/stream`.

This is in-memory, so it resets on server restart. For production, this would be Redis.

```python
def _get_or_init_memory(conversation_id: str) -> dict:
    if conversation_id not in conversation_memory:
        conversation_memory[conversation_id] = {
            "chat_history": [],
            "current_reservation": None,
        }
    return conversation_memory[conversation_id]
```

Called at the start of every request. Creates a new session for new conversations, returns the existing one for returning ones.

### The `/chat/stream` Endpoint — Step by Step

```python
@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    query = payload.query
    conversation_id = payload.conversation_id
    memory = _get_or_init_memory(conversation_id)
    memory["chat_history"].append({"role": "user", "content": query})
```

**Step 1:** Store the user's message in memory. After the response is generated, `_append_assistant_reply()` appends the assistant's reply and trims the list to `_HISTORY_WINDOW = 6` messages (3 full exchanges). Both sides of the conversation are stored so the intent classifier and extraction prompt have full context — the bot can reference its own previous answers.

```python
    if payload.user_email and not memory.get("user_email"):
        memory["user_email"] = payload.user_email

    current_reservation = memory.get("current_reservation") or {}
    if memory.get("user_email") and not current_reservation.get("email"):
        current_reservation = {**current_reservation, "email": memory["user_email"]}
```

**Step 2:** Persist the user's email into memory on the first request that includes it. Then inject it into `current_reservation` context so the graph nodes always have the email available — they use `current_reservation.get("email")` as the fallback when the user doesn't explicitly state their email in the current message.

```python
    intent_prompt = INTENT_PROMPT.format(
        chat_history=memory["chat_history"], query=query
    )
    intent_result = llm.with_structured_output(IntentOutput).invoke(intent_prompt)
    intent = intent_result.intent
```

**Step 3:** Classify the intent. `with_structured_output(IntentOutput)` tells the LLM to return a JSON object that matches the `IntentOutput` Pydantic schema `{"intent": "hotel_qa"}`. This guarantees we always get a valid intent string, never a freeform sentence.

```python
    if intent == "hotel_qa":
        cache_key = make_cache_key(query)
        if cache_key in _rag_cache:
            async def cached_stream():
                yield cached["response"]
            return StreamingResponse(cached_stream(), media_type="text/plain")
```

**Step 4a (hotel_qa):** Check the cache first. `make_cache_key()` normalises the query (lowercase, strip punctuation) so "What's check-in?" and "what is check in time" produce the same key. If cached, return immediately — no LLM call needed.

```python
        docs = retriever.invoke(query)
        context = "\n\n".join(doc.page_content for doc in docs)
        rag_prompt = RAG_PROMPT.format(context=context, question=query)

        async def generate():
            full_response = []
            async for chunk in llm.astream(rag_prompt):
                if chunk.content:
                    full_response.append(chunk.content)
                    yield chunk.content
            response_text = "".join(full_response)
            if is_cacheable(response_text):
                _rag_cache.set(cache_key, {"response": response_text}, expire=86400)

        return StreamingResponse(generate(), media_type="text/plain")
```

**Step 4b (hotel_qa, cache miss):** Retrieve context from FAISS, build the RAG prompt, and stream the LLM response token by token. As each token arrives, it's yielded to `StreamingResponse` which sends it to the frontend immediately. Only cache if `is_cacheable()` passes — i.e. the response is not a fallback "I don't know" message.

`StreamingResponse` with `media_type="text/plain"` keeps the HTTP connection open and flushes data as it's produced. The frontend's `requests.post(..., stream=True)` + `res.iter_content()` reads these chunks.

```python
    elif intent == "general_interactions":
        gen_prompt = (
            f"You are a friendly hotel concierge..."
            f"Chat history: {chat_history}\nGuest: {query}\nAssistant:"
        )
        async def gen_stream():
            async for chunk in llm.astream(gen_prompt):
                if chunk.content:
                    yield chunk.content
        return StreamingResponse(gen_stream(), media_type="text/plain")
```

**Step 4c (general):** Greetings, thanks, small talk — handled inline without invoking LangGraph. This avoids a second LLM call (the graph would call `general_node` which calls `llm.invoke()` again). One LLM call total instead of two.

```python
    else:
        response = graph.invoke({
            "query": query,
            "intent": intent,
            "response": None,
            "reservation_data": None,
            "reservation_id": None,
            "current_reservation": current_reservation,
            "chat_history": memory["chat_history"],
        })

        if response.get("reservation_id"):
            memory["current_reservation"] = None   # booking complete, reset
        elif response.get("reservation_data"):
            memory["current_reservation"] = response["reservation_data"]  # partial, accumulate
```

**Step 4d (reservation/unsafe):** Invoke the LangGraph graph with the full state. We pass the already-classified intent so the `intent_router_node` inside the graph skips its own classification (no double LLM call).

After the graph returns, we update `current_reservation`. If a booking was completed (`reservation_id` returned), we reset it to `None` so the next "book a room" starts fresh. If the graph returned partial data (user provided some fields but not all), we store it for the next turn.

---

## 3. LangGraph — The State Machine

### What LangGraph Is

LangGraph is a library for building stateful, multi-step LLM workflows as a directed graph. Think of it like a flowchart where:
- **Nodes** are functions that transform state
- **Edges** define which node runs next
- **State** is a typed dict that flows through the graph and gets updated by each node

### The State — `app/graph/state.py`

```python
class AssistantState(TypedDict):
    query: str                          # the user's current message
    intent: Optional[str]               # classified intent
    response: Optional[str]             # the final answer to send back
    reservation_data: Optional[dict]    # extracted booking fields
    chat_history: Optional[list]        # conversation history
    current_reservation: Optional[dict] # partial booking or last booking's context
    reservation_id: Optional[int]       # ID of a newly created reservation
    reservation_list: Optional[list]    # list of reservations (for display)
    pending_cancel: Optional[dict]      # {"reservation_id": int, "email": str}
```

`TypedDict` is a Python type hint that says "this dict must have these keys with these types". LangGraph uses it to validate state at each step. Nodes return a **partial state** — only the keys they want to update — and LangGraph merges it with the existing state.

### The Workflow — `app/graph/workflow.py`

```python
builder = StateGraph(AssistantState)

builder.add_node("intent_router", intent_router_node)
builder.add_node("rag_node", rag_node)
builder.add_node("tool_node", tool_node)
builder.add_node("general_node", general_node)
builder.add_node("reject_node", reject_node)
builder.add_node("extract_reservation", extract_reservation_node)

builder.set_entry_point("intent_router")
builder.add_conditional_edges("intent_router", route_intent)

builder.add_edge("extract_reservation", "tool_node")
builder.add_edge("general_node", END)
builder.add_edge("rag_node", END)
builder.add_edge("tool_node", END)
builder.add_edge("reject_node", END)

graph = builder.compile()
```

The graph always enters at `intent_router`. From there, `route_intent` decides where to go. Every path eventually leads to `END`. The only multi-hop path is `extract_reservation → tool_node` for booking (first extract fields, then execute the booking).

### The Router — `app/graph/router.py`

```python
def route_intent(state: AssistantState):
    intent = state["intent"]
    if intent == "hotel_qa":
        return "rag_node"
    elif intent == "create_reservation":
        return "extract_reservation"
    elif intent in ["view_reservation", "cancel_reservation"]:
        return "tool_node"
    elif intent == "general_interactions":
        return "general_node"
    else:
        return "reject_node"   # unsafe or unknown
```

This is a pure Python function — no LLM involved. It reads the `intent` field from state and returns the name of the next node as a string. LangGraph calls this after `intent_router` runs.

---

## 4. Nodes — `app/graph/nodes.py`

### `intent_router_node`

```python
def intent_router_node(state: AssistantState):
    if state.get("intent"):
        return {}   # already classified by server.py, skip
    query = state["query"]
    chat_history = state.get("chat_history", [])
    prompt = INTENT_PROMPT.format(chat_history=chat_history, query=query)
    structured_llm = llm.with_structured_output(IntentOutput)
    result = structured_llm.invoke(prompt)
    return {"intent": result.intent}
```

The `if state.get("intent"): return {}` guard is critical. The `/chat/stream` endpoint classifies intent before calling `graph.invoke()` and passes it in the state. Without this guard, the graph would classify intent again — two LLM calls for the same thing. Returning `{}` means "update nothing in the state, just pass through".

### `rag_node`

```python
def rag_node(state: AssistantState):
    query = state["query"]
    cache_key = make_cache_key(query)

    if cache_key in _rag_cache:
        cached = _rag_cache[cache_key]
        return {"response": cached["response"]}

    docs = retriever.invoke(query)
    context = "\n\n".join(doc.page_content for doc in docs)
    prompt = RAG_PROMPT.format(context=context, question=query)
    response = llm.invoke(prompt)

    if is_cacheable(response.content):
        _rag_cache.set(cache_key, {"response": response.content}, expire=86400)

    return {"response": response.content}
```

Used by the `/chat` (non-streaming) endpoint. Same logic as the streaming path but synchronous. The cache is shared between both paths — a cache hit in `/chat` will also be a hit in `/chat/stream` for the same query.

### `extract_reservation_node`

```python
def extract_reservation_node(state: AssistantState):
    query = state["query"]
    chat_history = state.get("chat_history", [])

    prompt = EXTRACTION_PROMPT.format(chat_history=chat_history, query=query)
    structured_llm = llm.with_structured_output(ReservationData)
    extracted_data = structured_llm.invoke(prompt)

    existing_reservation = state.get("current_reservation")
    new_data = extracted_data.model_dump()   # Pydantic → dict

    if existing_reservation:
        merged_data = {
            **existing_reservation,
            **{k: v for k, v in new_data.items() if v is not None}
        }
    else:
        merged_data = new_data

    return {"reservation_data": merged_data}
```

This is the multi-turn booking brain. `ReservationData` has 5 optional fields. The LLM extracts whatever the user has provided so far and returns a partial object (nulls for missing fields).

The merge logic: `{**existing_reservation, **{k: v for k, v in new_data.items() if v is not None}}` — start with what we already know, then overwrite with any newly provided non-null values. This means over multiple turns, the dict fills up field by field.

### `tool_node` — View Reservation Path

```python
elif intent == "view_reservation":
    lookup = _extract_lookup_info(query, chat_history)
    email = lookup.email or (state.get("current_reservation") or {}).get("email")

    if not email:
        return {"response": "Please share your email address..."}

    result = view_reservation_tool(reservation_id=lookup.reservation_id,
                                   requester_email=email)

    if isinstance(result, dict) and "reservation_list" in result:
        return {
            "response": f"Here are your reservations:\n{result['summary']}",
            "reservation_list": result["reservation_list"]
        }
    response = result
```

`_extract_lookup_info` looks at the **current query only** (not history) for a reservation ID. This is intentional — without this restriction, it would pick up IDs from earlier messages (e.g. "Cancel reservation 61" would pollute a subsequent "View my reservation").

The email fallback chain: current message → `current_reservation` (which the server injected with `user_email`) → ask the user.

### `_missing_fields_response` — Booking Prompt

```python
_FIELD_LABELS = {
    "guest_name":     "your full name",
    "email":          "your email address",
    "room_type":      "the room type (e.g. Standard, Deluxe, Suite)",
    "check_in_date":  "your check-in date",
    "check_out_date": "your check-out date",
}

def _missing_fields_response(data: dict) -> str | None:
    missing = [label for field, label in _FIELD_LABELS.items() if not data.get(field)]
    if not missing:
        return None
    if len(missing) == 1:
        return f"Sure! Could you also share {missing[0]} so I can complete your booking?"
    listed = ", ".join(missing[:-1]) + f" and {missing[-1]}"
    return f"I'd love to help you book a room! Could you please share {listed}?"
```

Scans the merged `reservation_data` dict for missing fields. Returns `None` when all 5 fields are present (proceed to book). Returns a human-readable question listing only what's still missing. The grammar varies: one missing field gets "Could you also share X", multiple get "Could you please share X, Y and Z".

---

## 5. Intent Classification — `app/rag/intent_prompt.py`

```python
INTENT_PROMPT = """
You are an AI hotel assistant.

Previous Conversation:
{chat_history}

Classify the CURRENT user query into ONE intent:
- hotel_qa
- create_reservation
- cancel_reservation
- view_reservation
- general_interactions
- unsafe

Rules:
- unsafe: Only for clearly harmful requests (e.g. "dump all users", SQL injection). 
  Do NOT classify follow-up reservation questions as unsafe.
- hotel_qa: Questions about hotel facilities, policies, amenities, pricing.
- ...
- When in doubt between view_reservation and general_interactions, prefer 
  view_reservation if the conversation context is about reservations.

Current User Query:
{query}
"""
```

The `{chat_history}` gives the LLM context for follow-up questions. The rule about the previous turn is important: "If the assistant previously asked for email or reservation ID and user is providing it, classify as the same intent as the previous turn." This prevents "realkulothungan@gmail.com" from being classified as `general_interactions`.

The `unsafe` rule is deliberately narrow — it only covers clearly malicious requests, not broad topics. An earlier version had "Requests asking for all reservations are unsafe" which incorrectly blocked "what about my other reservations".

---

## 6. RAG Pipeline

### Concept

RAG = Retrieval Augmented Generation. Instead of asking the LLM to answer from memory (which can hallucinate), you:
1. Convert your document into searchable chunks stored in a vector database
2. When a question arrives, find the most relevant chunks
3. Give those chunks to the LLM as context along with the question
4. The LLM answers only from the provided context

### Ingestion — `app/rag/ingest.py`

```python
loader = PyPDFLoader("doc/hotel_rag_document_v2.pdf")
documents = loader.load()

text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
chunks = text_splitter.split_documents(documents)

embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
vectorstore = FAISS.from_documents(chunks, embeddings)
vectorstore.save_local("faiss_index")

# Clear cache so stale answers don't persist after knowledge base update
from app.cache.store import rag_cache
rag_cache.clear()
```

- `chunk_size=500` — each chunk is at most 500 characters. Smaller chunks are more precise; larger chunks give more context. 500 is a common balance.
- `chunk_overlap=100` — consecutive chunks share 100 characters. This prevents a sentence that spans a boundary from being split and losing meaning.
- `sentence-transformers/all-MiniLM-L6-v2` — a 22MB HuggingFace model that converts text to 384-dimensional vectors. Free, fast, runs locally. OpenAI embeddings would be more accurate but cost money per token.
- FAISS (Facebook AI Similarity Search) — stores the vectors and supports fast nearest-neighbour lookup.

### Retriever — `app/rag/retriever.py`

```python
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
vectorstore = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
```

`k=3` means return the 3 most similar chunks. When `retriever.invoke("what is the check-in time?")` is called:
1. The query is converted to a 384-d vector using the same embedding model
2. FAISS finds the 3 stored chunk-vectors closest to it (cosine similarity)
3. Returns the original text of those chunks

`allow_dangerous_deserialization=True` is required for loading FAISS indices from disk — it's a safety flag because deserialising pickled data can be risky with untrusted files, but here we built the index ourselves.

### RAG Prompt — `app/rag/prompts.py`

```python
RAG_PROMPT = """
You are a friendly hotel concierge assistant for Grand Azure Bay Hotel.

Answer using the provided context. If the context has related information but not the 
exact detail asked (e.g. guest asks for a street address but context has city and 
distance landmarks), share what IS available and note what is missing.
Only say "I don't have that information — please contact our front desk." if the 
context has nothing relevant at all.

Context:
{context}

Question:
{question}
"""
```

The key instruction is "share what IS available" — without this, the LLM would say "I don't know" when asked for the hotel address because the document has a city name but no street number. With this instruction, it says "Our hotel is in Elysian Coast City, 5 km from the city center."

---

## 7. Smart Cache — `app/cache/store.py`

```python
rag_cache = diskcache.Cache(".rag_cache", statistics=True)

_FALLBACK_PHRASES = [
    "i don't have that information",
    "please contact our front desk",
    "i could not find that information",
]

def make_cache_key(query: str) -> str:
    normalized = re.sub(r"[^\w\s]", "", query.lower().strip())
    normalized = re.sub(r"\s+", " ", normalized)
    return hashlib.md5(normalized.encode()).hexdigest()

def is_cacheable(response: str) -> bool:
    lower = response.lower()
    return not any(phrase in lower for phrase in _FALLBACK_PHRASES)
```

Three design decisions here:

**`statistics=True`** — enables hit/miss tracking. You can call `rag_cache.stats()` to get `(hits, misses)` counts. The `/metrics/health` endpoint exposes this as a cache hit rate percentage.

**`make_cache_key()`** — normalisation before hashing means:
- "What's the check-in time?" → `whats the checkin time` → same MD5 as "what is check in time"
- Prevents duplicate cache entries for semantically identical questions

**`is_cacheable()`** — the quality guard. If the LLM couldn't answer (fallback response), we don't cache it. Next time someone asks the same question, the LLM gets another chance — maybe the retriever will find better context. A bad cached answer is permanent; an LLM call is just slow.

---

## 8. Tools — `app/tools/reservation_tools.py`

### `_is_active()`

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

A reservation is "active" only if: (1) not cancelled, AND (2) check-out is today or in the future. The try/except handles malformed dates (like the 1717 date from an earlier hallucination bug) — it returns False instead of crashing.

### `view_reservation_tool()`

```python
def view_reservation_tool(reservation_id, requester_email):
    if reservation_id is None and requester_email:
        # Email-only path: show all active reservations
        reservations = get_reservations_by_email(requester_email)
        active = [r for r in reservations if _is_active(r)]
        if not active:
            return "You have no upcoming reservations..."
        lines = [format each as markdown...]
        return {"reservation_list": active, "summary": "\n\n".join(lines)}

    # Single reservation path: ownership verified by email
    reservation = get_reservation(reservation_id)
    if not reservation:
        return "Reservation not found."
    if reservation["email"].lower() != requester_email.lower():
        return "Access denied. This reservation does not belong to your email."
    # format and return
```

Two modes: email-only (show all active) vs reservation-ID + email (show specific, verify ownership). The ownership check (`email != requester_email`) is the security boundary — without it, anyone knowing a reservation ID could view or cancel it.

---

## 9. Database — `app/db/`

### Connection — `app/db/database.py`

```python
DATABASE_NAME = os.getenv("DATABASE_PATH", "hotel.db")

def get_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn
```

`sqlite3.Row` makes query results behave like dicts — `row["email"]` instead of `row[2]`. The `DATABASE_PATH` env var allows different paths in different environments (local `hotel.db`, HF Spaces persistent storage path).

### Schema — `app/db/models.py`

```sql
CREATE TABLE IF NOT EXISTS reservations (
    reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guest_name TEXT NOT NULL,
    email TEXT NOT NULL,
    room_type TEXT NOT NULL,
    check_in_date TEXT NOT NULL,
    check_out_date TEXT NOT NULL,
    status TEXT DEFAULT 'CONFIRMED',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    guest_email TEXT,
    query TEXT NOT NULL,
    status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

Dates are stored as `TEXT` (ISO format: `2026-05-19`). This is a common SQLite pattern since SQLite has no native date type. The `_is_active()` function parses them back with `date.fromisoformat()`.

---

## 10. LLM Provider — `app/llm/provider.py`

```python
class FallbackLLM:
    def __init__(self):
        self.primary_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_tokens=1024)
        if _has_groq and os.getenv("GROQ_API_KEY"):
            self.fallback_llm = ChatGroq(model="llama-3.1-8b-instant", ...)
        else:
            self.fallback_llm = None
```

`temperature=0` means deterministic output — the model always picks the highest-probability token, no randomness. This is important for structured extraction and intent classification where you want consistent results.

`max_tokens=1024` caps response length. Without this, the `with_structured_output()` call for reservation extraction was hitting 16,384 tokens (the model's max) when something went wrong, causing a `LengthFinishReasonError`.

```python
    def with_structured_output(self, schema):
        return self.primary_llm.with_structured_output(schema)
```

`with_structured_output()` is a LangChain method that tells the LLM to respond with JSON matching a Pydantic schema. Under the hood it uses OpenAI's function-calling / response-format API. The model is forced to produce valid JSON — it cannot respond with freeform text.

```python
    async def astream(self, prompt):
        try:
            async for chunk in self.primary_llm.astream(prompt):
                yield chunk
        except Exception as e:
            if self.fallback_llm:
                result = self.fallback_llm.invoke(prompt)
                yield result
            else:
                raise
```

`astream` is the async generator version — it yields chunks as the LLM produces them. This is what powers the streaming endpoint. On failure, it falls back to a synchronous Groq call and yields the full result as one chunk (graceful degradation — no streaming but still functional).

---

## 11. Logging — `app/utils/logger.py`

```python
class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        for key, val in record.__dict__.items():
            if key not in _SKIP_KEYS and not key.startswith("_"):
                payload[key] = val
        return json.dumps(payload)
```

Every log line is a JSON object. This is the standard for production logging because JSON is machine-parseable — log aggregation tools (Datadog, CloudWatch, Grafana Loki) can query fields like `latency_ms > 3000` or `intent = "hotel_qa"`.

The `extra={}` pattern used in server.py:
```python
logger.info("intent_classified", extra={"intent": "hotel_qa", "prompt_tokens": 45})
```
→ produces:
```json
{"ts": "2026-05-18T...", "level": "INFO", "msg": "intent_classified", "intent": "hotel_qa", "prompt_tokens": 45}
```

The `_SKIP_KEYS` set filters out Python's internal `LogRecord` attributes that aren't meaningful for our purposes.

---

## 12. Escalation Flow

When the bot can't answer ("I don't have that information"):

1. **Frontend** detects the phrase in the reply, sets `st.session_state.escalate_query = query`
2. **UI** renders "Ask a Human" button
3. **User clicks** → frontend POSTs to `/escalate`:
   ```json
   {"conversation_id": "...", "query": "What are room rates?", "guest_email": "..."}
   ```
4. **Server** calls `create_escalation()` → writes to `escalations` table with `status='PENDING'`
5. **Hotel staff** hit `GET /admin/escalations` to see pending queries
6. **Staff** hit `PATCH /admin/escalations/{id}/resolve` after responding to the guest

---

## 13. End-to-End Flow: "Cancel my reservation"

To cement everything, here's a full trace of one request:

1. **Frontend** — user types "Cancel my reservation", `send("Cancel my reservation")` is called
2. **Frontend** — `requests.post("/chat/stream", json={query, conversation_id, user_email})`
3. **Server** — `_get_or_init_memory()` returns existing session (has `user_email`)
4. **Server** — injects email into `current_reservation = {"email": "guest@x.com"}`
5. **Server** — intent classification LLM call → `intent = "cancel_reservation"`
6. **Server** — not `hotel_qa` or `general_interactions` → calls `graph.invoke()`
7. **Graph** — enters `intent_router_node` → `state.get("intent")` is already set → returns `{}`
8. **Graph** — `route_intent` returns `"tool_node"` (for cancel_reservation)
9. **tool_node** — `_extract_lookup_info("Cancel my reservation", history)` → no ID in current message → `reservation_id = None`
10. **tool_node** — `email = current_reservation.get("email")` = "guest@x.com" ✓
11. **tool_node** — `reservation_id is None and email` → calls `get_reservations_by_email()`
12. **tool_node** — filters with `_is_active()` → 3 confirmed future reservations
13. **tool_node** — returns formatted list + "Which reservation would you like to cancel?"
14. **Server** — streams response back as single chunk
15. **Frontend** — `reply` contains "Here are your reservations: #61, #62, #63..."
16. **Frontend** — `_is_cancel_query("Cancel my reservation")` = True → `cancel_res_ids = [61, 62, 63]`
17. **Frontend** — on next rerun, renders "Cancel Reservation #61/62/63" buttons
18. **User clicks** "Cancel Reservation #62" → `pending_query = "Cancel reservation 62"`
19. **send("Cancel reservation 62")** → API → graph → `_extract_lookup_info` finds `reservation_id=62`
20. **tool_node** → `cancel_reservation_tool(62, "guest@x.com")` → verifies email, updates DB, returns success

---

## Key Numbers to Remember

| Thing | Value |
|---|---|
| LLM model | gpt-4o-mini |
| Embedding model | all-MiniLM-L6-v2 (22MB, local) |
| RAG chunks | 500 chars, 100 overlap |
| Retriever top-k | 3 chunks |
| Cache TTL | 24 hours |
| Max LLM tokens | 1024 |
| Session store | In-memory dict (resets on restart) |
| DB | SQLite (`hotel.db`) |
| Intents | 6: hotel_qa, create_reservation, view_reservation, cancel_reservation, general_interactions, unsafe |
