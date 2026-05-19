import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from langchain_community.callbacks import get_openai_callback

from app.graph.workflow import graph
from app.graph.nodes import llm, check_rag_cache, build_rag_prompt, save_rag_response, build_general_prompt
from app.rag.prompts import INTENT_PROMPT
from app.schemas.intent_schema import IntentOutput
from app.db.models import create_tables
from app.db.operations import create_escalation, get_pending_escalations, resolve_escalation
from app.utils.logger import logger, request_id_var
from app.schemas.api_schemas import ChatRequest, ChatResponse, EscalationRequest
from app.memory.store import conversation_memory
from app.cache.store import rag_cache as _rag_cache
from app.llm.provider import fallback_stats

_DRIFT_LOG = Path(".metrics/intent_log.jsonl")
_DRIFT_LOG.parent.mkdir(exist_ok=True)

app = FastAPI()
create_tables()


@app.get("/")
def root():
    return {"status": "ok", "service": "Grand Azure Bay Hotel API", "docs": "/docs"}


# ---------------------------------------------------------------------------
# Middleware — applied in reverse registration order (last registered = outermost)
# ---------------------------------------------------------------------------

class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generates a UUID per request, sets it in a ContextVar so every log line
    emitted during that request carries the same request_id, and echoes it back
    in the X-Request-Id response header for client-side correlation."""

    async def dispatch(self, request: Request, call_next):
        rid = str(uuid.uuid4())
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = rid
            return response
        finally:
            request_id_var.reset(token)


class LatencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "http_request",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        return response


app.add_middleware(LatencyMiddleware)
app.add_middleware(RequestIdMiddleware)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_init_memory(conversation_id: str) -> dict:
    mem = conversation_memory.get(conversation_id)
    if mem is None:
        mem = {
            "chat_history": [],
            "history_summary": "",   # compact text of messages trimmed from the window
            "current_reservation": None,
            "pending_cancel": None,
        }
        conversation_memory.save(conversation_id, mem)
    return mem


# Keep the last 3 full turn-pairs (user + assistant) in the active window.
# Older messages are summarised into history_summary rather than discarded.
_HISTORY_WINDOW = 6

_CONFIRM = {"yes", "yeah", "yep", "sure", "confirm", "confirmed", "ok", "okay", "proceed", "do it", "go ahead", "yes please"}
_DENY    = {"no", "nope", "don't", "dont", "stop", "abort", "never mind", "nevermind", "keep it", "cancel that"}


def _is_confirmation(query: str) -> bool:
    q = query.lower().strip().rstrip(".")
    return q in _CONFIRM or any(w in q for w in ["yes", "confirm", "proceed", "sure", "go ahead"])


def _is_denial(query: str) -> bool:
    q = query.lower().strip()
    return q in _DENY or any(w in q for w in ["no", "don't", "abort", "never mind", "stop", "keep"])


def _extract_pending_cancel(response: dict) -> dict | None:
    """Read pending_cancel from the graph's structured state output."""
    return response.get("pending_cancel") or None


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


def _log_drift(intent: str, query_len: int) -> None:
    entry = json.dumps({"ts": time.time(), "intent": intent, "query_len": query_len})
    with open(_DRIFT_LOG, "a") as f:
        f.write(entry + "\n")


# ---------------------------------------------------------------------------
# /chat  (non-streaming)
# ---------------------------------------------------------------------------

@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    query = payload.query
    conversation_id = payload.conversation_id

    memory = _get_or_init_memory(conversation_id)
    memory["chat_history"].append({"role": "user", "content": query})

    logger.info(
        "conversation_turn",
        extra={
            "conversation_id": conversation_id,
            "turns": len(memory["chat_history"]),
        },
    )

    # Intercept cancellation confirmation before invoking the graph
    pending = memory.get("pending_cancel")
    if pending:
        if _is_confirmation(query):
            from app.tools.reservation_tools import cancel_reservation_tool
            result = cancel_reservation_tool(pending["reservation_id"], pending["email"])
            memory["pending_cancel"] = None
            _log_drift("cancel_reservation", len(query))
            _append_assistant_reply(conversation_id, memory, str(result))
            return ChatResponse(response=str(result), intent="cancel_reservation")
        elif _is_denial(query):
            memory["pending_cancel"] = None
            _log_drift("cancel_reservation", len(query))
            reply = "No problem! Your reservation is still active."
            _append_assistant_reply(conversation_id, memory, reply)
            return ChatResponse(response=reply, intent="cancel_reservation")

    with get_openai_callback() as cb:
        t0 = time.perf_counter()
        response = graph.invoke({
            "query": query,
            "intent": None,
            "response": None,
            "reservation_data": None,
            "reservation_id": None,
            "current_reservation": memory["current_reservation"],
            "chat_history": memory["chat_history"],
            "pending_cancel": memory.get("pending_cancel"),
        })
        graph_ms = round((time.perf_counter() - t0) * 1000, 2)

    logger.info(
        "llm_usage",
        extra={
            "conversation_id": conversation_id,
            "intent": response.get("intent"),
            "prompt_tokens": cb.prompt_tokens,
            "completion_tokens": cb.completion_tokens,
            "total_tokens": cb.total_tokens,
            "cost_usd": round(cb.total_cost, 6),
            "graph_latency_ms": graph_ms,
        },
    )

    _log_drift(response.get("intent", "unknown"), len(query))

    pending_cancel = _extract_pending_cancel(response)
    if pending_cancel:
        memory["pending_cancel"] = pending_cancel
    if response.get("reservation_data"):
        memory["current_reservation"] = response["reservation_data"]

    _append_assistant_reply(conversation_id, memory, response["response"])
    return ChatResponse(
        response=response["response"],
        intent=response["intent"],
        reservation_id=response.get("reservation_id"),
    )


