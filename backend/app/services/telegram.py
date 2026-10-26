"""Telegram channel autopilot: free daily marketing without lifting a finger.

The owner creates a bot with @BotFather, adds it as an admin of the public channel and enters the token and the
channel in Settings (stored in owner/telegram, readable by the owner only). On engine runs it then posts:
  * Wins of the day - once a day (16:00 UTC, 20:00 Dubai), the best winning signals of the last 24 h;
  * Weekly results - Mondays from 06:00 UTC, last week's totals and best trades with the app link;
  * Teaser signal - at most one a day: a grade-A call members received at least an hour earlier.
Every post is sent once (markers in the engine's settings). Messages are plain facts from the real record.
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
DEFAULTS = {"enabled": False, "channel": "", "post_wins": True, "post_weekly": True, "post_teaser": True}


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


def _coin(sym: str) -> str:
    return html.escape(sym.split("/")[0])


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
    lines += ["", f"AI crypto signals from $15/month 👉 {SITE}", "<i>Not financial advice. Past results don't guarantee future results.</i>"]
    return "\n".join(lines)


def teaser_text(s: dict[str, Any]) -> str:
    side = "LONG 🟢" if s["side"] > 0 else "SHORT 🔴"
    mins = max(60, round((now_ms() - s["created_at"]) / 60_000))
    return "\n".join([
        f"⚡ <b>Free signal</b> · members got this {mins // 60} h {mins % 60:02d} min ago",
        "", f"<b>{_coin(s['symbol'])}/USDT {side}</b> · {s['timeframe'].upper()} · grade A",
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

    def post(kind: str, text: str | None, marker: str, value: Any):
        if not text:
            return
        try:
            send(cfg, text, session)
            db.set_setting(marker, value)
            out["sent"].append(kind)
        except Exception as exc:
            errors.append(f"{kind}: {exc}"[:200])

    if cfg["post_wins"] and dt.hour >= WINS_HOUR_UTC and db.get_setting("tg_wins_day", "") != day:
        if (wins_view or {}).get("period") == "today":
            post("wins", wins_text(wins_view), "tg_wins_day", day)
    if cfg["post_weekly"] and dt.weekday() == 0 and dt.hour >= WEEKLY_HOUR_UTC and db.get_setting("tg_weekly_day", "") != day:
        reports = (weekly_view or {}).get("reports") or []
        last = reports[1] if len(reports) > 1 else None
        if last and last.get("complete"):
            post("weekly", weekly_text(last), "tg_weekly_day", day)
    if cfg["post_teaser"] and db.get_setting("tg_teaser_day", "") != day:
        from ..views import record_since
        rows = db.query("SELECT * FROM signals WHERE status = 'OPEN' AND side != 0 AND created_at <= ? AND created_at >= ? "
                        "AND created_at >= ? ORDER BY created_at DESC LIMIT 20",
                        (now - TEASER_DELAY_MS, now - 6 * 3_600_000, record_since(rt)))
        from ..db import loads
        pick = next((r for r in rows if (loads(r.get("payload"), {}) or {}).get("grade") == "A"), None)
        if pick:
            post("teaser", teaser_text(pick), "tg_teaser_day", day)
    status = {"ok": not errors, "checked_at": now, "errors": errors, "last_sent": out["sent"] or None}
    try:
        prev = sink.get("owner/telegram_status") or {}
        if out["sent"]:
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
    send(cfg, "✅ <b>Crypto Intelligence AI</b> is connected to this channel. Wins of the day, weekly results and a "
              f"daily free signal will appear here automatically.\n\n👉 {SITE}")
    sink.set("owner/telegram_status", {"ok": True, "checked_at": now_ms(), "errors": [], "last_post_at": now_ms(),
                                       "last_sent": ["test"]})
    return {"sent": True}
