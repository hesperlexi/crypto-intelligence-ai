"""Telegram channel autopilot: free daily marketing without lifting a finger.

The owner creates a bot with @BotFather, adds it as an admin of the public channel and enters the token and the
channel in Settings (stored in owner/telegram, readable by the owner only). On engine runs it then posts:
  * Wins of the day - once a day (16:00 UTC, 20:00 Dubai), the best winning signals of the last 24 h;
  * Weekly results - Mondays from 06:00 UTC, last week's totals and best trades with the app link;
  * Teaser signal - at most one a day: a grade-A call members received at least an hour earlier;
  * Best wins (v2.3) - each signal that closes after reaching target 2 or 3, as soon as the engine sees it.
Approve first (default on): instead of posting, the engine puts each card in owner/telegram_drafts; the owner sees a
preview in Settings and taps Post (job "telegram_post", sent on the next engine run) or Skip.
Every post is an image card with the logo (services/cards.py) and the facts as its caption; if a card can't be
drawn the caption is sent as text. Each post is sent once (markers in the engine's settings). Wins and losses
alike come from the real record - the weekly card always shows the losses too.
"""
from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

from ..db import Database, now_ms

log = logging.getLogger(__name__)
SITE = "https://crypapp-6a9b9.web.app"
API = "https://api.telegram.org"
WINS_HOUR_UTC = 16
WEEKLY_HOUR_UTC = 6
TEASER_DELAY_MS = 60 * 60_000
MAX_WIN_POSTS = 5
MAX_DRAFTS = 6                     # each card is ~70 KB; a Firestore document holds 1 MB
DRAFTS = "owner/telegram_drafts"
DEFAULTS = {"enabled": False, "channel": "@crypappai", "post_wins": True, "post_weekly": True, "post_teaser": True,
            "post_each_win": True, "approve_first": True}


def config(sink) -> dict[str, Any]:
    raw = sink.get("owner/telegram") or {}
    cfg = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    cfg["token"] = (raw.get("token") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    ch = str(cfg["channel"] or "").strip()
    if ch and not ch.startswith(("@", "-")):
        ch = "@" + ch
    cfg["channel"] = ch
    return cfg


def send(cfg: dict[str, Any], text: str, session: Any = None) -> dict[str, Any]:
    r = (session or requests).post(f"{API}/bot{cfg['token']}/sendMessage", timeout=15,
                                   json={"chat_id": cfg["channel"], "text": text, "parse_mode": "HTML",
                                         "disable_web_page_preview": True})
    try:
        body = r.json()
    except Exception:
        body = {"ok": False, "description": f"HTTP {getattr(r, 'status_code', '?')}"}
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or "Telegram refused the message")
    return body


def send_photo(cfg: dict[str, Any], png: bytes | None, caption: str, session: Any = None) -> dict[str, Any]:
    """Image card with an HTML caption; falls back to a text message when there is no picture."""
    if not png:
        return send(cfg, caption, session)
    r = (session or requests).post(f"{API}/bot{cfg['token']}/sendPhoto", timeout=30,
                                   data={"chat_id": cfg["channel"], "caption": caption[:1024], "parse_mode": "HTML"},
                                   files={"photo": ("card.png", png, "image/png")})
    try:
        body = r.json()
    except Exception:
        body = {"ok": False, "description": f"HTTP {getattr(r, 'status_code', '?')}"}
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or "Telegram refused the picture")
    return body


def add_draft(sink, kind: str, caption: str, png: bytes | None, now: int) -> str:
    """Keep a card for the owner to approve (newest first, at most MAX_DRAFTS)."""
    import base64
    did = f"{kind}-{now}-{abs(hash(caption)) % 10_000:04d}"
    item = {"id": did, "kind": kind, "caption": caption, "created_at": now,
            "png": base64.b64encode(png).decode() if png else None}

    def put(cur):
        items = [x for x in ((cur or {}).get("items") or []) if x.get("id") != did]
        return {"items": ([item] + items)[:MAX_DRAFTS], "updated_at": now}, did
    return sink.transact(DRAFTS, put)


def post_draft(sink, draft_id: str, session: Any = None) -> dict[str, Any]:
    """Job from the website: send one approved card and take it off the list."""
    import base64
    cfg = config(sink)
    if not cfg["token"] or not cfg["channel"]:
        raise ValueError("add the bot token and the channel in Settings first")
    items = (sink.get(DRAFTS) or {}).get("items") or []
    item = next((x for x in items if x.get("id") == draft_id), None)
    if not item:
        return {"sent": False, "reason": "this card is no longer waiting (already posted or skipped)"}
    send_photo(cfg, base64.b64decode(item["png"]) if item.get("png") else None, item["caption"], session)
    sink.transact(DRAFTS, lambda cur: ({"items": [x for x in ((cur or {}).get("items") or []) if x.get("id") != draft_id],
                                        "updated_at": now_ms()}, None))
    prev = sink.get("owner/telegram_status") or {}
    sink.set("owner/telegram_status", {**prev, "ok": True, "errors": [], "last_post_at": now_ms(), "last_sent": [item["kind"]]})
    return {"sent": True, "kind": item["kind"]}


