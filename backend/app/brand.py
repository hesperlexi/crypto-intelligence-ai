"""Brand values shared with the website (frontend/src/lib/brand.ts holds the same values; docs/v1-contract.md)."""
from __future__ import annotations

import json
import re
from pathlib import Path

NAME = "Crypto Intelligence AI"
URL = "https://www.cryptointelai.com"
DISPLAY_URL = "www.cryptointelai.com"
SUPPORT_EMAIL = "support@cryptointelai.com"
TAGLINE = "AI market analysis for crypto traders"
DISCLAIMER = "Analysis only, not financial advice. No guaranteed profits."
TELEGRAM_CHANNEL = "@crypappai"      # the real public channel (renaming it is the owner's call)


def _version() -> str:
    try:
        p = Path(__file__).resolve().parents[2] / "frontend" / "package.json"
        v = str(json.loads(p.read_text()).get("version") or "")
        if re.fullmatch(r"\d+\.\d+\.\d+([-.+][\w.]+)?", v):
            return v
    except Exception:
        pass
    return "2.0.0"


VERSION = APP_VERSION = _version()
FOOTER = f"{NAME} v{VERSION} · {DISPLAY_URL} · {SUPPORT_EMAIL} · Analysis only, not financial advice."
