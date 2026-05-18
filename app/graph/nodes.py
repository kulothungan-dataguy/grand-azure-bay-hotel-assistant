import hashlib
from app.graph.state import AssistantState
from app.llm.provider import get_llm
from app.cache.store import rag_cache as _rag_cache, make_cache_key, is_cacheable
from app.rag.retriever import retriever
from app.rag.prompts import RAG_PROMPT
from app.rag.intent_prompt import INTENT_PROMPT
from app.rag.extraction_prompt import EXTRACTION_PROMPT
from app.schemas.intent_schema import IntentOutput, ReservationIDOutput
from app.schemas.reservation_schema import ReservationData
from app.tools.reservation_tools import (
    create_reservation_tool,
    view_reservation_tool,
    cancel_reservation_tool,
)
from app.utils.logger import logger


llm = get_llm()


def intent_router_node(state: AssistantState):
    if state.get("intent"):
        return {}

    query = state["query"]
    chat_history = state.get("chat_history", [])
    prompt = INTENT_PROMPT.format(chat_history=chat_history, query=query)
    structured_llm = llm.with_structured_output(IntentOutput)
    result = structured_llm.invoke(prompt)
    return {"intent": result.intent}


def rag_node(state: AssistantState):
    query = state["query"]
    cache_key = make_cache_key(query)

    if cache_key in _rag_cache:
        logger.info(f"RAG cache hit for: {query}")
        cached = _rag_cache[cache_key]
        return {"response": cached["response"]}

    docs = retriever.invoke(query)
    context = "\n\n".join(doc.page_content for doc in docs)
    prompt = RAG_PROMPT.format(context=context, question=query)

    response = llm.invoke(prompt)

    if is_cacheable(response.content):
        _rag_cache.set(cache_key, {"response": response.content}, expire=86400)
    else:
        logger.info(f"RAG cache skip (fallback response) for: {query}")

    return {"response": response.content}


def _extract_lookup_info(query: str, chat_history: list) -> ReservationIDOutput:
    prompt = (
        f"Extract the reservation ID and email address from the user's CURRENT message only. "
        f"Ignore previous conversation history — only look at the current message.\n\n"
        f"Current user message: {query}\n\n"
        "Return the integer reservation ID only if the user explicitly states one in this message, "
        "the email if mentioned, or null for either if not found in this message."
    )
    structured_llm = llm.with_structured_output(ReservationIDOutput)
    return structured_llm.invoke(prompt)


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


def tool_node(state: AssistantState):

    intent = state["intent"]
    query = state["query"]
    chat_history = state.get("chat_history", [])

    if intent == "create_reservation":
        data = state["reservation_data"]

        ask = _missing_fields_response(data)
        if ask:
            return {"response": ask}

        result = create_reservation_tool(
            guest_name=data["guest_name"],
            email=data["email"],
            room_type=data["room_type"],
            check_in_date=data["check_in_date"],
            check_out_date=data["check_out_date"]
        )

        return {
            "response": result["message"],
            "reservation_id": result["reservation_id"]
        }

    elif intent == "view_reservation":

        lookup = _extract_lookup_info(query, chat_history)

        email = lookup.email or (
            state.get("current_reservation") or {}
        ).get("email")

        if not email:
            return {"response": "Please share your email address so I can look up your reservations."}

        result = view_reservation_tool(
            reservation_id=lookup.reservation_id,
            requester_email=email
        )

        if isinstance(result, dict) and "reservation_list" in result:
            return {
                "response": f"Here are your reservations:\n{result['summary']}",
                "reservation_list": result["reservation_list"]
            }

        response = result

    elif intent == "cancel_reservation":

        lookup = _extract_lookup_info(query, chat_history)

        email = lookup.email or (
            state.get("current_reservation") or {}
        ).get("email")

        if not email:
            return {"response": "Please share your email address so I can look up your reservations for cancellation."}

        if lookup.reservation_id is None and email:
            from app.db.operations import get_reservations_by_email
            from app.tools.reservation_tools import _is_active
            reservations = get_reservations_by_email(email)
            confirmed = [r for r in reservations if _is_active(r)]
            if not confirmed:
                return {"response": "You have no upcoming reservations to cancel."}
            if len(confirmed) == 1:
                r = confirmed[0]
                return {
                    "response": (
                        f"Here are the details for your reservation:\n\n"
                        f"**Reservation #{r['reservation_id']}**\n"
                        f"- Room: {r['room_type']}\n"
                        f"- Check-in: {r['check_in_date']}\n"
                        f"- Check-out: {r['check_out_date']}\n"
                        f"- Status: ✅ {r['status']}\n\n"
                        f"Are you sure you want to cancel this reservation? Reply **Yes** to confirm or **No** to keep it."
                    ),
                    "pending_cancel": {"reservation_id": r["reservation_id"], "email": email},
                }
            lines = []
            for r in confirmed:
                lines.append(
                    f"**Reservation #{r['reservation_id']}**\n"
                    f"- Room: {r['room_type']}\n"
                    f"- Check-in: {r['check_in_date']}\n"
                    f"- Check-out: {r['check_out_date']}\n"
                    f"- Status: ✅ {r['status']}"
                )
            return {
                "response": (
                    "Here are your reservations:\n\n" + "\n\n".join(lines) +
                    "\n\nWhich reservation would you like to cancel? Please share the Reservation ID."
                ),
                "reservation_list": confirmed,
            }

        from app.db.operations import get_reservation
        reservation = get_reservation(lookup.reservation_id)
        if not reservation:
            return {"response": "Reservation not found."}
        if reservation["email"].lower() != email.lower():
            return {"response": "Access denied. This reservation does not belong to your email."}

        return {
            "response": (
                f"Here are the details for your reservation:\n\n"
                f"**Reservation #{reservation['reservation_id']}**\n"
                f"- Room: {reservation['room_type']}\n"
                f"- Check-in: {reservation['check_in_date']}\n"
                f"- Check-out: {reservation['check_out_date']}\n"
                f"- Status: ✅ {reservation['status']}\n\n"
                f"Are you sure you want to cancel this reservation? Reply **Yes** to confirm or **No** to keep it."
            ),
            "pending_cancel": {"reservation_id": reservation["reservation_id"], "email": email},
        }

    else:

        response = "Unsupported operation"

    return {
        "response": str(response)
    }


def general_node(state: AssistantState):
    query = state["query"]
    chat_history = state.get("chat_history", [])
    prompt = (
        f"You are a friendly hotel concierge assistant for Grand Azure Bay Hotel. "
        f"Respond naturally to the guest's message.\n\n"
        f"Chat history: {chat_history}\n"
        f"Guest: {query}\nAssistant:"
    )
    response = llm.invoke(prompt)
    return {"response": response.content}


def reject_node(state: AssistantState):
    return {
        "response": "Access denied"
    }


def extract_reservation_node(state: AssistantState):
    query = state["query"]
    chat_history = state.get("chat_history", [])

    prompt = EXTRACTION_PROMPT.format(
        chat_history=chat_history,
        query=query
    )

    structured_llm = llm.with_structured_output(ReservationData)
    extracted_data = structured_llm.invoke(prompt)

    existing_reservation = state.get("current_reservation")
    new_data = extracted_data.model_dump()

    if existing_reservation:
        merged_data = {
            **existing_reservation,
            **{k: v for k, v in new_data.items() if v is not None}
        }
    else:
        merged_data = new_data

    return {
        "reservation_data": merged_data
    }