def _card(name: str, *args) -> bytes | None:
    try:
        from . import cards
        return getattr(cards, name)(*args)
    except Exception as exc:          # Pillow missing or a drawing error: the caption still goes out as text
        log.warning("telegram card %s failed: %s", name, exc)
        return None


def _held(ms: int | None) -> str:
    if not ms or ms <= 0:
        return "—"
    m = round(ms / 60_000)
    if m < 60:
        return f"{m} min"
    if m < 48 * 60:
        return f"{m // 60} h {m % 60:02d} min"
    return f"{m // 1440} d {(m % 1440) // 60} h"


def win_item(r: dict[str, Any]) -> dict[str, Any]:
    target = {"TP1": r.get("tp1"), "TP2": r.get("tp2"), "TP3": r.get("tp3")}.get(r["status"])
    return {"symbol": r["symbol"], "timeframe": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT",
            "status": r["status"], "return_pct": float(r["return_pct"]), "entry": r.get("entry"),
            "exit_price": target, "held": _held((r.get("closed_at") or 0) - (r.get("created_at") or 0))}


def win_text(w: dict[str, Any]) -> str:
    target = {"TP1": "Target 1 hit", "TP2": "Target 2 hit", "TP3": "All targets hit"}.get(w["status"], "Closed in profit")
    return "\n".join([
        f"✅ <b>{_coin(w['symbol'])} {w['side']}</b> ({w['timeframe'].upper()}) · {target} · <b>+{w['return_pct']:.1f}%</b>",
        f"Entry {_px(w['entry'])} → {_px(w['exit_price'])} · held {w['held']}",
        "", f"Get every signal live 👉 {SITE}", "<i>Not financial advice.</i>"])


def _coin(sym: str) -> str:
    b = sym.split("/")[0]
    return "GOLD" if b == "PAXG" else html.escape(b)      # PAXG tracks XAU/USD: shown as gold


def _px(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}" if v >= 100 else f"{v:,.4f}" if v >= 1 else f"{v:.6g}"


def wins_text(w: dict[str, Any]) -> str | None:
    wins = (w or {}).get("wins") or []
    if not wins:
        return None
    target = {"TP1": "target 1", "TP2": "target 2", "TP3": "all targets"}
    lines = [f"🏆 <b>Wins of the {'day' if w.get('period') == 'today' else 'week'}</b>", ""]
    for x in wins[:5]:
        lines.append(f"✅ <b>{_coin(x['symbol'])}</b> {x['side']} ({x['timeframe'].upper()}) · entry {_px(x['entry'])} · "
                     f"{target.get(x['status'], 'closed in profit')} · <b>+{x['return_pct']:.1f}%</b>")
    lines += ["", f"Get every signal live with entry, stop-loss and targets 👉 {SITE}", "<i>Not financial advice.</i>"]
    return "\n".join(lines)


def weekly_text(r: dict[str, Any]) -> str | None:
    if not r or not r.get("closed"):
        return None
    d = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b")  # noqa: E731
    best = [t for t in (r.get("best") or []) if t["return_pct"] > 0][:3]
    lines = [f"📊 <b>Weekly results</b> · {d(r['week_start'])} – {d(r['week_end'] - 1)}", "",
             f"✅ {r['wins']} wins / {r['losses']} losses · win rate {r['win_rate']:.0%}",
             f"📈 Total of all closed signals: <b>{r['total_return_pct']:+.1f}%</b>"]
    if best:
        lines += ["", "Top signals:"] + [f"• {_coin(t['symbol'])} {t['side']} ({t['timeframe'].upper()}): +{t['return_pct']:.1f}%" for t in best]
    lines += ["", f"AI crypto signals from 15 USDT/month 👉 {SITE}", "<i>Not financial advice. Past results don't guarantee future results.</i>"]
    return "\n".join(lines)


def teaser_text(s: dict[str, Any]) -> str:
    side = "LONG 🟢" if s["side"] > 0 else "SHORT 🔴"
    mins = max(60, round((now_ms() - s["created_at"]) / 60_000))
    return "\n".join([
        f"⚡ <b>Free signal</b> · members got this {mins // 60} h {mins % 60:02d} min ago",
        "", f"<b>{_coin(s['symbol'])}{'' if s['symbol'].startswith('PAXG/') else '/USDT'} {side}</b> · {s['timeframe'].upper()} · grade A",
        f"Entry: {_px(s['entry'])}", f"Stop-loss: {_px(s['stop'])}",
        f"Targets: {_px(s['tp1'])} · {_px(s['tp2'])} · {_px(s['tp3'])}",
        "", f"Members get every signal the moment it appears, with phone alerts 👉 {SITE}",
        "<i>Not financial advice. Prices may have moved since.</i>"])


