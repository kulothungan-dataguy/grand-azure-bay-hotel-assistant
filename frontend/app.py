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

    /* Quick question buttons — sidebar (dark bg) */
    [data-testid="stSidebar"] .stButton > button {
        background: rgba(255, 255, 255, 0.12) !important;
        color: #e2e8f0 !important;
        border: 1.5px solid rgba(255, 255, 255, 0.35) !important;
        border-radius: 8px !important;
        font-size: 0.82rem !important;
        width: 100% !important;
        text-align: left !important;
        padding: 0.45rem 0.75rem !important;
        transition: all 0.15s !important;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: rgba(255, 255, 255, 0.25) !important;
        color: #ffffff !important;
    }

    /* Clear button */
    .stButton > button {
        border-radius: 8px;
        font-size: 0.82rem;
        width: 100%;
        transition: all 0.15s;
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

    /* Booking form card */
    .booking-form-card {
        background: white;
        border: 1.5px solid #cbd5e1;
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        margin-top: 0.5rem;
    }

    /* Divider */
    hr { border-color: #cbd5e1; }

    /* Blinking cursor */
    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
    .blink-cursor { animation: blink 1s step-start infinite; font-size: 1.2rem; }

    /* Latency pill */
    .latency-pill {
        display: inline-block;
        background: #f1f5f9;
        color: #64748b;
        font-size: 0.72rem;
        padding: 0.1rem 0.5rem;
        border-radius: 999px;
        margin-top: 0.25rem;
    }
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────
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
        st.session_state.show_booking_form = False
        st.session_state.cancel_res_ids = []
        st.session_state.user_email = None
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


# ── Welcome / email capture ───────────────────────────────────────────────────
if not st.session_state.user_email:
    with st.chat_message("assistant", avatar="🏨"):
        st.markdown(
            "Welcome to **Grand Azure Bay Hotel**! 🏨\n\n"
            "To help you with reservations, could you please share your **email address**? "
            "You can also ask me anything about the hotel without it."
        )
    with st.form("email_form", clear_on_submit=True):
        col1, col2 = st.columns([4, 1])
        with col1:
            email_input = st.text_input("Your email address", placeholder="you@example.com", label_visibility="collapsed")
        with col2:
            email_submitted = st.form_submit_button("Continue", type="primary")
    if email_submitted:
        try:
            from email_validator import validate_email, EmailNotValidError
            validate_email(email_input.strip(), check_deliverability=False)
            st.session_state.user_email = email_input.strip()
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Welcome! How can I assist you today? You can ask about the hotel, book a room, or manage your reservations.",
            })
            st.rerun()
        except EmailNotValidError:
            st.error("Please enter a valid email address.")
    st.stop()


# ── Chat history ──────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🏨"):
        st.markdown(msg["content"])
        if msg.get("reservation_id"):
            st.markdown(
                f'<span class="res-pill">Reservation ID: {msg["reservation_id"]}</span>',
                unsafe_allow_html=True,
            )


# ── Helpers ───────────────────────────────────────────────────────────────────
_BOOKING_TRIGGERS = ["full name", "check-in date", "check-out date", "email address"]
_ESCALATION_TRIGGERS = ["i don't have that information", "please contact our front desk", "contact our front desk"]

def _is_booking_ask(text: str) -> bool:
    lower = text.lower()
    return sum(1 for p in _BOOKING_TRIGGERS if p in lower) >= 2

def _is_cancel_query(text: str) -> bool:
    return "cancel" in text.lower()


# ── Send message ──────────────────────────────────────────────────────────────
def send(query: str):
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(query)

    with st.chat_message("assistant", avatar="🏨"):
        placeholder = st.empty()
        placeholder.markdown('<span class="blink-cursor">▋</span> *Thinking...*', unsafe_allow_html=True)
        t_start = time.time()
        reply = ""
        rid = None
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
                res.raise_for_status()
                placeholder.empty()

                def token_generator():
                    for chunk in res.iter_content(chunk_size=None):
                        if chunk:
                            yield chunk.decode("utf-8")

                reply = st.write_stream(token_generator())
                elapsed = time.time() - t_start
                st.markdown(
                    f'<span class="latency-pill">⚡ {elapsed:.1f}s</span>',
                    unsafe_allow_html=True,
                )
                _rid_match = re.search(r"Reservation ID[:\s#]+(\d+)", reply or "")
                rid = int(_rid_match.group(1)) if _rid_match else None

        except requests.exceptions.ConnectionError:
            placeholder.empty()
            reply = "Cannot reach the hotel server. Please ensure the API is running."
            st.markdown(reply)

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

    # Show booking form when bot asks for reservation details
    st.session_state.show_booking_form = _is_booking_ask(reply)

    # Show cancel buttons only when listing reservations, NOT when asking for confirmation
    is_confirmation_prompt = "are you sure you want to cancel" in (reply or "").lower()
    if _is_cancel_query(query) and "reservation" in reply.lower() and not is_confirmation_prompt:
        st.session_state.cancel_res_ids = re.findall(r"#(\d+)", reply)
    else:
        st.session_state.cancel_res_ids = []

    # Show escalation button when bot couldn't answer
    reply_lower = (reply or "").lower()
    if any(t in reply_lower for t in _ESCALATION_TRIGGERS):
        st.session_state.escalate_query = query
    else:
        st.session_state.escalate_query = None


