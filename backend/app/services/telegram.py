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
from .. import brand
from ..redact import redact
from ..pricefmt import fmt_price

SITE = brand.URL
API = "https://api.telegram.org"
WINS_HOUR_UTC = 16
WEEKLY_HOUR_UTC = 6
TEASER_DELAY_MS = 60 * 60_000
MAX_WIN_POSTS = 5
MAX_DRAFTS = 6                     # each card is ~70 KB; a Firestore document holds 1 MB
STATUS_EVERY_MS = 3_600_000
BRIEFING_HOURS_UTC = (5, 13)       # v2.16: market briefing at 09:00 and 17:00 Dubai
BRIEFING_MAX_AGE_MS = 5 * 3_600_000
CALL_DELAY_MS = 2 * 3_600_000      # v2.16 daily free call: posted 2 h after its entry filled
DAY_MS = 86_400_000
DRAFTS = "owner/telegram_drafts"
DEFAULTS = {"enabled": False, "channel": brand.TELEGRAM_CHANNEL, "post_wins": True, "post_weekly": True, "post_teaser": True,
            "post_each_win": True, "approve_first": True, "post_proofs": False,
            # v2.16 funnel (on by default, but only ever posted while the autopilot itself is switched on)
            "post_daily_call": True, "post_briefing": True, "post_week7": True,
            # v2.21 (owner, 4 Nov 2026): high-impact US news heads-up, sent directly (a fact, not a result)
            "post_news": True}


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
    from .tracking import margin_fields, net_pct
    target = {"TP1": r.get("tp1"), "TP2": r.get("tp2"), "TP3": r.get("tp3")}.get(r["status"])
    return {"symbol": r["symbol"], "timeframe": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT",
            # v2.13: the result after fees (round trip + funding); the price return before fees beside it
            "status": r["status"], "return_pct": float(net_pct(r)), "gross_return_pct": float(r["return_pct"]),
            "entry": r.get("entry"),
            "exit_price": target, "held": _held((r.get("closed_at") or 0) - (r.get("created_at") or 0)),
            **margin_fields(r)}


def result_text(x: dict[str, Any], bold: bool = True) -> str:
    """Headline result: ROI on margin with its leverage and the price move, or the price move alone (labelled)."""
    ret = float(x["return_pct"])
    roi, lev = x.get("roi_pct"), x.get("leverage")
    if roi is None and lev and ret is not None:
        roi = ret * float(lev)
    b = (lambda t: f"<b>{t}</b>") if bold else (lambda t: t)
    if roi is None or not lev:
        return f"{b(f'{ret:+.2f}%')} after fees"
    return f"{b(f'{float(roi):+.2f}% ROI')} · {int(lev)}x margin ({ret:+.2f}% after fees)"


def win_text(w: dict[str, Any]) -> str:
    target = {"TP1": "Target 1 hit", "TP2": "Target 2 hit", "TP3": "All targets hit"}.get(w["status"], "Closed in profit")
    return "\n".join([
        f"✅ <b>{_coin(w['symbol'])} {w['side']}</b> ({w['timeframe'].upper()}) · {target}",
        f"💰 {result_text(w)}",
        f"Entry {_px(w['entry'])} → {_px(w['exit_price'])} · held {w['held']}",
        "", f"Get every signal live 👉 {SITE}", f"<i>{html.escape(brand.FOOTER)}</i>"])


def _coin(sym: str) -> str:
    b = sym.split("/")[0]
    return "GOLD" if b == "PAXG" else html.escape(b)      # PAXG tracks XAU/USD: shown as gold


def _px(v: float | None) -> str:
    return fmt_price(v)      # no scientific notation for coins below 0.0001