def run(rt, sink, wins_view: dict[str, Any] | None, weekly_view: dict[str, Any] | None,
        now: int | None = None, session: Any = None) -> dict[str, Any]:
    """Post whatever is due. Returns what was sent (or why not); never raises."""
    now = now or now_ms()
    db: Database = rt.db
    cfg = config(sink)
    out: dict[str, Any] = {"enabled": bool(cfg["enabled"] and cfg["token"] and cfg["channel"]), "sent": []}
    if not out["enabled"]:
        return out
    dt = datetime.fromtimestamp(now / 1000, timezone.utc)
    day = dt.strftime("%Y-%m-%d")
    errors = []

    def post(kind: str, text: str | None, marker: str, value: Any, card: tuple | None = None):
        if not text:
            return
        try:
            png = _card(*card) if card else None
            if cfg["approve_first"]:
                add_draft(sink, kind, text, png, now)
            else:
                send_photo(cfg, png, text, session)
            db.set_setting(marker, value)
            out["sent"].append(kind + (" (waiting for approval)" if cfg["approve_first"] else ""))
        except Exception as exc:
            errors.append(f"{kind}: {exc}"[:200])

    if cfg["post_wins"] and dt.hour >= WINS_HOUR_UTC and db.get_setting("tg_wins_day", "") != day:
        if (wins_view or {}).get("period") == "today":
            post("wins", wins_text(wins_view), "tg_wins_day", day,
                 ("wins_card", wins_view["wins"], wins_view["period"]))
    if cfg["post_weekly"] and dt.weekday() == 0 and dt.hour >= WEEKLY_HOUR_UTC and db.get_setting("tg_weekly_day", "") != day:
        reports = (weekly_view or {}).get("reports") or []
        last = reports[1] if len(reports) > 1 else None
        if last and last.get("complete"):
            post("weekly", weekly_text(last), "tg_weekly_day", day, ("weekly_card", last))
    if cfg["post_teaser"] and db.get_setting("tg_teaser_day", "") != day:
        from ..views import record_clause
        rc, rp = record_clause(rt)
        rows = db.query("SELECT * FROM signals WHERE status = 'OPEN' AND side != 0 AND created_at <= ? AND created_at >= ? "
                        f"AND {rc} ORDER BY created_at DESC LIMIT 20",
                        (now - TEASER_DELAY_MS, now - 6 * 3_600_000, *rp))
        from ..db import loads
        pick = next((r for r in rows if (loads(r.get("payload"), {}) or {}).get("grade") == "A"), None)
        if pick:
            mins = max(60, round((now - pick["created_at"]) / 60_000))
            post("teaser", teaser_text(pick), "tg_teaser_day", day, ("teaser_card", pick, mins))
    if cfg["post_each_win"]:
        from ..views import record_clause
        last = db.get_setting("tg_win_last", None)
        if last is None:                       # first run: start from now, don't flood the channel with old wins
            db.set_setting("tg_win_last", now)
        else:
            rc, rp = record_clause(rt)
            rows = db.query("SELECT * FROM signals WHERE status IN ('TP2', 'TP3') AND return_pct > 0 "
                            f"AND closed_at IS NOT NULL AND closed_at > ? AND {rc} AND side != 0 "
                            "ORDER BY closed_at LIMIT ?", (int(last), *rp, MAX_WIN_POSTS))
            for r in rows:
                w = win_item(r)
                n = len(out["sent"])
                post("win", win_text(w), "tg_win_last", int(r["closed_at"]), ("win_card", w))
                if len(out["sent"]) == n:      # failed: keep the marker, try again next run
                    break
    status = {"ok": not errors, "checked_at": now, "errors": errors, "last_sent": out["sent"] or None}
    try:
        prev = sink.get("owner/telegram_status") or {}
        if any("approval" not in k for k in out["sent"]):
            status["last_post_at"] = now
        else:
            status["last_post_at"] = prev.get("last_post_at")
        sink.set("owner/telegram_status", status)
    except Exception:
        pass
    out["errors"] = errors
    return out


def test_post(sink) -> dict[str, Any]:
    cfg = config(sink)
    if not cfg["token"] or not cfg["channel"]:
        raise ValueError("add the bot token and the channel in Settings first")
    send(cfg, "✅ <b>Crypto Intelligence AI</b> is connected to this channel. Every win, wins of the day, weekly "
              f"results and a daily free signal will appear here automatically.\n\n👉 {SITE}")
    sink.set("owner/telegram_status", {"ok": True, "checked_at": now_ms(), "errors": [], "last_post_at": now_ms(),
                                       "last_sent": ["test"]})
    return {"sent": True}
