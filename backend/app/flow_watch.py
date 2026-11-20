"""v2.62 order-flow recorder + "big money" alerts (owner, 20 Nov 2026: "utilise the resources and data ... precise, high
probability"; "a big whale activates ... the AI should notify").

scripts/engine_loop.py runs this module every ~20 s in a background thread (like app.watch). Per watched coin that has
an OKX USDT perpetual (Binance futures is geo-blocked on the runners; OKX public market data is free, no key):

* trades   GET /api/v5/market/trades (newest 500) -> 5-minute buckets: taker-buy USD, taker-sell USD, whale buy / sell
           USD (trades >= the coin's whale size), whale count, largest trade, and `gaps` (a pass that could not reach
           back to the last trade it saw = some trades missed; recorded honestly so a later test can drop those buckets)
* book     GET /api/v5/market/books (400 levels) every ~2 min -> resting bid / ask USD within 0.5 / 1 / 2 % of the mid,
           and the biggest bid / ask wall (price, USD)
* liqs     GET /api/v5/public/liquidation-orders (filled) every ~1 min -> forced-close USD per bucket, longs / shorts

Everything goes to its OWN SQLite file `flow.db` next to the engine database (cached and backed up with it), so this
thread never locks the engine's database; the engine database is only opened read-only (watchlist, alert rules).
Nothing here changes a call, a bot or the record. The stored buckets are research data: features are tested later
(`known_at` = bucket end, no look-ahead) and switched on only where they improve unseen results, like every add-on.

Big-money alerts (push only, members who switched on the "Big money moves" alert, type BIG_MONEY):
* whale burst  whale net (buy - sell) over the last 5 min >= BURST_X x the coin's whale size AND >= BURST_MED x the
               median |whale net| of its last 24 h of buckets, with >= MIN_WHALES whale trades
* wipe-out     forced closes over the last 5 min >= max(LIQ_MIN_X x whale size, LIQ_MED x the 24 h average per 5 min)
One per coin per kind per COOLDOWN_MS. Wording describes what happened, never a prediction. Every alert is stored with
the price then, and the price 15 min / 1 h / 4 h later is filled in, so how often the price followed can be measured
(`stats()`), and shown only once there are enough of them.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("flow")

OKX = "https://www.okx.com"
DB_FILE, STATE_FILE = "flow.db", "flow_state.json"
BUCKET_MS = 5 * 60_000
DAY_MS = 86_400_000
KEEP_DAYS = 120
BOOK_EVERY_MS = 110_000
LIQ_EVERY_MS = 55_000
TICKERS_EVERY_MS = 10 * 60_000
WHALE_MIN, WHALE_MAX, WHALE_SHARE = 25_000.0, 500_000.0, 2e-5      # whale = clamp(24 h volume x share, min, max)
BURST_X, BURST_MED, MIN_WHALES = 8.0, 6.0, 3
LIQ_MIN_X, LIQ_MED = 10.0, 6.0
COOLDOWN_MS = 45 * 60_000
HORIZONS = {"p15": 15 * 60_000, "p60": 60 * 60_000, "p240": 240 * 60_000}
PASS_BUDGET_S = 15.0
ALERT_TYPE = "BIG_MONEY"
ALL_SYMBOLS = "ALL/USDT"

SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_5m (coin TEXT, ts INTEGER, buy REAL DEFAULT 0, sell REAL DEFAULT 0, wbuy REAL DEFAULT 0,
  wsell REAL DEFAULT 0, nw INTEGER DEFAULT 0, ntr INTEGER DEFAULT 0, maxtr REAL DEFAULT 0, gaps INTEGER DEFAULT 0,
  last_px REAL, PRIMARY KEY (coin, ts));
CREATE TABLE IF NOT EXISTS book_5m (coin TEXT, ts INTEGER, mid REAL, bid05 REAL, ask05 REAL, bid1 REAL, ask1 REAL,
  bid2 REAL, ask2 REAL, wall_bid_px REAL, wall_bid REAL, wall_ask_px REAL, wall_ask REAL, PRIMARY KEY (coin, ts));
CREATE TABLE IF NOT EXISTS liq_5m (coin TEXT, ts INTEGER, long_usd REAL DEFAULT 0, short_usd REAL DEFAULT 0,
  n INTEGER DEFAULT 0, PRIMARY KEY (coin, ts));
CREATE TABLE IF NOT EXISTS flow_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT, kind TEXT, dir INTEGER,
  at INTEGER, price REAL, size_usd REAL, ratio REAL, msg TEXT, p15 REAL, p60 REAL, p240 REAL);
CREATE INDEX IF NOT EXISTS flow_alerts_at ON flow_alerts (at);
"""


