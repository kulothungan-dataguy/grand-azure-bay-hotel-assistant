# Submission Email

---

**To:** [recruiter email]
**Subject:** Re: AI/ML Engineer Task — Hotel Reservation Assistant Submission

---

Dear Mallow Technologies Team,

Thank you for the opportunity. Please find my completed submission for the AI/ML Engineer assessment — Hotel Reservation Assistant.

**Live Demo**

| | Link |
|---|---|
| Chat UI | https://huggingface.co/spaces/Real-Kulothungan/grand-azure-bay |
| API Docs | https://real-kulothungan-grand-azure-bay-api.hf.space/docs |

**Source Code**

https://github.com/kulothungan-dataguy/grand-azure-bay-hotel-assistant

---

**Brief overview of what was built:**

- **RAG pipeline** — the hotel PDF is ingested with a heading-aware splitter (15 semantic sections), embedded with sentence-transformers, and stored in FAISS. Responses are grounded strictly in the document with a 24-hour smart cache (RAGAS faithfulness: 1.00, context recall: 1.00).

- **Reservation system** — create, view, and cancel operations backed by SQLite, with email-based ownership verification and a two-step cancel confirmation flow. Active-only filtering ensures guests only see upcoming confirmed reservations.

- **Intent routing** — a LangGraph state machine classifies each message into one of 6 intents (hotel Q&A, create/view/cancel reservation, general interaction, unsafe) before routing to the appropriate node.

- **PII handling** — guest name and email are stored only in the database and never written to logs. All view/cancel operations require email ownership verification.

- **Safety guardrails** — prompt injection, SQL injection attempts, and bulk data requests are blocked via the unsafe intent classifier.

- **Human escalation** — when the bot cannot answer, an "Ask a Human" button lets the guest escalate the query to hotel staff, stored and accessible via `/admin/escalations`.

- **Multi-turn context** — both sides of the conversation are stored with a 6-message sliding window so the bot can reference its own previous answers.

- **Test suite** — 38 tests across unit tests (cache, filters, history), API end-to-end tests, and intent accuracy evaluation (100% on 17 queries).

The README includes setup instructions, architecture overview, design decisions, and assumptions.

Please feel free to reach out if you have any questions.

Best regards,
Kulothungan
