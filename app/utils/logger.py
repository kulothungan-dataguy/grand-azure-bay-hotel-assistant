import contextvars
import json
import logging
import os
import time

# Set by RequestIdMiddleware at the start of each HTTP request so every log
# line emitted during that request carries the same request_id for correlation.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)

_SKIP_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        for key, val in record.__dict__.items():
            if key not in _SKIP_KEYS and not key.startswith("_"):
                payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


_handler = logging.StreamHandler()
_handler.setFormatter(_JsonFormatter())

logger = logging.getLogger("hotel_ai_assistant")
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
logger.handlers = [_handler]
logger.propagate = False
