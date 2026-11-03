"""v2.16 practice leaderboard (owner decision 3 Nov 2026): members ranked each calendar month (Dubai time) by the % return
of their FUTURES practice account (paper/{uid}_futures; spot practice is not counted - documented choice: one account,
one clear number, and the futures account is the one auto-trade and the signal cards use).

    return = (equity_now - equity_start - deposits) / (equity_start + deposits)

equity = wallet + money held for limit orders + each open position's margin + its profit / loss at the engine's price
(never below zero per position: isolated margin), exactly like the Trade page. `deposits` = the rise of `deposited`
("Add funds") since the month's first reading, so adding virtual money never counts as profit.

Computed by the ENGINE only (the website never ranks anyone):
  * at most every EVERY_S (1 h); skipped in lean mode (near the Firestore write budget);
  * reads: one document per member, and only when needed - the member opened the app since the last reading
    (presence, already read hourly for the write estimate, so no extra read), it is older than STALE_S (6 h; auto-trade
    writes the account without the member), or a new month began (everyone once). Open positions are re-priced every
    hour from the stored reading without another read;
  * who: active members (approved, not expired) WITH a username (privacy: only usernames are ever shown; members without
    one are not ranked) and not excluded by the admin (owner/leaderboard.excluded);
  * qualifies with >= MIN_TRADES closed trades in the month (totals.count) and no account reset in the month (a reset
    makes a new account: it would let someone retry until lucky);
  * month-start readings live in SQLite (`leaderboard_entries`). The first run after a month ends reads every account
    once: that reading closes the old month and opens the new one. Winner(s) (best return; exact ties share) go to
    `leaderboard_winners` and the admin's document; the prize (1 free month + badge) is NEVER granted here - the admin
    clicks "Award prize" on the Leaderboard tab (frontend/src/lib/leaderboard.ts).

Published: views/leaderboard (members: top 50 with usernames, trades and return; last month's winner; badges by
username; no uid / email) and admin/leaderboard (admin only: every entry with uid, deposits, equity, a "check" flag
when the numbers do not add up, and the winners).
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..db import dumps, loads, now_ms
from . import membership

DUBAI = timezone(timedelta(hours=4))
EVERY_S = int(os.environ.get("LEADERBOARD_EVERY_S", "3600"))
STALE_S = int(os.environ.get("LEADERBOARD_STALE_S", str(6 * 3600)))
MIN_TRADES = 5
TOP_N = 50
CHECK_RETURN_PCT = 300.0          # a return above this is flagged for the admin's look before any prize
BADGE_PREFIX = "lb:"              # users/{uid}.badges entries "lb:YYYY-MM" (written by the admin's Award prize)
RULES = f"Virtual money. Ranked by % return after deposits. Min {MIN_TRADES} closed trades."


# ------------------------------------------------------------------------------------------------ months (Dubai)
def month_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, DUBAI).strftime("%Y-%m")


def month_label(key: str) -> str:
    y, m = key.split("-")
    return datetime(int(y), int(m), 1).strftime("%B %Y")


def month_start_ms(key: str) -> int:
    y, m = key.split("-")
    return int(datetime(int(y), int(m), 1, tzinfo=DUBAI).timestamp() * 1000)


# ------------------------------------------------------------------------------------------------ one account
def _num(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def deposited_of(acc: dict[str, Any]) -> float:
    """Total virtual USDT put in (older accounts without the field: their starting balance) - writeShapes.depositedOf."""
    return _num(acc.get("deposited"), _num(acc.get("starting_balance")))


def slim_positions(acc: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for p in (acc.get("positions") or {}).values():
        if isinstance(p, dict) and p.get("symbol"):
            out.append({"symbol": str(p["symbol"]), "side": 1 if _num(p.get("side")) > 0 else -1, "qty": _num(p.get("qty")),
                        "entry": _num(p.get("entry")), "margin": _num(p.get("margin"))})
    return out


def equity_of(wallet: float, reserved: float, positions: list[dict[str, Any]], price_of: Callable[[str], float | None]) -> tuple[float, int]:
    """(equity, positions without a price). Same formula as paperFutures.subscribe: a position never counts below zero."""
    eq, unpriced = wallet + reserved, 0
    for p in positions:
        px = price_of(p["symbol"])
        if not px:
            unpriced += 1
            px = p["entry"]
        eq += max(0.0, p["margin"] + p["side"] * p["qty"] * (float(px) - p["entry"]))
    return eq, unpriced


def reading(acc: dict[str, Any], price_of: Callable[[str], float | None], now: int) -> dict[str, Any]:
    """What the leaderboard keeps from one read of paper/{uid}_futures."""
    totals = acc.get("totals") or {}
    reserved = sum(_num(o.get("reserve")) for o in (acc.get("orders") or {}).values() if isinstance(o, dict))
    pos = slim_positions(acc)
    wallet = _num(acc.get("wallet"))
    eq, unpriced = equity_of(wallet, reserved, pos, price_of)
    return {"account_id": str(acc.get("id") or ""), "wallet": wallet, "reserved": reserved, "positions": pos,
            "equity": eq, "unpriced": unpriced, "deposited": deposited_of(acc), "count": int(_num(totals.get("count"))),
            "realized": _num(totals.get("realized")), "book": wallet + reserved + sum(p["margin"] for p in pos), "at": now}


def reprice(last: dict[str, Any], price_of: Callable[[str], float | None]) -> dict[str, Any]:
    eq, unpriced = equity_of(last["wallet"], last["reserved"], last["positions"], price_of)
    return {**last, "equity": eq, "unpriced": unpriced}


def score(e: dict[str, Any], last: dict[str, Any]) -> dict[str, Any]:
    """Return, deposits and trades of one entry (row of leaderboard_entries) against its latest reading."""
    deps = max(0.0, last["deposited"] - e["start_deposited"])
    base = e["start_equity"] + deps
    ret = (last["equity"] - e["start_equity"] - deps) / base * 100 if base > 0 else 0.0
    trades = max(0, last["count"] - e["start_count"])
    # the book (wallet + reserved + margins at cost) can only move by realised results and deposits; anything else means
    # the account was changed outside the app's trading code -> flagged for the admin (never hidden from the ranking
    # automatically: the admin decides, and the prize needs the admin's click anyway)
    unexplained = (last["book"] - e["start_book"]) - (last["realized"] - e["start_realized"]) - deps
    flags = []
    if abs(unexplained) > max(5.0, 0.02 * base):
        flags.append("balance changed without trades")
    if ret > CHECK_RETURN_PCT:
        flags.append(f"return above {CHECK_RETURN_PCT:.0f}%")
    if e.get("reset"):
        flags.append("account reset this month")
    return {"return_pct": round(ret, 2), "deposits": round(deps, 2), "start_equity": round(e["start_equity"], 2),
            "equity": round(last["equity"], 2), "trades": trades, "unexplained": round(unexplained, 2), "flags": flags,
            "qualified": not e.get("reset") and trades >= MIN_TRADES and base > 0}


def rank(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Qualified entries, best return first (ties: more trades, then username). Equal returns share a rank."""
    q = sorted((s for s in scored if s["qualified"]), key=lambda s: (-s["return_pct"], -s["trades"], s.get("username") or ""))
    out, prev, r = [], None, 0
    for i, s in enumerate(q):
        if s["return_pct"] != prev:
            r, prev = i + 1, s["return_pct"]
        out.append({**s, "rank": r})
    return out