def wins_text(w: dict[str, Any]) -> str | None:
    wins = (w or {}).get("wins") or []
    if not wins:
        return None
    target = {"TP1": "target 1", "TP2": "target 2", "TP3": "all targets"}
    lines = [f"🏆 <b>Wins of the {'day' if w.get('period') == 'today' else 'week'}</b>", ""]
    for x in wins[:5]:
        lines.append(f"✅ <b>{_coin(x['symbol'])}</b> {x['side']} ({x['timeframe'].upper()}) · entry {_px(x['entry'])} · "
                     f"{target.get(x['status'], 'closed in profit')} · {result_text(x)}")
    lines += ["", f"Get every signal live with entry, stop-loss and targets 👉 {SITE}", f"<i>{html.escape(brand.FOOTER)}</i>"]
    return "\n".join(lines)


def weekly_text(r: dict[str, Any]) -> str | None:
    if not r or not r.get("closed"):
        return None
    d = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b")  # noqa: E731
    best = [t for t in (r.get("best") or []) if t["return_pct"] > 0][:3]
    lines = [f"📊 <b>Weekly results</b> · {d(r['week_start'])} – {d(r['week_end'] - 1)}", "",
             f"✅ {r['wins']} wins / {r['losses']} losses · win rate {r['win_rate']:.0%}",
             (f"📈 Total ROI on margin of all closed signals: <b>{r['total_roi_pct']:+.1f}%</b> "
              f"({r['total_return_pct']:+.1f}% after fees)" if r.get("total_roi_pct") is not None
              else f"📈 Total of all closed signals after fees: <b>{r['total_return_pct']:+.1f}%</b>")]
    if best:
        lines += ["", "Top signals:"] + [f"• {_coin(t['symbol'])} {t['side']} ({t['timeframe'].upper()}): {result_text(t, False)}" for t in best]
    lines += ["", f"AI crypto signals from 15 USDT/month 👉 {SITE}", "<i>Past results don't guarantee future results.</i>", f"<i>{html.escape(brand.FOOTER)}</i>"]
    return "\n".join(lines)


def _lev(s: dict[str, Any]) -> int | None:
    from .tracking import margin_fields
    return margin_fields(s).get("leverage")


