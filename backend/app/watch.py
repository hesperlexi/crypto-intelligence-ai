"""v2.31 fast price watch (owner, 14 Nov 2026: "why do notifications need to wait for engine? cant we do it same time?").

The engine judges calls on CLOSED 15-minute candles and runs every 5 minutes, so a "TP1 hit" push could come up to ~20
minutes after the price got there. scripts/engine_loop.py runs this module every ~30 s, also while a tick is running:
it compares the live spot price (data-api.binance.vision, the engine's own price source) with every open call's entry /
targets / stop in force and with the Hesper Challenge trade, and pushes AT ONCE ("price touched TP1").

* Notification only. It never writes the record, a bot, Hesper or Firestore documents: it opens the engine's SQLite
  file read-only, sends through app.push_send (FCM; pushes do not count against the Firestore write budget) and keeps
  what it already sent in its own small file (`watch_sent.json` next to the database).
* Same people as the engine's own push: a call event goes to the owners of the matching "My signals" / call alert rules
  that want that event (switched-off rules and events are respected); Hesper to the admin, and to the active members
  the last tick listed in setting `hesper_push_members` (only while the challenge is shown to members).
* The engine's confirmed push of the same event uses the same notification tag, so on the phone it replaces the early
  one instead of adding a second. Skipped when the engine already announced the event (alert_marks).
* The official result is still the closed candle: a very short spike can be "touched" here and not counted there.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("watch")

PRICE_URL = "https://data-api.binance.vision/api/v3/ticker/price"
SENT_FILE, STATUS_FILE = "watch_sent.json", "watch_status.json"
KEEP_MS = 7 * 86_400_000
CALL_RULES = ("ENTRY_REACHED", "TP2_REACHED", "TP3_REACHED", "SIGNAL_CLOSED", "SIGNAL_UPDATES")
LOCAL_USER = "local"
TITLES = {"entry": "Entry reached", "tp1": "TP1 hit", "tp2": "TP2 hit", "tp3": "TP3 hit", "closed": "Stop hit"}
CONFIRM = "Confirmed at the 15-minute candle close."


# ---- read-only database ----------------------------------------------------------------------------------------
class ReadOnlyDB:
    """The few reads this module needs, on a read-only connection (never blocks or changes the engine's file)."""

    def __init__(self, path: str):
        self.c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        self.c.row_factory = sqlite3.Row

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.c.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        r = self.c.execute(sql, tuple(params)).fetchone()
        return dict(r) if r else None

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM app_settings WHERE key = ?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default


def _loads(v: Any, default: Any) -> Any:
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v) if v else default
    except Exception:
        return default


def _coin(sym: str) -> str:
    return "GOLD" if str(sym).startswith("PAXG") else str(sym).split("/")[0]


def _px(v: Any) -> str:
    from .pricefmt import fmt_price
    try:
        return fmt_price(float(v))
    except (TypeError, ValueError):
        return "-"


def _reached(side: int, price: float, level: float | None, toward_profit: bool) -> bool:
    if level is None:
        return False
    d = (price - float(level)) * (1 if side > 0 else -1)
    return d >= 0 if toward_profit else d <= 0


def _tighter(side: int, a: float, b: float) -> float:
    return max(a, b) if side > 0 else min(a, b)


# ---- public calls ------------------------------------------------------------------------------------------------
def call_touches(db: Any, prices: dict[str, float]) -> list[tuple[dict[str, Any], str, str]]:
    """(call, event, body) for every level of an open call the live price has reached but the record has not yet."""
    out = []
    calls = db.query("SELECT * FROM signals WHERE status = 'OPEN' AND side != 0")
    for r in calls:
        p = prices.get(r["symbol"])
        if p is None:
            continue
        side = 1 if int(r["side"]) > 0 else -1
        adj = {a["field"]: float(a["new"]) for a in db.query(
            "SELECT field, new FROM signal_adjustments WHERE signal_id = ? ORDER BY at", (r["id"],))}
        head = f"{_coin(r['symbol'])} {str(r['timeframe']).upper()} {'LONG' if side > 0 else 'SHORT'}"
        if r.get("fill_status") == "PENDING":
            if _reached(side, p, r.get("entry"), toward_profit=False):
                out.append((r, "entry", f"{head}: price reached the entry {_px(r['entry'])}. {CONFIRM}"))
            continue
        tps = [adj.get("tp1", r.get("tp1")), r.get("tp2"), r.get("tp3")]
        for i, lvl in enumerate(tps, 1):
            if not r.get(f"tp{i}_hit") and _reached(side, p, lvl, toward_profit=True):
                out.append((r, f"tp{i}", f"{head}: price touched TP{i} {_px(lvl)}. {CONFIRM}"))
        stop, what = adj.get("stop", r.get("stop")), "the stop"
        if stop is None:
            continue
        stop = float(stop)
        if r.get("tp1_hit") and r.get("entry") is not None:
            stop, what = _tighter(side, stop, float(r["entry"])), "the break-even stop"
        if r.get("tp2_hit") and tps[0] is not None:
            stop, what = _tighter(side, stop, float(tps[0])), "the stop at TP1 (profit kept)"
        if _reached(side, p, stop, toward_profit=False):
            out.append((r, "closed", f"{head}: price touched {what} {_px(stop)}. {CONFIRM}"))
    return out


