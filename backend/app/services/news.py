"""Market-moving news: the economic calendar (US data releases such as CPI, jobs report, FOMC) and crypto
headlines. Both are free, keyless public feeds; any that fails is reported, never filled in.

* The calendar is stored (econ_events) so the signal guard and replays know past events too.
* `event_risk(db, ts)` is the guard used by the analysis: around a high-impact US release prices often jump
  both ways within minutes, so fresh entries are paused from 45 minutes before to 30 minutes after.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree as ET

import requests

from ..db import Database, now_ms

log = logging.getLogger(__name__)

CALENDAR_FEEDS = ("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                  "https://nfs.faireconomy.media/ff_calendar_nextweek.json")
HEADLINE_FEEDS = (("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
                  ("Cointelegraph", "https://cointelegraph.com/rss"),
                  ("Decrypt", "https://decrypt.co/feed"))
COUNTRIES = {"USD"}                      # US releases move crypto the most; others only when High impact
OTHER_HIGH = {"EUR", "CNY", "JPY", "GBP"}
BEFORE_MS, AFTER_MS = 45 * 60_000, 30 * 60_000
UA = {"User-Agent": "Mozilla/5.0 (compatible; CryptoIntelligenceAI/2.0)"}

# what each release means for crypto, in one line (matched on the title)
EXPLAIN = (
    (r"\bCPI\b|Consumer Price", "Inflation. Hotter than expected usually hurts crypto (rates stay high); cooler helps."),
    (r"\bPCE\b", "The Fed's preferred inflation gauge. Same reading as CPI: hot hurts, cool helps."),
    (r"\bPPI\b|Producer Price", "Wholesale inflation; an early hint for CPI."),
    (r"Non-Farm|Nonfarm|NFP|Employment Change", "Jobs report. Very strong jobs can mean higher rates for longer (bad for crypto)."),
    (r"Unemployment", "Higher unemployment raises the odds of rate cuts (often good for crypto)."),
    (r"FOMC|Federal Funds|Fed Chair|Powell|Interest Rate", "Fed interest-rate decision or speech: the biggest single mover. Expect sharp swings."),
    (r"GDP", "Economic growth. Surprises in either direction move risk assets."),
    (r"Retail Sales", "Consumer spending; strong numbers can push rate cuts further out."),
    (r"Jobless Claims", "Weekly layoffs; a rising trend supports rate-cut hopes."),
    (r"ISM|PMI", "Business activity survey; signals where the economy is heading."),
)


def explain(title: str) -> str | None:
    for pat, text in EXPLAIN:
        if re.search(pat, title, re.I):
            return text
    return None


def _parse_ts(s: str) -> int | None:
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def sync_calendar(db: Database, session: Any = None) -> dict[str, Any]:
    """Fetch this and next week's calendar and upsert the relevant events. Returns a short status."""
    sess = session or requests
    got, errors = 0, []
    for url in CALENDAR_FEEDS:
        try:
            r = sess.get(url, timeout=12, headers=UA)
            if r.status_code == 404 and "nextweek" in url:
                continue                       # next week's file appears late in the week
            r.raise_for_status()
            rows = r.json()
        except Exception as exc:
            errors.append(f"{url.rsplit('/', 1)[-1]}: {type(exc).__name__}"[:120])
            continue
        for e in rows:
            country, impact = (e.get("country") or "").upper(), (e.get("impact") or "").title()
            if impact not in ("High", "Medium"):
                continue
            if not (country in COUNTRIES or (country in OTHER_HIGH and impact == "High")):
                continue
            ts = _parse_ts(e.get("date") or "")
            if ts is None:
                continue
            title = (e.get("title") or "").strip()
            eid = hashlib.sha1(f"{country}|{title}|{ts}".encode()).hexdigest()[:16]
            db.execute(
                "INSERT INTO econ_events (id, ts, country, title, impact, forecast, previous, actual, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET impact = excluded.impact, "
                "forecast = excluded.forecast, previous = excluded.previous, "
                "actual = COALESCE(excluded.actual, econ_events.actual), updated_at = excluded.updated_at",
                (eid, ts, country, title, impact, e.get("forecast") or None, e.get("previous") or None,
                 e.get("actual") or None, now_ms()))
            got += 1
    db.execute("DELETE FROM econ_events WHERE ts < ?", (now_ms() - 120 * 86_400_000,))
    return {"events": got, "errors": errors}