def teaser_text(s: dict[str, Any]) -> str:
    side = "LONG 🟢" if s["side"] > 0 else "SHORT 🔴"
    mins = max(60, round((now_ms() - s["created_at"]) / 60_000))
    return "\n".join([
        f"⚡ <b>Free signal</b> · members got this {mins // 60} h {mins % 60:02d} min ago",
        "", f"<b>{_coin(s['symbol'])}{'' if s['symbol'].startswith('PAXG/') else '/USDT'} {side}</b> · {s['timeframe'].upper()} · grade A",
        f"Entry: {_px(s['entry'])}", f"Stop-loss: {_px(s['stop'])}",
        f"Targets: {_px(s['tp1'])} · {_px(s['tp2'])} · {_px(s['tp3'])}",
        *([f"Suggested leverage: {lev}x"] if (lev := _lev(s)) else []),
        "", f"Members get every signal the moment it appears, with phone alerts 👉 {SITE}",
        "<i>Prices may have moved since.</i>", f"<i>{html.escape(brand.FOOTER)}</i>"])


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

    def post(kind: str, text: str | None, marker: str, value: Any, card: tuple | None = None, direct: bool = False):
        if not text:
            return
        try:
            png = _card(*card) if card else None
            draft = cfg["approve_first"] and not direct
            if draft:
                add_draft(sink, kind, text, png, now)
            else:
                send_photo(cfg, png, text, session)
            db.set_setting(marker, value)
            out["sent"].append(kind + (" (waiting for approval)" if draft else ""))
        except Exception as exc:
            errors.append(redact(f"{kind}: {exc}")[:200])

    if cfg["post_wins"] and dt.hour >= WINS_HOUR_UTC and db.get_setting("tg_wins_day", "") != day:
        if (wins_view or {}).get("period") == "today":
            post("wins", wins_text(wins_view), "tg_wins_day", day,
                 ("wins_card", wins_view["wins"], wins_view["period"], wins_view.get("closed"), wins_view.get("losses")))
    if cfg["post_week7"] and dt.weekday() == 0 and dt.hour >= WEEKLY_HOUR_UTC and db.get_setting("tg_week7_day", "") != day:
        # v2.16: the weekly public report card (last 7 days after fees, sample-size note); replaces the older weekly post
        from ..views import recent_summary
        r7 = recent_summary(rt, 7, now)
        post("week7", week7_text(r7, now), "tg_week7_day", day, ("week7_card", r7, now))
    if cfg["post_weekly"] and not cfg["post_week7"] and dt.weekday() == 0 and dt.hour >= WEEKLY_HOUR_UTC \
            and db.get_setting("tg_weekly_day", "") != day:
        reports = (weekly_view or {}).get("reports") or []
        last = reports[1] if len(reports) > 1 else None
        if last and last.get("complete"):
            post("weekly", weekly_text(last), "tg_weekly_day", day, ("weekly_card", last))
    if cfg["post_teaser"] and not cfg["post_daily_call"] and db.get_setting("tg_teaser_day", "") != day:
        # (v2.16: the daily free call below replaces the teaser - it never picks by outcome and always posts the result)
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
            from .tracking import net_sql
            # v2.21: every win after fees (TP1 too), not only TP2 / TP3
            rows = db.query(f"SELECT * FROM signals WHERE status IN ('TP1', 'TP2', 'TP3') AND return_pct IS NOT NULL AND {net_sql()} > 0 "
                            f"AND closed_at IS NOT NULL AND closed_at > ? AND {rc} AND side != 0 "
                            "ORDER BY closed_at LIMIT ?", (int(last), *rp, MAX_WIN_POSTS))
            for r in rows:
                w = win_item(r)
                n = len(out["sent"])
                post("win", win_text(w), "tg_win_last", int(r["closed_at"]), ("win_card", w))
                if len(out["sent"]) == n:      # failed: keep the marker, try again next run
                    break
    if cfg["post_daily_call"]:
        try:
            daily_call(rt, now, post)
        except Exception as exc:
            errors.append(redact(f"daily call: {exc}")[:200])
    if cfg["post_briefing"]:
        slot = next((h for h in reversed(BRIEFING_HOURS_UTC) if dt.hour >= h), None)
        mark = f"{day}-{slot}"
        if slot is not None and db.get_setting("tg_briefing_slot", "") != mark:
            from .briefing import current
            b = current(db)
            if b and now - int(b.get("at") or 0) <= BRIEFING_MAX_AGE_MS:
                post("briefing", briefing_text(b), "tg_briefing_slot", mark, ("briefing_card", b))
    from .tracking import SEALED_PROOFS
    if cfg["post_proofs"] and SEALED_PROOFS:
        try:
            out["sent"] += proofs(rt, cfg, now, session)
        except Exception as exc:
            errors.append(redact(f"proof: {exc}")[:200])
    status = {"ok": not errors, "checked_at": now, "errors": errors, "last_sent": out["sent"] or None}
    # v2.16 (free plan): the status document was rewritten every 5-minute cycle (~288 writes a day); now only when
    # something was sent, the errors changed, or at most hourly as a sign of life
    from ..db import dumps as _dumps
    sig = _dumps({"ok": status["ok"], "errors": errors})
    written = db.get_setting("tg_status_written", None) or {}
    if out["sent"] or written.get("sig") != sig or now - int(written.get("at") or 0) >= STATUS_EVERY_MS:
        try:
            prev = sink.get("owner/telegram_status") or {}
            if any("approval" not in k for k in out["sent"]):
                status["last_post_at"] = now
            else:
                status["last_post_at"] = prev.get("last_post_at")
            if not out["sent"]:
                status["last_sent"] = prev.get("last_sent")
            sink.set("owner/telegram_status", status)
            db.set_setting("tg_status_written", {"sig": sig, "at": now})
        except Exception:
            pass
    out["errors"] = errors
    return out