def call_messages(db: Any, prices: dict[str, float], sent: dict[str, int]) -> list[tuple[str, dict[str, str]]]:
    from .services import alerts
    touches = call_touches(db, prices)
    if not touches:
        return []
    rules = db.query(f"SELECT * FROM alerts WHERE enabled = 1 AND type IN ({','.join('?' * len(CALL_RULES))})", CALL_RULES)
    out = []
    for rule in rules:
        rule["params"] = _loads(rule.get("params"), {}) or {}
        if rule.get("last_state") != "primed":
            continue
        want = alerts._wants(rule)
        for r, ev, body in touches:
            if ev not in want or not alerts._matches(rule, r):
                continue
            key = f"{rule['id']}:{r['id']}:{ev}"
            if key in sent or db.one("SELECT 1 AS x FROM alert_marks WHERE alert_id = ? AND mark = ?",
                                     (rule["id"], f"{r['id']}:{ev}")):
                continue
            m = {"title": f"{TITLES[ev]} · {r['symbol']}", "body": body, "url": "/alerts", "tag": f"{r['id']}-{ev}"}
            if rule.get("user_id") and rule["user_id"] != LOCAL_USER:
                m["uid"] = rule["user_id"]
            out.append((key, m))
    return out


# ---- Hesper Challenge ----------------------------------------------------------------------------------------------
def hesper_messages(db: Any, prices: dict[str, float], sent: dict[str, int]) -> list[tuple[str, dict[str, str]]]:
    from .services import hesper as H
    st = db.get_setting(H.STATE_KEY, None) or {}
    if not st or st.get("idle"):
        return []
    run = st.get("run")
    head = f"Hesper Challenge · run #{run}" if run else "Hesper Challenge"
    found: list[tuple[str, str, str]] = []           # (key, tag, body)
    for q in st.get("positions") or []:
        p = prices.get(q.get("symbol"))
        if p is None:
            continue
        side = 1 if (q.get("side") or 0) > 0 else -1
        coin, name = _coin(q["symbol"]), f"{_coin(q['symbol'])} {'LONG' if side > 0 else 'SHORT'}"
        hit = int(q.get("tp_hit") or 0)
        for n, lvl in enumerate(q.get("targets") or [], 1):
            if n > hit and _reached(side, p, lvl, toward_profit=True):
                found.append((f"h:{q['id']}:tp{n}", f"hesper-{run}-tp-{coin}-{n}",
                              f"{name}: price touched TP{n} {_px(lvl)}. {CONFIRM}"))
        if q.get("stop") is not None and _reached(side, p, q["stop"], toward_profit=False):
            what = "the stop" if not hit else "the break-even stop" if hit == 1 else "the stop at TP1 (profit kept)"
            found.append((f"h:{q['id']}:stop", f"hesper-{run}-close-{coin}-",
                          f"{name}: price touched {what} {_px(q['stop'])}. The trade closes at the candle close."))
    for o in st.get("pending") or []:
        p = prices.get(o.get("symbol"))
        side = 1 if (o.get("side") or 0) > 0 else -1
        if p is not None and _reached(side, p, o.get("limit"), toward_profit=False):
            coin = _coin(o["symbol"])
            found.append((f"h:{o['id']}:fill", f"hesper-{run}-fill-{coin}-",
                          f"{coin}: price reached the entry order {_px(o['limit'])}. {CONFIRM}"))
    members = [u for u in (db.get_setting("hesper_push_members", None) or []) if isinstance(u, str)]
    out = []
    for key, tag, body in found:
        if key in sent:
            continue
        base = {"title": head, "body": body, "url": H.PUSH_URL, "tag": tag}
        out.append((key, base))
        out += [(key, {**base, "uid": u, "url": H.MEMBER_URL}) for u in members]
    return out