# ── Handle pending queries (sidebar clicks) ───────────────────────────────────
if st.session_state.pending_query:
    q = st.session_state.pending_query
    st.session_state.pending_query = None
    send(q)

# ── Handle typed input — locked during active reservation flows ───────────────
_chat_locked = st.session_state.show_booking_form or bool(st.session_state.cancel_res_ids)
if user_input := st.chat_input(
    "Ask about the hotel or manage your reservation…",
    disabled=_chat_locked,
):
    send(user_input)


# ── Booking form (persists across reruns) ─────────────────────────────────────
if st.session_state.show_booking_form:
    st.markdown("---")
    st.markdown("### Complete Your Booking")
    with st.form("booking_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Full Name *")
            room_type = st.selectbox("Room Type", ["Standard", "Deluxe", "Suite"])
        with col2:
            today = date.today()
            check_in = st.date_input("Check-in Date", value=today + timedelta(days=1), min_value=today)
            check_out = st.date_input("Check-out Date", value=today + timedelta(days=2), min_value=today)
        col_confirm, col_cancel = st.columns([3, 1])
        with col_confirm:
            submitted = st.form_submit_button("Confirm Booking", type="primary", use_container_width=True)
        with col_cancel:
            cancelled = st.form_submit_button("Never mind", use_container_width=True)

    if cancelled:
        st.session_state.show_booking_form = False
        st.rerun()

    if submitted:
        errors = []
        if not name.strip():
            errors.append("Full name is required.")
        if check_out <= check_in:
            errors.append("Check-out date must be after check-in date.")
        if errors:
            for err in errors:
                st.error(err)
        else:
            st.session_state.show_booking_form = False
            st.session_state.pending_query = (
                f"Book a room for {name.strip()}, email {st.session_state.user_email}, "
                f"room type {room_type}, check-in {check_in}, check-out {check_out}"
            )
            st.rerun()


# ── Escalation button (when bot couldn't answer) ──────────────────────────────
if st.session_state.escalate_query:
    st.markdown("---")
    st.markdown("#### Need more help?")
    st.markdown("Our team can answer this question directly.")
    if st.button("📩 Ask a Human", key="escalate_btn", type="primary"):
        try:
            resp = requests.post(
                f"{API_URL}/escalate",
                json={
                    "conversation_id": st.session_state.conversation_id,
                    "query": st.session_state.escalate_query,
                    "guest_email": st.session_state.user_email,
                },
                timeout=10,
            )
            if resp.status_code == 201:
                st.success("Your question has been sent to our team. We'll get back to you shortly!")
                st.session_state.escalate_query = None
            else:
                st.error("Could not reach the hotel team. Please try again.")
        except requests.exceptions.ConnectionError:
            st.error("Cannot reach the server.")


# ── Cancel buttons (only on explicit cancel intent) ───────────────────────────
if st.session_state.cancel_res_ids:
    st.markdown("---")
    st.markdown("**Select reservation to cancel:**")
    for res_id in st.session_state.cancel_res_ids:
        col_cancel, col_keep = st.columns([3, 1])
        with col_cancel:
            if st.button(f"Cancel Reservation #{res_id}", key=f"cancel_bottom_{res_id}", use_container_width=True):
                st.session_state.cancel_res_ids = []
                st.session_state.pending_query = f"Cancel reservation {res_id}"
                st.rerun()
        with col_keep:
            if st.button("Don't cancel", key=f"keep_{res_id}", use_container_width=True):
                st.session_state.cancel_res_ids = []
                st.rerun()