# ---- v2.16 funnel: daily free call (delayed, result always follows), market briefing, last-7-days card -----------
# Daily call rule (fixed in advance, never by outcome): of the grade-A public calls published on a UTC day, in
# publication order, the first whose entry FILLED is that day's free call. An earlier call still waiting for its entry
# holds the choice back until it fills (then it is the pick) or expires unfilled (then the next one is considered).
# The card goes out CALL_DELAY_MS after the entry filled - whether the trade is still running or already closed - and
# its result (after fees) follows when it closes. Both are sent directly, never as drafts, so a loss can't be skipped.
def _grade(r: dict[str, Any]) -> str | None:
    from ..db import loads
    return (loads(r.get("payload"), {}) or {}).get("grade") if isinstance(r.get("payload"), str) else (r.get("payload") or {}).get("grade")


def pick_daily_call(rt, day_start: int) -> tuple[str, dict[str, Any] | None]:
    """('pick', row) | ('wait', None) | ('none', None) for the UTC day starting at day_start."""
    from ..views import record_clause
    rc, rp = record_clause(rt)
    rows = rt.db.query(f"SELECT * FROM signals WHERE side != 0 AND status != 'INFO' AND created_at >= ? AND created_at < ? "
                       f"AND {rc} ORDER BY created_at, id", (day_start, day_start + DAY_MS, *rp))
    for r in rows:
        if _grade(r) != "A":
            continue
        if r["status"] in ("NOT_FILLED", "VOID") and r.get("fill_status") != "FILLED":
            continue                                    # never traded: no result to show, the next call is considered
        if r.get("fill_status") == "PENDING":
            return "wait", None
        return "pick", r
    return "none", None


def _exit_price(r: dict[str, Any]) -> float | None:
    """The exit price where the record knows it for sure (all targets, or the stop); otherwise not shown."""
    if r.get("exit_reason") == "admin_close":
        return None
    return {"TP3": r.get("tp3"), "STOPPED": r.get("stop")}.get(r.get("status"))


def call_item(r: dict[str, Any]) -> dict[str, Any]:
    from .tracking import margin_fields, result_fields
    f = result_fields(r)
    start = r.get("filled_at") or r.get("created_at")
    return {"symbol": r["symbol"], "timeframe": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT",
            "status": r["status"], "exit_reason": r.get("exit_reason"), "return_pct": f.get("return_pct"),
            "gross_return_pct": f.get("gross_return_pct"), "entry": r.get("entry"), "exit_price": _exit_price(r),
            "held": _held((r.get("closed_at") or 0) - (start or 0)), **margin_fields(r)}


def _status_now(r: dict[str, Any]) -> str:
    if r["status"] == "OPEN":
        hit = [f"TP{i}" for i in (1, 2, 3) if r.get(f"tp{i}_hit")]
        return "running" + (f" ({', '.join(hit)} hit)" if hit else "")
    return "closed (result below)"


def call_text(r: dict[str, Any], now: int) -> str:
    side = "LONG 🟢" if r["side"] > 0 else "SHORT 🔴"
    pub = _utc(int(r["created_at"]))
    hrs = max(2, round((now - int(r["created_at"])) / 3_600_000))
    return "\n".join([
        f"🕑 <b>Free signal of the day</b> · members got it {pub}, {hrs} h ago",
        "", f"<b>{_coin(r['symbol'])}{'' if r['symbol'].startswith('PAXG/') else '/USDT'} {side}</b> · {r['timeframe'].upper()} · grade A",
        f"Entry: {_px(r['entry'])}", f"Stop-loss: {_px(r['stop'])}",
        f"Targets: {_px(r['tp1'])} · {_px(r['tp2'])} · {_px(r['tp3'])}",
        f"Status now: {_status_now(r)}",
        "", "Our rule: the first grade-A call of each day that got filled, chosen by time, never by result. Its result "
            "is posted here when it closes, win or loss.",
        f"Members get every signal the moment it appears 👉 {SITE}",
        "<i>Prices have moved since. Not financial advice.</i>", f"<i>{html.escape(brand.FOOTER)}</i>"])


