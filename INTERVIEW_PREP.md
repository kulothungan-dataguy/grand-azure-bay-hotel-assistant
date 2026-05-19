# Interview Preparation — Grand Azure Bay Hotel Assistant

---

## How to Open the Explanation (Script)

Start with the live demo, then walk through the architecture. This keeps it concrete before going deep.

---

### Opening (30 seconds)

> "I built an AI-powered hotel concierge that can answer questions about the hotel, and let guests create, view, and cancel reservations — all through natural conversation. It's live on Hugging Face if you want to try it while I explain.
>
> The core challenge was making the bot smart enough to route between two very different tasks: answering from a document versus executing a database operation. I used LangGraph to make that routing explicit and testable."

---

### Architecture Walk-through (2–3 minutes)

> "The system has three layers.
>
> **Layer 1 — the frontend** is a Streamlit app. It captures the guest's email once at the start, then sends every message to the FastAPI backend over a streaming endpoint. Tokens stream back in real time so it feels responsive.
>
> **Layer 2 — the API** is a FastAPI server. The first thing it does with every message is classify the intent using GPT-4o-mini — one of six categories: hotel Q&A, create reservation, view reservation, cancel reservation, general greeting, or unsafe. That classification happens outside the graph so I can handle streaming for the RAG and general paths directly, without going through LangGraph's sync interface.
>
> **Layer 3 — LangGraph** is the state machine. It's only invoked for reservation operations. The graph has nodes for extraction, tool execution, and rejection. Each node is a pure function that reads from state and returns a patch — which makes it easy to test in isolation."

---

### RAG Pipeline (1 minute)

> "For hotel Q&A I use RAG — Retrieval Augmented Generation. The hotel document is a 4-page PDF. I ingest it with a heading-aware splitter I wrote myself: it detects section boundaries by looking for short title-case lines with no trailing punctuation, and splits there. That gives me 15 clean semantic sections — one per heading — instead of character-count chunks that can split mid-sentence.
>
> Each section is embedded with a HuggingFace sentence-transformers model and stored in FAISS. At query time, the top 3 matching sections are retrieved and passed to the LLM with a strict prompt: answer only from the context, share what's available even if it's partial, escalate to a human if nothing relevant is found.
>
> I also cache RAG responses with a 24-hour TTL using diskcache. There are three quality guards on the cache: query normalisation before hashing so different phrasings share one entry, a cacheability check that blocks fallback responses from being stored, and automatic cache invalidation when the knowledge base is rebuilt."

---

### Reservation System (1 minute)

> "The reservation system is backed by SQLite with two tables: reservations and escalations. All three operations — create, view, cancel — verify ownership by email match. You can only view or cancel reservations belonging to your email.
>
> Cancel is a two-step confirmation flow: the bot shows you the reservation details and asks you to confirm. That's important for user experience — you don't want accidental cancellations.
>
> The booking form on the frontend uses native date pickers and dropdowns. That's a deliberate decision: LLM date parsing is unreliable — I saw it parse 'the 17th of May' as year 1717 in testing. The form eliminates that entire class of error."

---

### PII & Safety (30 seconds)

> "On PII: guest name and email are stored in SQLite but never written to logs. The structured logger only records conversation ID, intent, token counts, and latency — no personal data. The unsafe intent blocks prompt injection, SQL injection attempts, and bulk data requests like 'show all bookings in the system'."

---

### Multi-turn Context (30 seconds)

> "The bot maintains conversation context using a sliding window of the last 6 messages — 3 full exchanges. Both sides are stored: user messages and assistant replies. This lets the bot reference its own previous answers and handle follow-ups like 'tell me more about that' without re-asking questions it already answered. The window is trimmed after each turn so prompt tokens stay bounded."

---

---

## Likely Interview Questions

### Architecture & Design

**Q: Why LangGraph instead of a simple if-else router?**
> LangGraph makes the routing explicit as a directed graph — nodes, edges, and state are all visible and testable. Adding a new intent (like `modify_reservation`) requires one new node and one new edge with no changes to existing nodes. With if-else you'd be editing a growing chain. It also gives you LangSmith tracing for free.

**Q: Why classify intent before calling the graph instead of letting the LLM decide mid-generation?**
> Pre-classifying is more reliable and separates concerns cleanly. The intent is a typed field in every API response, which makes it observable and testable. With mid-generation tool selection, you can't easily write a test that asserts the bot chose the right path for a given query.

**Q: Why FastAPI + Streamlit instead of a single framework?**
> Separation of concerns. The FastAPI backend is independently deployable and testable — the test suite hits it directly without a browser. The Streamlit frontend is a thin client that only handles rendering and user input. They're also deployed independently on Hugging Face Spaces.

**Q: What would you change if this needed to handle 1000 concurrent users?**
> Three things: replace the in-memory session store with Redis so sessions survive restarts and can be shared across multiple server instances; replace SQLite with PostgreSQL; and add a connection pool. The LangGraph and RAG logic wouldn't change — they're stateless per request.

---

### RAG

**Q: Why HuggingFace embeddings instead of OpenAI embeddings?**
> Cost and latency. The sentence-transformers model runs locally with no API call, so embedding at query time adds ~0ms network latency and zero cost. The model (all-MiniLM-L6-v2) is well-proven for semantic search. RAGAS context recall came out at 1.00 so it's clearly finding the right chunks.

