"""Logging estruturado em JSON, que nunca exibe tokens ou segredos (Task 1.6)."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

REDACTED = "[redacted]"

_SENSITIVE_KEY = re.compile(
    r"(token|secret|password|passwd|authorization|api[_-]?key|cookie|credential)", re.IGNORECASE
)
_PATTERNS = [
    # Authorization: Bearer <token>
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1" + REDACTED),
    # postgresql://user:senha@host
    (re.compile(r"(://[^:/@\s]+:)[^@\s]+(@)"), r"\1" + REDACTED + r"\2"),
    # token=..., "password": "...", access_token: ...
    (
        re.compile(
            r"(?i)((?:access_token|refresh_token|client_secret|token|secret|password|api_key)"
            r"[\"']?\s*[=:]\s*[\"']?)[^\s\"'&,}]+"
        ),
        r"\1" + REDACTED,
    ),
]

# Atributos que todo LogRecord tem; o resto veio por extra=.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


def redact_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact(value: Any, key: str | None = None) -> Any:
    if key is not None and _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = redact(value, key)
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