# ------------------------------------------------------------------------------------------------ engine run
def _users(rt: Any) -> dict[str, dict[str, Any]]:
    return (rt.db.get_setting("users_cache", None) or {}).get("users") or {}


def eligible(users: dict[str, dict[str, Any]], now: int, excluded: set[str]) -> dict[str, str]:
    """uid -> username of the members who take part (active, with a username, not excluded)."""
    return {uid: str(u["username"]) for uid, u in users.items()
            if u.get("username") and uid not in excluded and membership.is_active(u, now)}


def badges(users: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for u in users.values():
        months = sorted(b[len(BADGE_PREFIX):] for b in (u.get("badges") or []) if isinstance(b, str) and b.startswith(BADGE_PREFIX))
        if months and u.get("username"):
            out[str(u["username"])] = months
    return out


def _price_fn(rt: Any, symbols: set[str], allow_rest: bool) -> Callable[[str], float | None]:
    """Engine price per coin: live / newest 15m close for the coins it follows; one public ticker call for the rest."""
    from .adjust import latest_price
    cache: dict[str, float | None] = {}
    known = set(rt.symbols()) if hasattr(rt, "symbols") else set()
    for s in symbols & known:
        try:
            cache[s] = latest_price(rt, s)
        except Exception:
            cache[s] = None
    rest = {s for s in symbols if not cache.get(s)}
    prov = getattr(rt, "provider", None)
    if rest and allow_rest and hasattr(prov, "_get_sync"):
        try:
            rows = prov._get_sync("/api/v3/ticker/price")
            by = {r["symbol"]: float(r["price"]) for r in rows or [] if isinstance(r, dict) and r.get("price")}
            for s in rest:
                cache[s] = by.get(s.replace("/", "")) or cache.get(s)
        except Exception:
            pass
    return lambda s: cache.get(s)


def _entries(db: Any, month: str) -> dict[str, dict[str, Any]]:
    out = {}
    for r in db.query("SELECT * FROM leaderboard_entries WHERE month = ?", (month,)):
        out[r["uid"]] = {**r, "last": loads(r["last_json"], {})}
    return out


def _save(db: Any, month: str, uid: str, e: dict[str, Any]) -> None:
    db.execute(
        "INSERT INTO leaderboard_entries (month, uid, account_id, start_equity, start_deposited, start_count, start_realized, "
        "start_book, start_at, last_json, last_read_at, reset) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (month, uid) DO UPDATE SET last_json = excluded.last_json, last_read_at = excluded.last_read_at, "
        "reset = excluded.reset",
        (month, uid, e["account_id"], e["start_equity"], e["start_deposited"], e["start_count"], e["start_realized"],
         e["start_book"], e["start_at"], dumps(e["last"]), e["last_read_at"], int(bool(e.get("reset")))))


def _new_entry(r: dict[str, Any], now: int) -> dict[str, Any]:
    return {"account_id": r["account_id"], "start_equity": r["equity"], "start_deposited": r["deposited"], "start_count": r["count"],
            "start_realized": r["realized"], "start_book": r["book"], "start_at": now, "last": r, "last_read_at": now, "reset": 0}


def _apply(e: dict[str, Any] | None, r: dict[str, Any], now: int) -> dict[str, Any]:
    if e is None:
        return _new_entry(r, now)
    reset = bool(e.get("reset")) or (r["account_id"] != (e.get("account_id") or ""))
    return {**e, "last": r, "last_read_at": now, "reset": int(reset)}


def standings(month: str, entries: dict[str, dict[str, Any]], names: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(ranked qualified rows, every scored row) of the members in `names`."""
    scored = []
    for uid, e in entries.items():
        if uid not in names or not e.get("last"):
            continue
        scored.append({"uid": uid, "username": names[uid], **score(e, e["last"])})
    return rank(scored), scored


def decide_winners(db: Any, month: str, ranked: list[dict[str, Any]], now: int) -> list[dict[str, Any]]:
    """The month's #1 (all who share the best return). Recorded once; a month already decided never changes."""
    have = db.query("SELECT * FROM leaderboard_winners WHERE month = ?", (month,))
    if have:
        return have
    top = [r for r in ranked if r["rank"] == 1]
    for r in top:
        db.execute("INSERT INTO leaderboard_winners (month, uid, username, return_pct, trades, decided_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (month, r["uid"], r["username"], r["return_pct"], r["trades"], now))
    return db.query("SELECT * FROM leaderboard_winners WHERE month = ?", (month,))


def winners(db: Any, limit_months: int = 12) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM leaderboard_winners ORDER BY month DESC, username")
    months = sorted({r["month"] for r in rows}, reverse=True)[:limit_months]
    return [{**r, "label": month_label(r["month"])} for r in rows if r["month"] in months]


def run(rt: Any, sink: Any, now: int | None = None, force: bool = False, allow_rest: bool = True) -> dict[str, Any]:
    now = now or now_ms()
    db = rt.db
    if getattr(sink, "lean", False):
        return {"skipped": "lean"}
    if not force and now - int(db.get_setting("lb_at", 0) or 0) < EVERY_S * 1000:
        return {"skipped": "not due"}
    users = _users(rt)
    if not users:
        return {"skipped": "no users cache yet"}
    db.set_setting("lb_at", now)
    own = sink.get("owner/leaderboard") or {}                                  # 1 read: exclusions + prizes awarded
    excluded = {str(x) for x in (own.get("excluded") or [])}
    names = eligible(users, now, excluded)
    month = month_key(now)
    prev_month = db.get_setting("lb_month", None)
    rollover = bool(prev_month) and prev_month != month
    seen = db.get_setting("fs_presence_seen", None) or {}                     # uid -> last_seen (sinks.refresh_member_estimate)
    cur = _entries(db, prev_month if rollover else month)

    # 1. read the accounts that may have changed (see module doc)
    todo = [uid for uid in names
            if rollover or uid not in cur or _num(seen.get(uid)) > cur[uid]["last_read_at"]
            or now - cur[uid]["last_read_at"] >= STALE_S * 1000]
    docs = {}
    for uid in todo:
        acc = sink.get(f"paper/{uid}_futures")
        if acc:
            docs[uid] = acc
    symbols = {p["symbol"] for e in cur.values() for p in (e["last"].get("positions") or [])}
    symbols |= {str(p.get("symbol")) for a in docs.values() for p in (a.get("positions") or {}).values() if isinstance(p, dict)}
    price_of = _price_fn(rt, symbols, allow_rest)
    fresh = {uid: reading(acc, price_of, now) for uid, acc in docs.items()}

    decided: list[dict[str, Any]] = []
    if rollover:
        # 2a. the reading after midnight closes the old month (members no longer eligible keep their last reading) ...
        for uid, e in cur.items():
            e2 = _apply(e, fresh[uid], now) if uid in fresh else {**e, "last": reprice(e["last"], price_of)}
            _save(db, prev_month, uid, e2)
            cur[uid] = e2
        # everyone with an entry who still has a username and is not excluded (a membership that ended at midnight
        # still counts for the month it was active in)
        old_names = {uid: str((users.get(uid) or {}).get("username") or "") for uid in cur}
        old_names = {k: v for k, v in old_names.items() if v and k not in excluded}
        ranked_old, _ = standings(prev_month, cur, old_names)
        decided = decide_winners(db, prev_month, ranked_old, now)
        # ... and opens the new one
        cur = {}
        for uid, r in fresh.items():
            e = _new_entry(r, now)
            _save(db, month, uid, e)
            cur[uid] = e
    else:
        for uid, r in fresh.items():
            e = _apply(cur.get(uid), r, now)
            _save(db, month, uid, e)
            cur[uid] = e
    db.set_setting("lb_month", month)

    # 2b. re-price the accounts not read this time (open positions move with the market)
    for uid, e in cur.items():
        if uid not in fresh and e.get("last"):
            cur[uid] = {**e, "last": reprice(e["last"], price_of)}

    ranked, scored = standings(month, cur, names)
    publish(rt, sink, month, ranked, scored, users, own, now)
    return {"month": month, "read": len(todo), "found": len(docs), "taking_part": len(scored), "ranked": len(ranked),
            "rollover": rollover, "winners": [w["username"] for w in decided]}


def member_view(month: str, ranked: list[dict[str, Any]], scored: list[dict[str, Any]], users: dict[str, dict[str, Any]],
                win: list[dict[str, Any]], now: int) -> dict[str, Any]:
    """views/leaderboard: usernames only (never uid or email)."""
    bd = badges(users)
    last = None
    if win:
        m = win[0]["month"]
        last = {"month": m, "label": month_label(m),
                "winners": [{"username": w["username"], "return_pct": w["return_pct"], "trades": w["trades"]} for w in win if w["month"] == m]}
    return {
        "month": month, "label": month_label(month), "since": month_start_ms(month), "generated_at": now,
        "min_trades": MIN_TRADES, "rules": RULES, "every_s": EVERY_S,
        "rows": [{"rank": r["rank"], "username": r["username"], "return_pct": r["return_pct"], "trades": r["trades"]} for r in ranked[:TOP_N]],
        "ranked": len(ranked), "taking_part": len(scored), "last_winner": last, "badges": bd,
    }


def admin_view(month: str, ranked: list[dict[str, Any]], scored: list[dict[str, Any]], win: list[dict[str, Any]],
               own: dict[str, Any], now: int) -> dict[str, Any]:
    ranks = {r["uid"]: r["rank"] for r in ranked}
    rows = sorted(({**s, "rank": ranks.get(s["uid"])} for s in scored),
                  key=lambda s: (s["rank"] is None, s["rank"] or 0, -s["return_pct"]))
    return {"month": month, "label": month_label(month), "generated_at": now, "min_trades": MIN_TRADES,
            "rows": rows, "winners": win, "excluded": list(own.get("excluded") or [])}


def publish(rt: Any, sink: Any, month: str, ranked: list[dict[str, Any]], scored: list[dict[str, Any]],
            users: dict[str, dict[str, Any]], own: dict[str, Any], now: int) -> None:
    win = winners(rt.db)
    sink.view("leaderboard", member_view(month, ranked, scored, users, win, now), volatile=("generated_at",))
    adm = admin_view(month, ranked, scored, win, own, now)
    digest = hashlib.sha1(dumps({k: v for k, v in adm.items() if k != "generated_at"}).encode()).hexdigest()
    if rt.db.get_setting("lb_admin_hash", None) != digest:                 # written only when it changed
        try:
            sink.set("admin/leaderboard", {"json": dumps(adm), "updated_at": now})
            rt.db.set_setting("lb_admin_hash", digest)
        except Exception as exc:                                           # quota pause: try again next hour
            if hasattr(rt, "record_error"):
                rt.record_error("leaderboard admin doc", exc)
