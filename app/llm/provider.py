import os
import threading
import time
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from app.llm.config import OPENAI_MODEL

try:
    from langchain_groq import ChatGroq
    _has_groq = True
except ImportError:
    _has_groq = False

load_dotenv()

# Thread-safe counters for health/metrics endpoint
fallback_stats: dict[str, int] = {
    "primary_calls": 0,
    "fallback_calls": 0,
    "primary_errors": 0,
}

_FAILURE_THRESHOLD = 3   # consecutive failures before opening the circuit
_RECOVERY_TIMEOUT  = 30  # seconds to wait before retrying OpenAI


class _CircuitBreaker:
    """
    Three-state circuit breaker (CLOSED → OPEN → HALF_OPEN → CLOSED).
    Prevents hammering OpenAI when it is known to be down.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._failures = 0
        self._state = "CLOSED"
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._state == "OPEN":
                if time.monotonic() >= self._open_until:
                    self._state = "HALF_OPEN"
                    return False
                return True
            return False

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._state = "CLOSED"

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= _FAILURE_THRESHOLD:
                self._state = "OPEN"
                self._open_until = time.monotonic() + _RECOVERY_TIMEOUT


_circuit = _CircuitBreaker()


class FallbackLLM:
    def __init__(self):
        self.primary_llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0, max_tokens=1024)

        if _has_groq and os.getenv("GROQ_API_KEY"):
            self.fallback_llm = ChatGroq(
                model="llama-3.1-8b-instant",
                api_key=os.environ["GROQ_API_KEY"],
                temperature=0,
            )
        else:
            self.fallback_llm = None

    def _use_fallback(self, prompt, logger):
        if not self.fallback_llm:
            raise RuntimeError("OpenAI is unavailable and no fallback LLM is configured.")
        fallback_stats["fallback_calls"] += 1
        logger.info("Falling back to Groq")
        response = self.fallback_llm.invoke(prompt)
        logger.debug("llm_response_fallback", extra={"response": response.content[:2000]})
        return response

    def invoke(self, prompt):
        from app.utils.logger import logger
        fallback_stats["primary_calls"] += 1
        prompt_text = prompt if isinstance(prompt, str) else str(prompt)
        logger.debug("llm_invoke", extra={"prompt": prompt_text[:2000]})

        if _circuit.is_open:
            logger.warning("circuit_open_skipping_openai")
            return self._use_fallback(prompt, logger)

        try:
            response = self.primary_llm.invoke(prompt)
            _circuit.record_success()
            logger.debug("llm_response", extra={"response": response.content[:2000]})
            return response
        except Exception as e:
            fallback_stats["primary_errors"] += 1
            _circuit.record_failure()
            logger.error(f"OpenAI failed: {e}")
            return self._use_fallback(prompt, logger)

    def with_structured_output(self, schema):
        return self.primary_llm.with_structured_output(schema)

    async def astream(self, prompt):
        from app.utils.logger import logger
        fallback_stats["primary_calls"] += 1
        prompt_text = prompt if isinstance(prompt, str) else str(prompt)
        logger.debug("llm_astream_start", extra={"prompt": prompt_text[:2000]})

        if _circuit.is_open:
            logger.warning("circuit_open_skipping_openai")
            result = self._use_fallback(prompt, logger)
            yield result
            return

        full_response = []
        try:
            async for chunk in self.primary_llm.astream(prompt):
                if chunk.content:
                    full_response.append(chunk.content)
                yield chunk
            _circuit.record_success()
            logger.debug("llm_astream_done", extra={"response": "".join(full_response)[:2000]})
        except Exception as e:
            fallback_stats["primary_errors"] += 1
            _circuit.record_failure()
            logger.error(f"OpenAI astream failed: {e}")
            result = self._use_fallback(prompt, logger)
            logger.debug("llm_astream_fallback", extra={"response": result.content[:2000]})
            yield result


def get_llm():
    return FallbackLLM()
