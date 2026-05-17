import streamlit as st
import requests
import uuid
import os

try:
    API_URL = st.secrets["API_URL"]
except (FileNotFoundError, KeyError):
    API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Grand Azure Bay — Hotel Assistant",
    page_icon="🏨",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* Page background */
    .stApp { background-color: #f0f4f8; }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a365d 0%, #1e4a7a 100%);
    }
    [data-testid="stSidebar"] * { color: #e2e8f0 !important; }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 { color: #ffffff !important; }

    /* Header card */
    .header-card {
        background: linear-gradient(135deg, #1a365d 0%, #2a5298 100%);
        color: white;
        padding: 1.5rem 2rem;
        border-radius: 14px;
        margin-bottom: 1.2rem;
        text-align: center;
        box-shadow: 0 4px 16px rgba(26,54,93,0.18);
    }
    .header-card h1 { font-size: 1.6rem; margin: 0; font-weight: 700; color: white; }
    .header-card p  { margin: 0.3rem 0 0; font-size: 0.9rem; color: #a8c4e0; }

    /* Accent badge */
    .badge {
        display: inline-block;
        background: #f97316;
        color: white;
        font-size: 0.72rem;
        font-weight: 700;
        padding: 0.2rem 0.6rem;
        border-radius: 999px;
        margin-bottom: 0.6rem;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }

    /* Chat input */
    [data-testid="stChatInput"] textarea {
        border: 2px solid #1a365d !important;
        border-radius: 10px !important;
    }
    [data-testid="stChatInput"] button {
        background: #f97316 !important;
        border-radius: 8px !important;
    }

    /* Quick question buttons */
    .stButton > button {
        background: white;
        color: #1a365d;
        border: 1.5px solid #1a365d;
        border-radius: 8px;
        font-size: 0.82rem;
        width: 100%;
        text-align: left;
        padding: 0.45rem 0.75rem;
        transition: all 0.15s;
    }
    .stButton > button:hover {
        background: #1a365d;
        color: white;
    }

    /* Reservation ID pill */
    .res-pill {
        display: inline-block;
        background: #dcfce7;
        color: #15803d;
        font-size: 0.78rem;
        font-weight: 600;
        padding: 0.15rem 0.6rem;
        border-radius: 999px;
        margin-top: 0.25rem;
    }

    /* Divider */
    hr { border-color: #cbd5e1; }
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_query" not in st.session_state:
    st.session_state.pending_query = None


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏨 Grand Azure Bay")
    st.markdown("*Powered by Mallow Technologies*")
    st.markdown("---")

    st.markdown("### Quick Questions")
    quick = [
        "What is the check-in time?",
        "What is the cancellation policy?",
        "Tell me about the dining options",
        "How far is the hotel from the airport?",
        "What is the signature dish?",
        "Is vegetarian food available?",
    ]
    for q in quick:
        if st.button(q, key=f"q_{q}"):
            st.session_state.pending_query = q

    st.markdown("---")
    st.markdown("### Reservation Actions")
    actions = [
        "I want to book a room",
        "View my reservation",
        "Cancel my reservation",
    ]
    for a in actions:
        if st.button(a, key=f"a_{a}"):
            st.session_state.pending_query = a

    st.markdown("---")
    if st.button("🗑 Clear conversation", key="clear"):
        st.session_state.messages = []
        st.session_state.conversation_id = str(uuid.uuid4())
        st.session_state.pending_query = None
        st.rerun()

    st.markdown(
        "<div style='margin-top:2rem;font-size:0.75rem;color:#94a3b8;'>"
        "Grand Azure Bay Hotel<br>Elysian Coast City"
        "</div>",
        unsafe_allow_html=True,
    )


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="header-card">
    <div class="badge">AI Concierge</div>
    <h1>🏨 Grand Azure Bay Hotel</h1>
    <p>Ask anything about the hotel, or let me help you manage a reservation.</p>
</div>
""", unsafe_allow_html=True)


# ── Chat history ──────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🏨"):
        st.markdown(msg["content"])
        if msg.get("reservation_id"):
            st.markdown(
                f'<span class="res-pill">Reservation ID: {msg["reservation_id"]}</span>',
                unsafe_allow_html=True,
            )


# ── Send message ──────────────────────────────────────────────────────────────
def send(query: str):
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(query)

    with st.chat_message("assistant", avatar="🏨"):
        try:
            with requests.post(
                f"{API_URL}/chat/stream",
                json={
                    "conversation_id": st.session_state.conversation_id,
                    "query": query,
                },
                stream=True,
                timeout=60,
            ) as res:
                res.raise_for_status()

                def token_generator():
                    for chunk in res.iter_content(chunk_size=None):
                        if chunk:
                            yield chunk.decode("utf-8")

                reply = st.write_stream(token_generator())
                rid = None

        except requests.exceptions.ConnectionError:
            reply = "Cannot reach the hotel server. Please ensure the API is running."
            st.markdown(reply)
            rid = None

        if rid:
            st.markdown(
                f'<span class="res-pill">Reservation ID: {rid}</span>',
                unsafe_allow_html=True,
            )

    st.session_state.messages.append({
        "role": "assistant",
        "content": reply,
        "reservation_id": rid,
    })


# Handle sidebar quick-question clicks
if st.session_state.pending_query:
    q = st.session_state.pending_query
    st.session_state.pending_query = None
    send(q)

# Handle typed input
if user_input := st.chat_input("Ask about the hotel or manage your reservation…"):
    send(user_input)