def call_result_text(x: dict[str, Any]) -> str:
    res = {"TP1": "Target 1 hit, rest closed at break-even / time limit", "TP2": "Target 2 hit", "TP3": "All targets hit",
           "STOPPED": "Stopped out", "EXPIRED": "Closed at the time limit", "VOID": "No market data: void, not counted"}.get(
        x["status"], x["status"])
    if x.get("exit_reason") == "admin_close":
        res = "Closed by the admin at the market price"
    lines = [f"📌 <b>Result · free signal of the day</b> · {_coin(x['symbol'])} {x['side']} ({x['timeframe'].upper()})", res]
    if x.get("return_pct") is not None:
        lines.append(f"{'✅' if x['return_pct'] > 0 else '❌'} {result_text(x)}")
    lines += [f"Entry {_px(x['entry'])}" + (f" → {_px(x['exit_price'])}" if x.get("exit_price") else "") + f" · held {x['held']}",
              "", "Every daily free signal's result is posted, wins and losses alike.",
              f"Full public record 👉 {SITE}", f"<i>{html.escape(brand.FOOTER)}</i>"]
    return "\n".join(lines)


def daily_call(rt, now: int, post) -> None:
    """Pick, post (CALL_DELAY_MS after the fill) and later post the result of the daily free call."""
    db = rt.db
    today = now - now % DAY_MS
    since = db.get_setting("tg_daily_since", None)
    if since is None:                                  # first run: start with today (never posts older days)
        db.set_setting("tg_daily_since", today)
        since = today
    state = db.get_setting("tg_daily_calls", None) or {}
    for day_start in (today - DAY_MS, today):
        if day_start < int(since):
            continue
        key = datetime.fromtimestamp(day_start / 1000, timezone.utc).strftime("%Y-%m-%d")
        st = dict(state.get(key) or {})
        if not st.get("signal_id"):
            what, r = pick_daily_call(rt, day_start)
            if what != "pick":
                continue
            st = {"signal_id": r["id"], "picked_at": now}
            state[key] = st
            db.set_setting("tg_daily_calls", state)
        r = db.one("SELECT * FROM signals WHERE id = ?", (st["signal_id"],))
        if not r:
            continue
        fill = int(r.get("filled_at") or r["created_at"])
        if not st.get("posted_at") and now >= fill + CALL_DELAY_MS:
            post("daily_call", call_text(r, now), "tg_daily_last", r["id"],
                 ("teaser_card", r, max(120, round((now - int(r["created_at"])) / 60_000))), direct=True)
            if db.get_setting("tg_daily_last", None) == r["id"]:
                st["posted_at"] = now
        if st.get("posted_at") and not st.get("result_posted_at") and r["status"] not in ("OPEN", "INFO"):
            x = call_item(r)
            post("daily_result", call_result_text(x), "tg_daily_result_last", r["id"],
                 ("result_card", x) if x.get("return_pct") is not None else None, direct=True)
            if db.get_setting("tg_daily_result_last", None) == r["id"]:
                st["result_posted_at"] = now
        state[key] = st
    # keep the last 30 days of choices (an audit trail of what was picked and when)
    keep = sorted(state)[-30:]
    db.set_setting("tg_daily_calls", {k: state[k] for k in keep})


def briefing_text(b: dict[str, Any]) -> str | None:
    if not b or not b.get("text"):
        return None
    lines = ["🧭 <b>Market briefing</b> · " + _utc(int(b.get("at") or now_ms())), "", html.escape(b["text"])]
    if b.get("bullets"):
        lines += [""] + [f"• {html.escape(x)}" for x in b["bullets"][:5]]
    lines += ["", f"Live analysis and signals 👉 {SITE}",
              "<i>" + ("Written by AI from the engine's numbers. " if b.get("source") == "ai" else "") + "Context, not advice.</i>",
              f"<i>{html.escape(brand.FOOTER)}</i>"]
    return "\n".join(lines)