# ---- small helpers ----------------------------------------------------------------------------------------------
def bucket(ts: int) -> int:
    return int(ts) // BUCKET_MS * BUCKET_MS


def coin_of(symbol: str) -> str:
    s = str(symbol).upper().split("/")[0]
    return "PAXG" if s == "PAXG" else s


def inst(coin: str) -> str:
    return f"{coin}-USDT-SWAP"


def fmt_usd(v: float) -> str:
    v = abs(float(v))
    return f"${v / 1e9:.2f}B" if v >= 1e9 else f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K" if v >= 1e3 else f"${v:.0f}"


def name_of(coin: str) -> str:
    return "Gold (PAXG)" if coin == "PAXG" else coin


def whale_size(vol24: float | None) -> float:
    if not vol24 or vol24 <= 0:
        return WHALE_MIN
    return max(WHALE_MIN, min(WHALE_MAX, float(vol24) * WHALE_SHARE))


# ---- parsing (pure, tested) ----------------------------------------------------------------------------------------
def parse_trades(rows: list[dict], ct_val: float, last_id: int | None, whale: float
                 ) -> tuple[dict[int, dict[str, float]], int | None, bool, float | None]:
    """OKX trades (newest first) -> per-bucket sums of trades newer than last_id, the newest id, whether the batch did
    NOT reach back to last_id (a gap), and the newest price."""
    out: dict[int, dict[str, float]] = {}
    newest, px, oldest = last_id, None, None
    for r in rows:
        try:
            tid, p, sz, ts = int(r["tradeId"]), float(r["px"]), float(r["sz"]), int(r["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        oldest = tid if oldest is None else min(oldest, tid)
        if newest is None or tid > newest:
            newest = tid
        if px is None:
            px = p
        if last_id is not None and tid <= last_id:
            continue
        usd = p * sz * ct_val
        b = out.setdefault(bucket(ts), {"buy": 0.0, "sell": 0.0, "wbuy": 0.0, "wsell": 0.0, "nw": 0, "ntr": 0, "maxtr": 0.0, "last_px": p})
        side = "buy" if r.get("side") == "buy" else "sell"
        b[side] += usd
        b["ntr"] += 1
        b["maxtr"] = max(b["maxtr"], usd)
        if usd >= whale:
            b["w" + side] += usd
            b["nw"] += 1
    gap = last_id is not None and oldest is not None and oldest > last_id + 1 and len(rows) >= 450
    return out, newest, gap, px


def parse_book(d: dict, ct_val: float) -> dict[str, float] | None:
    """OKX books -> depth in USD within 0.5 / 1 / 2 % of the mid and the biggest wall on each side (within 2 %)."""
    try:
        bids = [(float(x[0]), float(x[1]) * float(x[0]) * ct_val) for x in d["bids"]]
        asks = [(float(x[0]), float(x[1]) * float(x[0]) * ct_val) for x in d["asks"]]
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if not bids or not asks:
        return None
    mid = (bids[0][0] + asks[0][0]) / 2
    out: dict[str, float] = {"mid": mid}
    for name, pct in (("05", 0.005), ("1", 0.01), ("2", 0.02)):
        out["bid" + name] = sum(u for p, u in bids if p >= mid * (1 - pct))
        out["ask" + name] = sum(u for p, u in asks if p <= mid * (1 + pct))
    wb = max((x for x in bids if x[0] >= mid * 0.98), key=lambda x: x[1], default=(None, 0.0))
    wa = max((x for x in asks if x[0] <= mid * 1.02), key=lambda x: x[1], default=(None, 0.0))
    out.update(wall_bid_px=wb[0], wall_bid=wb[1], wall_ask_px=wa[0], wall_ask=wa[1])
    return out


def parse_liqs(rows: list[dict], ct_val: float, since: int) -> tuple[dict[int, dict[str, float]], int]:
    """OKX liquidation-orders data -> per-bucket long / short USD of fills after `since`; returns the newest ts."""
    out: dict[int, dict[str, float]] = {}
    newest = since
    for blk in rows or []:
        for d in blk.get("details") or []:
            try:
                ts, sz, px = int(d["ts"]), float(d["sz"]), float(d.get("bkPx") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if ts <= since or px <= 0:
                continue
            newest = max(newest, ts)
            usd = sz * ct_val * px
            b = out.setdefault(bucket(ts), {"long_usd": 0.0, "short_usd": 0.0, "n": 0})
            b["long_usd" if d.get("posSide") == "long" or d.get("side") == "sell" else "short_usd"] += usd
            b["n"] += 1
    return out, newest


# ---- storage ---------------------------------------------------------------------------------------------------------
class FlowDB:
    def __init__(self, path: str):
        self.c = sqlite3.connect(path, timeout=10)
        self.c.row_factory = sqlite3.Row
        self.c.executescript(SCHEMA)

    def add_trades(self, coin: str, buckets: dict[int, dict[str, float]], gap: bool) -> None:
        for ts, b in buckets.items():
            self.c.execute(
                "INSERT INTO flow_5m (coin, ts, buy, sell, wbuy, wsell, nw, ntr, maxtr, last_px) VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT (coin, ts) DO UPDATE SET buy = buy + excluded.buy, sell = sell + excluded.sell, "
                "wbuy = wbuy + excluded.wbuy, wsell = wsell + excluded.wsell, nw = nw + excluded.nw, ntr = ntr + excluded.ntr, "
                "maxtr = MAX(maxtr, excluded.maxtr), last_px = excluded.last_px",
                (coin, ts, b["buy"], b["sell"], b["wbuy"], b["wsell"], b["nw"], b["ntr"], b["maxtr"], b.get("last_px")))
        if gap and buckets:
            self.c.execute("UPDATE flow_5m SET gaps = gaps + 1 WHERE coin = ? AND ts = ?", (coin, min(buckets)))

    def add_book(self, coin: str, ts: int, b: dict[str, float]) -> None:
        self.c.execute("INSERT OR REPLACE INTO book_5m VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (coin, bucket(ts), b["mid"], b["bid05"], b["ask05"], b["bid1"], b["ask1"], b["bid2"], b["ask2"],
                        b["wall_bid_px"], b["wall_bid"], b["wall_ask_px"], b["wall_ask"]))

    def add_liqs(self, coin: str, buckets: dict[int, dict[str, float]]) -> None:
        for ts, b in buckets.items():
            self.c.execute("INSERT INTO liq_5m (coin, ts, long_usd, short_usd, n) VALUES (?,?,?,?,?) ON CONFLICT (coin, ts) "
                           "DO UPDATE SET long_usd = long_usd + excluded.long_usd, short_usd = short_usd + excluded.short_usd, "
                           "n = n + excluded.n", (coin, ts, b["long_usd"], b["short_usd"], b["n"]))

    def rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.c.execute(sql, params).fetchall()]

    def prune(self, now: int) -> None:
        cut = now - KEEP_DAYS * DAY_MS
        for t in ("flow_5m", "book_5m", "liq_5m"):
            self.c.execute(f"DELETE FROM {t} WHERE ts < ?", (cut,))

    def commit(self) -> None:
        self.c.commit()


# ---- big-money detection (pure on stored rows, tested) -----------------------------------------------------------
def detect(db: FlowDB, coin: str, now: int, whale: float) -> list[dict[str, Any]]:
    """Bursts on the last two buckets (the current one is still filling) vs the coin's last 24 h."""
    cur = bucket(now)
    recent = db.rows("SELECT * FROM flow_5m WHERE coin = ? AND ts >= ?", (coin, cur - BUCKET_MS))
    hist = db.rows("SELECT wbuy, wsell FROM flow_5m WHERE coin = ? AND ts >= ? AND ts < ?", (coin, cur - DAY_MS, cur - BUCKET_MS))
    out: list[dict[str, Any]] = []
    wb, ws = sum(r["wbuy"] for r in recent), sum(r["wsell"] for r in recent)
    nw = sum(r["nw"] for r in recent)
    net = wb - ws
    med = statistics.median([abs(r["wbuy"] - r["wsell"]) for r in hist]) if len(hist) >= 24 else None
    if med is not None and nw >= MIN_WHALES and abs(net) >= BURST_X * whale and abs(net) >= BURST_MED * max(med, whale * 0.25):
        out.append({"kind": "whales", "dir": 1 if net > 0 else -1, "size": abs(net), "ratio": abs(net) / max(med, 1.0),
                    "buy": wb, "sell": ws, "n": nw})
    lq = db.rows("SELECT long_usd, short_usd, ts FROM liq_5m WHERE coin = ? AND ts >= ?", (coin, cur - DAY_MS))
    if len(hist) >= 24:
        rec = [r for r in lq if r["ts"] >= cur - BUCKET_MS]
        lo, sh = sum(r["long_usd"] for r in rec), sum(r["short_usd"] for r in rec)
        avg = sum(r["long_usd"] + r["short_usd"] for r in lq if r["ts"] < cur - BUCKET_MS) / max(1, DAY_MS // BUCKET_MS - 2)
        tot = lo + sh
        if tot >= max(LIQ_MIN_X * whale, LIQ_MED * avg) and tot > 0:
            # longs wiped = forced selling (price pushed down); shorts wiped = forced buying
            out.append({"kind": "wipeout", "dir": -1 if lo >= sh else 1, "size": tot, "ratio": tot / max(avg, 1.0),
                        "long": lo, "short": sh})
    return out


def message(coin: str, a: dict[str, Any]) -> tuple[str, str]:
    n = name_of(coin)
    if a["kind"] == "whales":
        side = "buyers" if a["dir"] > 0 else "sellers"
        body = (f"Big {side} active on {n}: {fmt_usd(a['buy'])} bought vs {fmt_usd(a['sell'])} sold in large trades over "
                f"the last 5-10 minutes ({a['n']} big trades, about {a['ratio']:.0f}x a normal 5 minutes). "
                "This shows what is happening now; it is not a forecast.")
        return f"Big money {'buying' if a['dir'] > 0 else 'selling'} · {n}", body
    who = "rise-bets (longs)" if a["dir"] < 0 else "fall-bets (shorts)"
    body = (f"Wave of forced closes on {n}: {fmt_usd(a['size'])} of {who} wiped out in the last 5-10 minutes "
            f"(longs {fmt_usd(a.get('long', 0))}, shorts {fmt_usd(a.get('short', 0))}). Moves can speed up while this lasts. "
            "Not a forecast.")
    return f"Forced closes · {n}", body


def fill_outcomes(db: FlowDB, now: int, prices: dict[str, float]) -> int:
    """Price 15 min / 1 h / 4 h after each alert (the newest trade price we saw at that time or later)."""
    n = 0
    for a in db.rows("SELECT * FROM flow_alerts WHERE p240 IS NULL AND at >= ?", (now - 2 * DAY_MS,)):
        for col, ms in HORIZONS.items():
            if a[col] is None and now >= a["at"] + ms:
                row = db.rows("SELECT last_px FROM flow_5m WHERE coin = ? AND ts >= ? AND last_px IS NOT NULL ORDER BY ts LIMIT 1",
                              (a["coin"], bucket(a["at"] + ms)))
                px = row[0]["last_px"] if row else prices.get(a["coin"])
                if px:
                    db.c.execute(f"UPDATE flow_alerts SET {col} = ? WHERE id = ?", (px, a["id"]))
                    n += 1
    return n


def stats(db: FlowDB, since: int = 0) -> dict[str, Any]:
    """How often the price moved the way the alert's flow pointed, per kind and horizon (needs the outcomes)."""
    out: dict[str, Any] = {}
    for kind in ("whales", "wipeout"):
        rows = db.rows("SELECT * FROM flow_alerts WHERE kind = ? AND at >= ?", (kind, since))
        k: dict[str, Any] = {"alerts": len(rows)}
        for col in HORIZONS:
            done = [r for r in rows if r[col] and r["price"]]
            if done:
                follow = [((r[col] - r["price"]) * r["dir"]) > 0 for r in done]
                move = [((r[col] - r["price"]) / r["price"]) * 100 * r["dir"] for r in done]
                k[col] = {"n": len(done), "followed_pct": round(100 * sum(follow) / len(done), 1),
                          "avg_move_pct": round(sum(move) / len(move), 3)}
        out[kind] = k
    return out


# ---- network ---------------------------------------------------------------------------------------------------------
def _get(path: str, params: dict | None = None) -> Any:
    url = OKX + path + ("?" + urllib.parse.urlencode(params) if params else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cia-flow"}), timeout=8) as r:
        d = json.load(r)
    if str(d.get("code")) not in ("0", ""):
        raise RuntimeError(f"okx {d.get('code')}: {str(d.get('msg'))[:80]}")
    return d.get("data")


def _read_engine(path: str) -> tuple[list[str], list[dict[str, Any]], dict[str, float]]:
    """Watchlist coins, BIG_MONEY rules and OKX contract values from the engine database (read-only)."""
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        syms = [r["symbol"] for r in c.execute("SELECT symbol FROM watchlists").fetchall()]
        rules = [dict(r) for r in c.execute("SELECT * FROM alerts WHERE enabled = 1 AND type = ?", (ALERT_TYPE,)).fetchall()]
        row = c.execute("SELECT value FROM app_settings WHERE key = 'mkt_okx_support'").fetchone()
        ct = (json.loads(row["value"]) or {}).get("ct_val") or {} if row else {}
    finally:
        c.close()
    return sorted({coin_of(s) for s in syms}), rules, {k.upper(): float(v) for k, v in ct.items()}


def audience(rules: list[dict[str, Any]], coin: str) -> list[str | None]:
    """uids of the members whose BIG_MONEY rule covers this coin (None = the owner's local rule)."""
    out: list[str | None] = []
    for r in rules:
        sym = str(r.get("symbol") or "")
        if sym not in (ALL_SYMBOLS, f"{coin}/USDT"):
            continue
        uid = r.get("user_id")
        uid = None if not uid or uid == "local" else uid
        if uid not in out:
            out.append(uid)
    return out


def run_pass(engine_path: str, now: int | None = None) -> dict[str, Any]:
    now = int(time.time() * 1000) if now is None else now
    t0 = time.time()
    folder = Path(engine_path).parent
    st_path = folder / STATE_FILE
    try:
        st = json.loads(st_path.read_text()) if st_path.exists() else {}
    except Exception:
        st = {}
    coins, rules, ct = _read_engine(engine_path)
    db = FlowDB(str(folder / DB_FILE))
    last_ids: dict[str, int] = st.get("last_id") or {}
    vols: dict[str, float] = st.get("vol24") or {}
    prices: dict[str, float] = {}
    errors: list[str] = []
    if now - int(st.get("tickers_at") or 0) >= TICKERS_EVERY_MS:
        try:
            for t in _get("/api/v5/market/tickers", {"instType": "SWAP"}) or []:
                iid = str(t.get("instId", ""))
                if iid.endswith("-USDT-SWAP"):
                    vols[iid.split("-")[0]] = float(t.get("volCcy24h") or 0) * float(t.get("last") or 0)
            st["tickers_at"] = now
        except Exception as exc:
            errors.append(f"tickers {type(exc).__name__}")
    live = [c for c in coins if c in ct and c in vols]
    do_book = now - int(st.get("book_at") or 0) >= BOOK_EVERY_MS
    do_liq = now - int(st.get("liq_at") or 0) >= LIQ_EVERY_MS
    liq_since: dict[str, int] = st.get("liq_since") or {}
    for coin in live:
        if time.time() - t0 > PASS_BUDGET_S:
            break
        w = whale_size(vols.get(coin))
        try:
            rows = _get("/api/v5/market/trades", {"instId": inst(coin), "limit": 500}) or []
            b, newest, gap, px = parse_trades(rows, ct[coin], last_ids.get(coin), w)
            if last_ids.get(coin) is not None:          # the first pass only sets the starting point
                db.add_trades(coin, b, gap)
            if newest is not None:
                last_ids[coin] = newest
            if px:
                prices[coin] = px
            if do_book:
                bk = parse_book((_get("/api/v5/market/books", {"instId": inst(coin), "sz": 400}) or [{}])[0], ct[coin])
                if bk:
                    db.add_book(coin, now, bk)
            if do_liq:
                data = _get("/api/v5/public/liquidation-orders", {"instType": "SWAP", "uly": f"{coin}-USDT", "state": "filled", "limit": 100})
                lb, newest_l = parse_liqs(data or [], ct[coin], int(liq_since.get(coin) or now - BUCKET_MS))
                db.add_liqs(coin, lb)
                liq_since[coin] = newest_l
        except Exception as exc:
            errors.append(f"{coin} {type(exc).__name__}")
    st.update(last_id=last_ids, vol24=vols, liq_since=liq_since)
    if do_book:
        st["book_at"] = now
    if do_liq:
        st["liq_at"] = now
    # alerts
    cool: dict[str, int] = st.get("cool") or {}
    messages: list[dict[str, str]] = []
    for coin in live:
        for a in detect(db, coin, now, whale_size(vols.get(coin))):
            key = f"{coin}:{a['kind']}"
            if now - int(cool.get(key) or 0) < COOLDOWN_MS:
                continue
            cool[key] = now
            title, body = message(coin, a)
            db.c.execute("INSERT INTO flow_alerts (coin, kind, dir, at, price, size_usd, ratio, msg) VALUES (?,?,?,?,?,?,?,?)",
                         (coin, a["kind"], a["dir"], now, prices.get(coin), a["size"], a["ratio"], body))
            for uid in audience(rules, coin):
                m = {"title": title, "body": body, "url": "/flow", "tag": f"flow-{coin}-{a['kind']}"}
                if uid:
                    m["uid"] = uid
                messages.append(m)
    st["cool"] = {k: v for k, v in cool.items() if now - int(v) < DAY_MS}
    fill_outcomes(db, now, prices)
    if now - int(st.get("pruned_at") or 0) > DAY_MS:
        db.prune(now)
        st["pruned_at"] = now
    db.commit()
    st.update(at=now, coins=len(live), errors=errors[-5:], passes=int(st.get("passes") or 0) + 1)
    tmp = st_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    tmp.replace(st_path)
    return {"coins": len(live), "messages": messages, "errors": errors}


def main() -> None:
    from .config import settings
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        return
    path = url.replace("sqlite:///", "")
    if not os.path.exists(path):
        return
    res = run_pass(path)
    if res["messages"]:
        from .watch import send
        out = send(res["messages"])
        print(f"flow: {len(res['messages'])} big-money push(es): {json.dumps(out)[:200]}", flush=True)
    if res["errors"]:
        print(f"flow: {len(res['errors'])} error(s): {', '.join(res['errors'][:3])}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"flow: skipped ({type(exc).__name__}: {str(exc)[:160]})", flush=True)
