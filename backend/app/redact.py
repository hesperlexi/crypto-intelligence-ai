"""Remove secrets from error text before it is stored, published or logged (v2.13).

Errors from HTTP clients often quote the request URL: a Telegram bot token sits in the path
(`https://api.telegram.org/bot<id>:<secret>/sendPhoto`) and API keys sit in the query (`?key=...`). The engine's logs are
public (GitHub Actions of a public repository), so every error text goes through `redact` first.
"""
from __future__ import annotations

import logging
import re
from typing import Any

_RULES = (
    (re.compile(r"bot\d+:[\w-]+"), "bot<redacted>"),                                       # Telegram bot token
    (re.compile(r"(?i)([?&;](?:key|api[_-]?key|token|access[_-]?token|auth|secret|client[_-]?secret|signature|sig|"
                r"password|pass|pwd|code|credential|x-goog-api-key)=)[^&#\s'\"<>]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?(?:bearer|basic|token)\s+)[A-Za-z0-9._~+/=-]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(x-goog-api-key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9._-]+"), r"\1<redacted>"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "<redacted-key>"),                              # Google API keys
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), "<redacted-private-key>"),
    (re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1<redacted>@"),                   # user:password@host
)


def redact(text: Any) -> Any:
    """`text` with secrets replaced; non-strings are returned unchanged."""
    if not isinstance(text, str) or not text:
        return text
    for rx, rep in _RULES:
        text = rx.sub(rep, text)
    return text


def error_text(exc: BaseException, limit: int = 300) -> str:
    """'Type: message' of an exception, secrets removed (redacted before cutting, so a token is never half-kept)."""
    return redact(f"{type(exc).__name__}: {exc}")[:limit]


class RedactingFormatter(logging.Formatter):
    """Log formatter that runs the final line (message and traceback) through `redact`."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def install_logging_redaction() -> None:
    """Wrap the formatter of every root handler so nothing secret reaches the (public) job logs."""
    for h in logging.getLogger().handlers:
        fmt = h.formatter
        rf = RedactingFormatter(fmt._fmt if fmt else None, fmt.datefmt if fmt else None)
        h.setFormatter(rf)