def week7_text(r: dict[str, Any], now: int) -> str | None:
    """Last 7 days of the public record after fees - posted even when it is a losing week."""
    d = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b")  # noqa: E731
    head = f"📊 <b>Last 7 days</b> · {d(now - 7 * DAY_MS)} – {d(now)}"
    if not r.get("closed"):
        return "\n".join([head, "", "No signal closed in these 7 days.", "", f"Full public record 👉 {SITE}",
                          f"<i>{html.escape(brand.FOOTER)}</i>"])
    lines = [head, "", f"Closed signals: <b>{r['closed']}</b> · {r['wins']} wins / {r['losses']} losses",
             f"Win rate (after fees): <b>{r['win_rate']:.0%}</b>",
             f"Average per signal after fees: <b>{r['avg_return_pct']:+.2f}%</b> (total {r['total_return_pct']:+.1f}%)"]
    if r.get("best"):
        lines.append(f"Best: {_coin(r['best']['symbol'])} {r['best']['side']} ({r['best']['timeframe'].upper()}) {r['best']['return_pct']:+.2f}%")
    if r.get("worst"):
        lines.append(f"Worst: {_coin(r['worst']['symbol'])} {r['worst']['side']} ({r['worst']['timeframe'].upper()}) {r['worst']['return_pct']:+.2f}%")
    if r.get("sample_note"):
        lines += ["", f"<i>{html.escape(r['sample_note'])}</i>"]
    lines += ["", "Equal size per signal, price move after a 0.15% round trip and funding; no leverage.",
              f"Every signal, wins and losses 👉 {SITE}", "<i>Past results don't guarantee future results.</i>",
              f"<i>{html.escape(brand.FOOTER)}</i>"]
    return "\n".join(lines)


# ---- v2.9 sealed-signal proof (services/proof.py) --------------------------------------------------------------
# Posted straight away, never as drafts: a fingerprint only proves something if it is public before the result.
SEAL_FRESH_MS = 30 * 60_000          # calls older than this when first seen are not sealed late (no back-dating)
MAX_PROOF_POSTS = 6


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b %H:%M UTC")


def seal_text(rows: list[dict[str, Any]]) -> str:
    lines = [f"🔒 <b>Sealed signal{'s' if len(rows) > 1 else ''}</b> · members have {'them' if len(rows) > 1 else 'it'} now", ""]
    for r in rows:
        lines.append(f"{r['timeframe'].upper()} · published {_utc(int(r['created_at']))}")
        lines.append(f"<code>{r['hash']}</code>")
    lines += ["", "Coin and levels stay hidden until the trade closes; then the full text is posted here. Anyone can check "
              "that its SHA-256 equals this fingerprint, so it cannot have been changed or added later.",
              f"How to verify 👉 {SITE}/verify"]
    return "\n".join(lines)


def reveal_text(r: dict[str, Any]) -> str:
    from .tracking import margin_fields
    res = {"TP1": "Target 1 hit", "TP2": "Target 2 hit", "TP3": "All targets hit", "STOPPED": "Stopped out",
           "EXPIRED": "Closed at the time limit", "NOT_FILLED": "Entry never filled (not counted)",
           "VOID": "No market data (not counted)"}.get(r["status"], r["status"])
    if r.get("exit_reason") == "admin_close":
        res = "Closed by the admin"
    head = f"🔓 <b>Signal revealed</b> · {_coin(r['symbol'])} {'LONG' if r['side'] > 0 else 'SHORT'} ({r['timeframe'].upper()}) · {res}"
    lines = [head]
    if r.get("return_pct") is not None:
        lines.append(f"{'✅' if r['return_pct'] > 0 else '❌'} {result_text({'return_pct': r['return_pct'], **margin_fields(r)})}")
    lines += ["", "Sealed text:", f"<code>{html.escape(r['text'])}</code>",
              f"Fingerprint posted {_utc(int(r['sealed_post_at']))}:", f"<code>{r['hash']}</code>",
              "", f"SHA-256 of the text = the fingerprint. Verify 👉 {SITE}/verify"]
    return "\n".join(lines)


