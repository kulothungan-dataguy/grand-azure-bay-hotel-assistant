import hashlib
import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from langchain_community.callbacks import get_openai_callback

from app.graph.workflow import graph
from app.graph.nodes import llm
from app.rag.retriever import retriever
from app.rag.prompts import RAG_PROMPT
from app.rag.intent_prompt import INTENT_PROMPT
from app.schemas.intent_schema import IntentOutput
from app.db.models import create_tables
from app.utils.logger import logger
from app.schemas.api_schemas import ChatRequest, ChatResponse
from app.memory.store import conversation_memory
from app.cache.store import rag_cache as _rag_cache
from app.llm.provider import fallback_stats

_DRIFT_LOG = Path(".metrics/intent_log.jsonl")
_DRIFT_LOG.parent.mkdir(exist_ok=True)

app = FastAPI()
create_tables()


# ---------------------------------------------------------------------------
# Latency middleware
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_init_memory(conversation_id: str) -> dict:
    if conversation_id not in conversation_memory:
        conversation_memory[conversation_id] = {
            "chat_history": [],
            "current_reservation": None,
        }
    return conversation_memory[conversation_id]


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

    if response.get("reservation_data"):
        memory["current_reservation"] = response["reservation_data"]

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

    # Classify intent (non-streaming — track tokens here)
    intent_prompt = INTENT_PROMPT.format(
        chat_history=memory["chat_history"], query=query
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
        cache_key = hashlib.md5(query.lower().strip().encode()).hexdigest()
        if cache_key in _rag_cache:
            logger.info("rag_cache_hit", extra={"query": query})
            cached = _rag_cache[cache_key]

            async def cached_stream():
                yield cached["response"]

            return StreamingResponse(cached_stream(), media_type="text/plain")

        docs = retriever.invoke(query)
        context = "\n\n".join(doc.page_content for doc in docs)
        rag_prompt = RAG_PROMPT.format(context=context, question=query)

        async def generate():
            full_response: list[str] = []
            async for chunk in llm.astream(rag_prompt):
                if chunk.content:
                    full_response.append(chunk.content)
                    yield chunk.content
            _rag_cache.set(
                cache_key,
                {"response": "".join(full_response)},
                expire=86400,
            )

        return StreamingResponse(generate(), media_type="text/plain")

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

        if response.get("reservation_id"):
            memory["current_reservation"] = None
        elif response.get("reservation_data"):
            memory["current_reservation"] = response["reservation_data"]

        async def single_chunk():
            yield response["response"]

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
