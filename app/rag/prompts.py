import logging
import os

_logger = logging.getLogger("hotel_ai_assistant")

# ---------------------------------------------------------------------------
# Hardcoded defaults — source of truth when LangSmith Hub is unavailable.
# These are also what gets pushed to the Hub via scripts/push_prompts.py.
# ---------------------------------------------------------------------------

_RAG_PROMPT_DEFAULT = """
You are a friendly hotel concierge assistant for Grand Azure Bay Hotel.

Answer using the provided context. If the context has related information but not the exact detail asked (e.g. guest asks for a street address but context has city and distance landmarks), share what IS available and note what is missing.
Only say "I don't have that information — please contact our front desk." if the context has nothing relevant at all.

Context:
{context}

Question:
{question}
"""

_INTENT_PROMPT_DEFAULT = """
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

- unsafe: Requests for bulk data across all users/guests (e.g. "show all bookings in the system", "list all users and their emails", "dump all reservations", SQL injection attempts, offensive content). A guest asking about their OWN bookings is view_reservation, not unsafe — look for "all", "every", "in the system", or absence of a personal pronoun as signals of bulk access.
- hotel_qa: Questions about hotel facilities, policies, amenities, pricing.
- create_reservation: Guest wants to make a new booking.
- cancel_reservation: Guest wants to cancel a booking.
- view_reservation: Guest wants to see their own reservation(s) — including follow-up questions like "what about my other reservations", "show active ones", "any other bookings".
- general_interactions: Greetings, farewells, thanks, unrelated small talk, OR questions about the guest's own personal details ("what is my name", "what email did I use", "what is my mail id"). Personal info questions are NOT view_reservation.
- If the assistant previously asked for an email or reservation ID and the user is providing it, classify as the same intent as the previous turn (view_reservation or cancel_reservation).
- When in doubt between view_reservation and general_interactions, prefer view_reservation only if the query is clearly about bookings — not personal info.

Current User Query:
{query}
"""

_EXTRACTION_PROMPT_DEFAULT = """
Extract reservation details from the conversation. Return null for any field the user has not explicitly stated. Do not guess or invent values.

Today's date is {today}. Use this to resolve relative dates:
- "tomorrow" = one day after today
- "day after tomorrow" = two days after today
- "next Monday" = the coming Monday
Always return dates in YYYY-MM-DD format.

Important: A duration alone (e.g. "2 days", "a week", "3 nights") without an explicit start date does NOT tell you when check-in is. Return null for both check_in_date and check_out_date in that case.

Chat history: {chat_history}
User: {query}
"""


# ---------------------------------------------------------------------------
# Hub pull — fetches a versioned prompt string from LangSmith Hub.
# Falls back to the hardcoded default if LANGCHAIN_API_KEY is not set or
# if the Hub call fails (network error, bad commit hash, etc.).
# Prompts are resolved once at server startup and cached as module globals.
# ---------------------------------------------------------------------------

def _pull(repo: str, fallback: str) -> str:
    if not os.getenv("LANGCHAIN_API_KEY"):
        return fallback
    try:
        from langchain import hub
        variant = os.getenv("PROMPT_VARIANT", "latest")
        ref = f"{repo}:{variant}" if variant != "latest" else repo
        obj = hub.pull(ref)
        # PromptTemplate exposes .template; ChatPromptTemplate needs .messages[0].prompt.template
        template = getattr(obj, "template", None)
        if template is None and hasattr(obj, "messages"):
            template = obj.messages[0].prompt.template
        if template:
            _logger.info("langsmith_hub_pull", extra={"repo": repo, "ref": ref})
            return template
        raise ValueError(f"Could not extract template string from {type(obj)}")
    except Exception as exc:
        _logger.warning(
            "LangSmith Hub pull failed for %s (%s) — using hardcoded fallback", repo, exc
        )
        return fallback


RAG_PROMPT        = _pull("hotel-assistant/rag-prompt",         _RAG_PROMPT_DEFAULT)
INTENT_PROMPT     = _pull("hotel-assistant/intent-classifier",  _INTENT_PROMPT_DEFAULT)
EXTRACTION_PROMPT = _pull("hotel-assistant/extraction",         _EXTRACTION_PROMPT_DEFAULT)