def proofs(rt, cfg: dict[str, Any], now: int, session: Any = None) -> list[str]:
    db: Database = rt.db
    sent: list[str] = []
    rows = db.query("SELECT p.*, s.timeframe FROM signal_proofs p JOIN signals s ON s.id = p.signal_id "
                    "WHERE p.sealed_post_at IS NULL ORDER BY p.created_at LIMIT 50")
    fresh = [r for r in rows if now - int(r["created_at"]) <= SEAL_FRESH_MS]
    stale = [r for r in rows if now - int(r["created_at"]) > SEAL_FRESH_MS]
    for r in stale:                                    # missed the window: never sealed (it would prove nothing)
        db.execute("UPDATE signal_proofs SET sealed_post_at = -1 WHERE signal_id = ?", (r["signal_id"],))
    for i in range(0, len(fresh), MAX_PROOF_POSTS):
        part = fresh[i:i + MAX_PROOF_POSTS]
        send(cfg, seal_text(part), session)
        for r in part:
            db.execute("UPDATE signal_proofs SET sealed_post_at = ? WHERE signal_id = ?", (now, r["signal_id"]))
        sent.append(f"seal x{len(part)}")
    done = db.query("SELECT p.text, p.hash, p.sealed_post_at, p.signal_id, s.* FROM signal_proofs p JOIN signals s ON "
                    "s.id = p.signal_id WHERE p.sealed_post_at > 0 AND p.revealed_post_at IS NULL "
                    "AND s.status NOT IN ('OPEN', 'INFO') ORDER BY s.closed_at LIMIT ?", (MAX_PROOF_POSTS,))
    for r in done:
        send(cfg, reveal_text(r), session)
        db.execute("UPDATE signal_proofs SET revealed_post_at = ? WHERE signal_id = ?", (now, r["signal_id"]))
        sent.append("reveal")
    return sent


def test_post(sink) -> dict[str, Any]:
    cfg = config(sink)
    if not cfg["token"] or not cfg["channel"]:
        raise ValueError("add the bot token and the channel in Settings first")
    send(cfg, "✅ <b>Crypto Intelligence AI</b> is connected to this channel. Every win, wins of the day, weekly "
              f"results and a daily free signal will appear here automatically.\n\n👉 {SITE}")
    sink.set("owner/telegram_status", {"ok": True, "checked_at": now_ms(), "errors": [], "last_post_at": now_ms(),
                                       "last_sent": ["test"]})
    return {"sent": True}


# ---- v2.21 news heads-up (owner, 4 Nov 2026) --------------------------------------------------------------------
def news_text(m: dict[str, Any]) -> str:
    return "\n".join([f"📰 <b>{html.escape(str(m.get('title') or 'High-impact news'))}</b>",
                      html.escape(str(m.get("body") or "")), "", f"Live signals and alerts 👉 {SITE}",
                      f"<i>{html.escape(brand.FOOTER)}</i>"])


def post_news(sink, items: list[dict[str, Any]], session: Any = None) -> dict[str, Any]:
    """High-impact US release heads-up (the same items as the phone notification). Sent directly, never a draft:
    it is a calendar fact, not a result. Never raises."""
    cfg = config(sink)
    if not (items and cfg["enabled"] and cfg["token"] and cfg["channel"] and cfg["post_news"]):
        return {"sent": 0}
    sent, errors = 0, []
    for m in items:
        try:
            send(cfg, news_text(m), session)
            sent += 1
        except Exception as exc:
            errors.append(redact(f"news: {exc}")[:200])
    return {"sent": sent, "errors": errors}