# ---------------------------------------------------------------------------
# /chat/stream
# ---------------------------------------------------------------------------

@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    query = payload.query
    conversation_id = payload.conversation_id
    memory = _get_or_init_memory(conversation_id)
    memory["chat_history"].append({"role": "user", "content": query})

    if payload.user_email and not memory.get("user_email"):
        memory["user_email"] = payload.user_email

    current_reservation = memory.get("current_reservation") or {}
    if memory.get("user_email") and not current_reservation.get("email"):
        current_reservation = {**current_reservation, "email": memory["user_email"]}

    # Intercept cancellation confirmation before invoking the graph
    pending = memory.get("pending_cancel")
    if pending:
        if _is_confirmation(query):
            from app.tools.reservation_tools import cancel_reservation_tool
            result = cancel_reservation_tool(pending["reservation_id"], pending["email"])
            memory["pending_cancel"] = None
            _log_drift("cancel_reservation", len(query))
            confirm_text = str(result)
            _append_assistant_reply(conversation_id, memory, confirm_text)
            async def confirm_stream():
                yield confirm_text
            return StreamingResponse(confirm_stream(), media_type="text/plain")
        elif _is_denial(query):
            memory["pending_cancel"] = None
            _log_drift("cancel_reservation", len(query))
            deny_text = "No problem! Your reservation is still active."
            _append_assistant_reply(conversation_id, memory, deny_text)
            async def deny_stream():
                yield deny_text
            return StreamingResponse(deny_stream(), media_type="text/plain")

    # Classify intent (non-streaming — track tokens here)
    summary = memory.get("history_summary", "")
    history_for_prompt = (
        [{"role": "system", "content": f"Earlier conversation summary: {summary}"}]
        + memory["chat_history"]
        if summary else memory["chat_history"]
    )
    intent_prompt = INTENT_PROMPT.format(
        chat_history=history_for_prompt, query=query
    )
    with get_openai_callback() as cb:
        intent_result = llm.with_structured_output(IntentOutput).invoke(intent_prompt)
        intent = intent_result.intent

    logger.info(
        "intent_classified",
        extra={
            "conversation_id": conversation_id,
            "intent": intent,
            "prompt_tokens": cb.prompt_tokens,
            "completion_tokens": cb.completion_tokens,
        },
    )
    _log_drift(intent, len(query))

    if intent == "hotel_qa":
        cache_key, cached_text = check_rag_cache(query)
        if cached_text:
            logger.info("rag_cache_hit", extra={"query": query})
            _append_assistant_reply(conversation_id, memory, cached_text)
            async def cached_stream():
                yield cached_text
            return StreamingResponse(cached_stream(), media_type="text/plain")

        rag_prompt = build_rag_prompt(query)

        async def generate():
            full_response: list[str] = []
            async for chunk in llm.astream(rag_prompt):
                if chunk.content:
                    full_response.append(chunk.content)
                    yield chunk.content
            response_text = "".join(full_response)
            save_rag_response(cache_key, response_text)
            _append_assistant_reply(conversation_id, memory, response_text)

        return StreamingResponse(generate(), media_type="text/plain")
    
    elif intent == "general_interactions":
        chat_history = memory.get("chat_history", [])
        identity_ctx = ""
        if memory.get("user_email"):
            identity_ctx += "The guest's identity has been verified. "
        guest_name = (memory.get("current_reservation") or {}).get("guest_name", "")
        if guest_name:
            identity_ctx += f"The guest's name on file is {guest_name}. "
        gen_prompt = build_general_prompt(query, chat_history, identity_ctx)

        async def gen_stream():
            full_response: list[str] = []
            async for chunk in llm.astream(gen_prompt):
                if chunk.content:
                    full_response.append(chunk.content)
                    yield chunk.content
            _append_assistant_reply(conversation_id, memory, "".join(full_response))

        return StreamingResponse(gen_stream(), media_type="text/plain")

    else:
        with get_openai_callback() as cb:
            response = graph.invoke({
                "query": query,
                "intent": intent,
                "response": None,
                "reservation_data": None,
                "reservation_id": None,
                "current_reservation": current_reservation,
                "chat_history": memory["chat_history"],
                "pending_cancel": memory.get("pending_cancel"),
            })

        logger.info(
            "llm_usage",
            extra={
                "conversation_id": conversation_id,
                "intent": intent,
                "prompt_tokens": cb.prompt_tokens,
                "completion_tokens": cb.completion_tokens,
                "total_tokens": cb.total_tokens,
                "cost_usd": round(cb.total_cost, 6),
            },
        )

        pending_cancel = _extract_pending_cancel(response)
        if pending_cancel:
            memory["pending_cancel"] = pending_cancel
        if response.get("reservation_id"):
            memory["current_reservation"] = None
            memory["pending_cancel"] = None
        elif response.get("reservation_data"):
            memory["current_reservation"] = response["reservation_data"]

        reply_text = response["response"]
        _append_assistant_reply(conversation_id, memory, reply_text)

        async def single_chunk():
            yield reply_text

        return StreamingResponse(single_chunk(), media_type="text/plain")