**Q: What is your chunk size and why?**
> We moved away from fixed chunk sizes. The current splitter is heading-aware — each of the 15 sections in the hotel document becomes one chunk, bounded naturally by the section's content (~200–350 characters). This is better than a fixed 500-character limit because a fixed size can split a section mid-sentence and separate a heading from its body text.

**Q: How do you prevent hallucination in RAG responses?**
> The prompt instructs the model to answer only from retrieved context. If the context has related but not exact information, it shares what's available and notes what's missing. Only if the context has nothing relevant does it say "I don't have that information." RAGAS faithfulness score is 1.00 — every claim in the answer is grounded in the retrieved text.

**Q: What is your RAGAS faithfulness score and what does it mean?**
> 1.00. Faithfulness measures whether every statement in the answer can be attributed to the retrieved context. A score of 1.00 means no hallucination — the bot never added information that wasn't in the document. Answer relevancy is 0.86, meaning 14% of responses contain some content not directly asked for — typically the bot adds related helpful information.

**Q: Why cache RAG responses? What are the risks?**
> The same hotel questions get asked repeatedly — check-in time, cancellation policy, famous dish. Caching those saves LLM calls and reduces latency to near-zero on the second hit. The risk is serving stale answers if the knowledge base changes — mitigated by auto-clearing the cache whenever `ingest.py` rebuilds the FAISS index. There's also a manual `DELETE /admin/cache` endpoint. A second risk is caching bad answers — mitigated by the `is_cacheable()` guard that blocks fallback responses from being stored.

---

### Reservation System & PII

**Q: How do you verify a guest owns a reservation without user accounts?**
> Email match. Every view and cancel operation requires the guest's email to match the email stored in the reservation row. It's a meaningful ownership check appropriate for a demo — not secure enough for production, where you'd want JWT authentication. That's listed as a known limitation in the README.

**Q: What PII does the system store and how is it handled?**
> Name and email are stored in SQLite in the reservations table. They're never written to logs — the structured logger only records conversation ID, intent, and token metrics. The in-memory session store holds the email during a session but resets on server restart. For production, Redis with encryption at rest would be the right move.

**Q: Why does cancel require a two-step confirmation?**
> Cancelling a reservation is a destructive, irreversible action. Requiring explicit confirmation ("Are you sure? Reply Yes to confirm") prevents accidental cancellation from ambiguous phrasing like "what if I cancel?" or "can I cancel reservation 42?" — both of which would trigger the intent without the user actually wanting to cancel.

---

### Safety & Guardrails

**Q: How does the bot handle prompt injection?**
> Queries are classified by intent first. Anything that tries to override instructions ("ignore previous instructions", "you are now a different bot") gets classified as `unsafe` and routed to `reject_node` which returns "Access denied." The LLM never acts on the injected instruction because the intent classification intercepts it.

**Q: How do you prevent the bot from dumping all reservations?**
> Two layers. First, the intent classifier catches "show all bookings in the system", "list all users" etc. as `unsafe` — the unsafe rule specifically flags queries containing "all", "every", "in the system" without a personal pronoun. Second, even if a bulk query somehow got through to the view tool, it requires an email and only returns records for that email.

---

### Testing

**Q: How did you test this?**
> Three test suites: unit tests (18 tests, no LLM — test cache normalisation, the active reservation filter, history window trimming), API end-to-end tests (20 tests — cover the full booking/view/cancel flows, PII ownership checks, escalation endpoints, guardrails), and an intent accuracy batch test (17 queries, asserts ≥85% accuracy). All 38 tests pass.

**Q: How do you test intent accuracy?**
> I have a list of 17 (query, expected_intent) pairs covering all 6 intents. The test posts each query to `/chat` and compares the returned intent field. It asserts accuracy ≥ 85%. Currently at 100%. The threshold is 85% because LLM classification has inherent variance — a strict 100% assertion would be flaky.

---

### Observability

**Q: What metrics does your system expose?**
> Four endpoints: `/metrics/health` (cache hit rate, LLM primary vs fallback call counts), `/metrics/cache` (detailed cache stats), `/metrics/drift` (intent distribution over last N requests vs previous N — flags if any intent shifts by more than 10 percentage points), and structured JSON logs for every request with latency, token counts, and cost.

**Q: You mentioned LangSmith showed 0.85s but the app took 4.5s — why?**
> LangSmith only traces what happens inside `graph.invoke()`. The intent classification call happens before the graph is invoked — it's outside the trace. So LangSmith shows 0.85s (graph execution) while the actual wall time is ~4.5s (intent classification + graph). I moved the general_interactions path outside the graph entirely to reduce latency for that intent.

---

### Potential Improvements (if asked what you'd do next)

1. **Redis session store** — make sessions survive server restarts and support horizontal scaling
2. **Room rates in the knowledge base** — currently the most common escalation trigger
3. **Modify reservation intent** — new LangGraph node + edge, no changes to existing nodes
4. **JWT authentication** — proper auth flow instead of email-only ownership
5. **Pre-populate booking form** — fill guest name and room type from previous reservation