def events(db: Database, start: int, end: int) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM econ_events WHERE ts >= ? AND ts <= ? ORDER BY ts", (start, end))
    return [{**dict(r), "explain": explain(r["title"])} for r in rows]


def event_risk(db: Database, ts: int | None = None) -> dict[str, Any] | None:
    """The high-impact US release whose window (45 min before to 30 min after) contains `ts`, if any."""
    ts = ts or now_ms()
    try:
        r = db.one("SELECT * FROM econ_events WHERE impact = 'High' AND country = 'USD' AND ts >= ? AND ts <= ? "
                   "ORDER BY ABS(ts - ?) LIMIT 1", (ts - AFTER_MS, ts + BEFORE_MS, ts))
    except Exception:                          # older database without the table
        return None
    if not r:
        return None
    mins = round((r["ts"] - ts) / 60_000)
    when = f"in {mins} min" if mins > 0 else "now" if mins == 0 else f"{-mins} min ago"
    return {"title": r["title"], "ts": r["ts"], "minutes": mins, "when": when, "country": r["country"],
            "reason": f"major US data ({r['title']}) {when}: prices can jump both ways, so new entries wait until 30 min after the release"}


def due_notifications(db: Database, now: int | None = None, lead_min: int = 30) -> list[dict[str, Any]]:
    """High-impact US releases starting within `lead_min` minutes that nobody was told about yet (marks them)."""
    now = now or now_ms()
    rows = db.query("SELECT * FROM econ_events WHERE impact = 'High' AND country = 'USD' AND notified_at IS NULL "
                    "AND ts > ? AND ts <= ?", (now, now + lead_min * 60_000))
    out = []
    for r in rows:
        db.execute("UPDATE econ_events SET notified_at = ? WHERE id = ?", (now, r["id"]))
        mins = max(1, round((r["ts"] - now) / 60_000))
        out.append({"title": f"High-impact news in {mins} min", "url": "/news", "tag": f"econ-{r['id']}", "broadcast": "1",
                    "body": f"US {r['title']} at {datetime.utcfromtimestamp(r['ts'] / 1000):%H:%M} UTC. "
                            f"Expect volatility; new signals pause until 30 min after. {explain(r['title']) or ''}".strip()})
    return out


def _text(el: ET.Element | None) -> str:
    return re.sub(r"<[^>]+>", "", (el.text or "") if el is not None else "").strip()


def headlines(session: Any = None, limit: int = 30) -> dict[str, Any]:
    sess = session or requests
    items, errors = [], []
    for source, url in HEADLINE_FEEDS:
        try:
            r = sess.get(url, timeout=12, headers=UA)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as exc:
            errors.append(f"{source}: {type(exc).__name__}"[:120])
            continue
        for it in root.iter("item"):
            title, link = _text(it.find("title")), _text(it.find("link"))
            if not title or not link.startswith("http"):
                continue
            try:
                ts = int(parsedate_to_datetime(_text(it.find("pubDate"))).timestamp() * 1000)
            except Exception:
                ts = None
            items.append({"source": source, "title": title[:220], "url": link, "ts": ts,
                          "summary": _text(it.find("description"))[:260] or None})
    seen, out = set(), []
    for x in sorted(items, key=lambda x: x["ts"] or 0, reverse=True):
        k = re.sub(r"\W+", "", x["title"].lower())[:60]
        if k not in seen:
            seen.add(k)
            out.append(x)
    return {"items": out[:limit], "errors": errors}


def news_view(db: Database, heads: dict[str, Any] | None, cal_status: dict[str, Any] | None) -> dict[str, Any]:
    now = now_ms()
    return {"generated_at": now,
            "calendar": events(db, now - 2 * 86_400_000, now + 10 * 86_400_000),
            "risk_now": event_risk(db, now),
            "next_high": next((e for e in events(db, now - AFTER_MS, now + 10 * 86_400_000)
                               if e["impact"] == "High" and e["country"] == "USD"), None),
            "headlines": (heads or {}).get("items", []),
            "sources": {"calendar": "Forex Factory weekly economic calendar",
                        "headlines": ", ".join(s for s, _ in HEADLINE_FEEDS)},
            "errors": (cal_status or {}).get("errors", []) + (heads or {}).get("errors", [])}