# ---------------------------------------------------------------------------
# Metrics endpoints
# ---------------------------------------------------------------------------

@app.get("/metrics/cache")
def metrics_cache():
    hits, misses = _rag_cache.stats()
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / total, 4) if total > 0 else 0.0,
        "entry_count": len(_rag_cache),
        "size_bytes": _rag_cache.volume(),
    }


@app.get("/metrics/drift")
def metrics_drift(window: int = 100):
    """
    Returns intent distribution for the last `window` requests and the
    preceding `window` requests. A shift between the two windows signals drift.
    """
    if not _DRIFT_LOG.exists():
        return {"error": "No drift data yet"}

    with open(_DRIFT_LOG) as f:
        lines = [l.strip() for l in f if l.strip()]

    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    def _distribution(batch: list[dict]) -> dict:
        counts: dict[str, int] = {}
        for e in batch:
            counts[e["intent"]] = counts.get(e["intent"], 0) + 1
        total = len(batch)
        return {k: {"count": v, "pct": round(v / total * 100, 1)} for k, v in counts.items()}

    recent = entries[-window:] if len(entries) >= window else entries
    previous = entries[-(window * 2):-window] if len(entries) >= window * 2 else []

    result: dict = {
        "total_logged": len(entries),
        "recent_window": _distribution(recent),
    }
    if previous:
        result["previous_window"] = _distribution(previous)

        # Simple drift flag: any intent whose share shifted by >10 percentage points
        all_intents = set(result["recent_window"]) | set(result["previous_window"])
        drift_alerts = []
        for intent in all_intents:
            r_pct = result["recent_window"].get(intent, {}).get("pct", 0.0)
            p_pct = result["previous_window"].get(intent, {}).get("pct", 0.0)
            if abs(r_pct - p_pct) > 10:
                drift_alerts.append({
                    "intent": intent,
                    "recent_pct": r_pct,
                    "previous_pct": p_pct,
                    "delta": round(r_pct - p_pct, 1),
                })
        result["drift_alerts"] = drift_alerts

    return result


@app.get("/metrics/health")
def metrics_health():
    hits, misses = _rag_cache.stats()
    total_cache = hits + misses
    return {
        "status": "ok",
        "cache": {
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / total_cache, 4) if total_cache > 0 else 0.0,
            "entry_count": len(_rag_cache),
        },
        "llm": {
            "primary_calls": fallback_stats["primary_calls"],
            "fallback_calls": fallback_stats["fallback_calls"],
            "primary_errors": fallback_stats["primary_errors"],
        },
        "drift_log_entries": sum(
            1 for _ in open(_DRIFT_LOG) if _DRIFT_LOG.exists()
        ) if _DRIFT_LOG.exists() else 0,
    }


# ---------------------------------------------------------------------------
# /escalate  — guest raises a question that the bot could not answer
# ---------------------------------------------------------------------------

@app.post("/escalate", status_code=201)
def escalate(payload: EscalationRequest):
    escalation_id = create_escalation(
        conversation_id=payload.conversation_id,
        query=payload.query,
        guest_email=payload.guest_email,
    )
    logger.info(
        "escalation_created",
        extra={"escalation_id": escalation_id, "query": payload.query},
    )
    return {"escalation_id": escalation_id, "status": "PENDING"}


# ---------------------------------------------------------------------------
# /admin/escalations  — hotel staff view & resolve pending questions
# ---------------------------------------------------------------------------

@app.get("/admin/escalations")
def list_escalations():
    return {"escalations": get_pending_escalations()}


@app.patch("/admin/escalations/{escalation_id}/resolve")
def resolve(escalation_id: int):
    found = resolve_escalation(escalation_id)
    if not found:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Escalation not found")
    return {"escalation_id": escalation_id, "status": "RESOLVED"}


# ---------------------------------------------------------------------------
# /admin/cache  — cache management
# ---------------------------------------------------------------------------

@app.delete("/admin/cache")
def clear_cache():
    count = len(_rag_cache)
    _rag_cache.clear()
    logger.info("cache_cleared", extra={"entries_removed": count})
    return {"cleared": True, "entries_removed": count}