# ---- live prices and one pass ----------------------------------------------------------------------------------------
def _pair(sym: str) -> str:
    return sym.replace("/", "").replace("-", "").upper()


def fetch_prices(symbols: list[str]) -> dict[str, float]:
    """Last spot price per symbol ('BTC/USDT' -> 97000.1). One request; one per symbol if the batch is refused."""
    syms = sorted(set(symbols))
    if not syms:
        return {}
    from .data.futures_only import FUT_ONLY, MEXC     # v2.49 futures-only coins (MSTR/USDT): MEXC futures last price
    fut: dict[str, float] = {}
    for s in [x for x in syms if x.upper() in FUT_ONLY]:
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{MEXC}/ticker?symbol={FUT_ONLY[s.upper()]}",
                                                               headers={"User-Agent": "cia-watch"}), timeout=8) as r:
                fut[s] = float(json.load(r)["data"]["lastPrice"])
        except Exception:
            pass
    syms = [x for x in syms if x.upper() not in FUT_ONLY]
    if not syms:
        return fut

    def get(url: str) -> Any:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cia-watch"}), timeout=8) as r:
            return json.load(r)
    by_pair = {_pair(s): s for s in syms}
    try:
        rows = get(PRICE_URL + "?symbols=" + urllib.parse.quote(json.dumps(list(by_pair), separators=(",", ":"))))
    except Exception:
        rows = []
        for pr in by_pair:                         # an unknown pair makes the whole batch fail
            try:
                rows.append(get(f"{PRICE_URL}?symbol={pr}"))
            except Exception:
                pass
    return {**{by_pair[r["symbol"]]: float(r["price"]) for r in rows if r.get("symbol") in by_pair}, **fut}


def watched_symbols(db: Any) -> list[str]:
    from .services import hesper as H
    syms = [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM signals WHERE status = 'OPEN' AND side != 0")]
    st = db.get_setting(H.STATE_KEY, None) or {}
    syms += [q.get("symbol") for q in (st.get("positions") or []) + (st.get("pending") or []) if q.get("symbol")]
    return [s for s in syms if s]


def once(db: Any, sent: dict[str, int], prices: dict[str, float] | None = None, now: int | None = None
         ) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Messages to send now, and the updated 'already sent' map (keys older than KEEP_MS dropped)."""
    now = int(time.time() * 1000) if now is None else now
    if prices is None:
        prices = fetch_prices(watched_symbols(db))
    pairs = call_messages(db, prices, sent) + hesper_messages(db, prices, sent)
    sent = {k: v for k, v in sent.items() if now - int(v) < KEEP_MS}
    for k, _ in pairs:
        sent[k] = now
    return [m for _, m in pairs], sent


def send(messages: list[dict[str, str]]) -> dict[str, Any]:
    if not messages:
        return {"sent": 0}
    p = subprocess.run([sys.executable, "-m", "app.push_send"], input=json.dumps(messages), capture_output=True,
                       text=True, timeout=60)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        return {"sent": 0, "error": (p.stderr or "no result")[-200:]}


def main() -> None:
    from .config import settings
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        return
    path = url.replace("sqlite:///", "")
    if not os.path.exists(path):
        return
    sent_path = Path(path).parent / SENT_FILE
    try:
        sent = json.loads(sent_path.read_text()) if sent_path.exists() else {}
    except Exception:
        sent = {}
    db = ReadOnlyDB(path)
    syms = watched_symbols(db)
    prices = fetch_prices(syms)
    msgs, sent = once(db, sent, prices)
    res: dict[str, Any] = {}
    if msgs:
        res = send(msgs)
        print(f"watch: {len(msgs)} early notification(s): {json.dumps(res)[:300]}", flush=True)
    status_path = Path(path).parent / STATUS_FILE    # read by the tick into Health (engine.watch_*)
    try:
        st = json.loads(status_path.read_text()) if status_path.exists() else {}
    except Exception:
        st = {}
    st = {"at": int(time.time() * 1000), "coins": len(set(syms)), "priced": len(prices),
          "sent_total": int(st.get("sent_total") or 0) + len(msgs), "last_error": (res.get("error") or None) if msgs else st.get("last_error")}
    status_path.write_text(json.dumps(st))
    tmp = sent_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sent))
    tmp.replace(sent_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:                      # never noisy: the next pass tries again
        print(f"watch: skipped ({type(exc).__name__}: {str(exc)[:160]})", flush=True)
