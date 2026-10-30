"""v2.6 news sentiment: COLLECTION ONLY (no decision uses it).

Once per hour the engine asks the Gemini advisor (services/ai_advisor.py: same daily budget, breaker and key) to score
the recent crypto headlines that services/news.py already fetches (CoinDesk, Cointelegraph, Decrypt RSS) into a market
sentiment in [-1, 1] for the market as a whole and per coin group (BTC, ETH, alts). When no headline feed is reachable
the score is made from the economic-calendar context only (upcoming / recent high-impact US releases) and stored with
source = 'calendar'. Rows are keyed by the hour and carry `known_at` (when they were scored) and the newest headline
time used, so a later back-test can align them without look-ahead. Nothing is invented: no key, no budget or no
answer -> no row.

ml/sentiment_gate.py will evaluate the score as a feature once 60 days of history exist; until then it is off.
"""
from __future__ import annotations

import logging
from typing import Any

from ..db import Database, now_ms

log = logging.getLogger(__name__)
HOUR = 3_600_000
GROUPS = ("market", "BTC", "ETH", "alts")
MAX_HEADLINES = 25
LOOKBACK_MS = 6 * HOUR


def due(db: Database, now: int | None = None) -> bool:
    now = now or now_ms()
    try:
        r = db.one("SELECT MAX(ts) AS t FROM news_sentiment")
    except Exception:
        return False
    return not (r and r["t"] is not None and int(r["t"]) >= now // HOUR * HOUR)


def _inputs(db: Database, heads: dict[str, Any] | None, now: int) -> tuple[dict[str, Any], str, int | None, int]:
    items = [h for h in (heads or {}).get("items", []) if h.get("ts") and now - LOOKBACK_MS <= int(h["ts"]) <= now]
    items = sorted(items, key=lambda h: h["ts"], reverse=True)[:MAX_HEADLINES]
    from .news import events
    cal = [{"title": e["title"], "impact": e["impact"], "hours_from_now": round((e["ts"] - now) / HOUR, 1),
            "actual": e.get("actual"), "forecast": e.get("forecast"), "previous": e.get("previous")}
           for e in events(db, now - 24 * HOUR, now + 48 * HOUR) if e["country"] == "USD"]
    if items:
        data = {"headlines": [{"title": h["title"], "source": h["source"], "hours_ago": round((now - h["ts"]) / HOUR, 1)}
                              for h in items], "calendar": cal[:10]}
        return data, "headlines", max(int(h["ts"]) for h in items), len(items)
    return {"headlines": [], "calendar": cal[:10]}, "calendar", None, 0


def collect(db: Database, heads: dict[str, Any] | None, advisor: Any = None, now: int | None = None) -> dict[str, Any]:
    """Score the current hour once. Returns a short status (never raises)."""
    from ..config import settings
    now = now or now_ms()
    if not settings.news_sentiment:
        return {"skipped": "off"}
    if not due(db, now):
        return {"skipped": "already scored this hour"}
    try:
        from .ai_advisor import Advisor
        adv = advisor or Advisor(db)
        if not adv.available(now):
            return {"skipped": "advisor off or over budget"}
        data, source, newest, n = _inputs(db, heads, now)
        if source == "calendar" and not data["calendar"]:
            return {"skipped": "no headlines and no calendar context"}
        props = {g: {"type": "NUMBER"} for g in GROUPS}
        schema = {"type": "OBJECT", "properties": props, "required": list(GROUPS)}
        out = adv.generate(
            "Score the likely short-term effect of this news on crypto prices as numbers between -1 (very bearish) and "
            "1 (very bullish), 0 = neutral or no relevant news: 'market' (crypto overall), 'BTC', 'ETH', 'alts' (other "
            "coins). Use ONLY the input headlines and calendar entries; with no relevant news answer 0.", data, schema, now)
        if not out:
            return {"skipped": "no answer"}
        hour = now // HOUR * HOUR
        rows = []
        for g in GROUPS:
            try:
                v = float(out.get(g))
            except (TypeError, ValueError):
                continue
            if v != v:
                continue
            rows.append((hour, g, max(-1.0, min(1.0, v)), n, newest, now, source, getattr(adv, "model", None)))
        if rows:
            db.executemany("INSERT INTO news_sentiment (ts, grp, score, n_headlines, newest_headline_ts, known_at, source, model) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (ts, grp) DO NOTHING", rows)
        return {"scored": len(rows), "source": source, "headlines": n}
    except Exception as exc:
        log.warning("sentiment collection failed: %s", exc)
        return {"error": f"{type(exc).__name__}"}


def history(db: Database, grp: str = "market") -> list[dict[str, Any]]:
    return [dict(r) for r in db.query("SELECT * FROM news_sentiment WHERE grp = ? ORDER BY ts", (grp,))]


def as_of(db: Database, ts: int, grp: str = "market") -> float | None:
    """The latest score KNOWN at `ts` (by known_at, never by the hour label): no look-ahead."""
    r = db.one("SELECT score FROM news_sentiment WHERE grp = ? AND known_at <= ? ORDER BY known_at DESC LIMIT 1", (grp, ts))
    return float(r["score"]) if r else None
