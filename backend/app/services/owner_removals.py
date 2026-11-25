"""Owner-requested removals of specific calls (testing mode). Owner, 25 Nov 2026: "we were fixing that coin and this
happened, so let's remove this trade - we are in testing mode - so it's ok" + "the other Anthropic entry remove it
from data": the two ANTHROPIC/USDT calls published on 25 Nov 2026 (Dubai) are taken out of the record, the bots'
books and both challenges, and the balances set back as if they had not been taken. This is an explicit owner
exception to the ground rule (losing trades are never removed); nothing is truly deleted: every removed row is copied
to a `removed_*` table with the reason first. Runs once (flag in worker.MIGRATION_FLAGS)."""
from __future__ import annotations

from typing import Any

from ..db import dumps, loads, now_ms

REASON = "owner removal 25 Nov 2026 (testing mode, Anthropic calls)"
SYMBOL = "ANTHROPIC/USDT"
FROM_MS, TO_MS = 1795550400000, 1795633200000      # 25 Nov 2026 00:00 -> 23:00 Dubai


def _keep(db: Any, table: str, src: str, row: dict[str, Any]) -> None:
    db.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, source TEXT, removed_at INTEGER, reason TEXT, row TEXT)")
    db.execute(f"INSERT INTO {table} (id, source, removed_at, reason, row) VALUES (?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
               (f"{src}:{row.get('id')}", src, now_ms(), REASON, dumps(row)))


def remove_anthropic_25nov(rt: Any) -> dict[str, Any]:
    db = rt.db
    calls = db.query("SELECT * FROM signals WHERE symbol = ? AND side != 0 AND created_at >= ? AND created_at < ?",
                     (SYMBOL, FROM_MS, TO_MS))
    out: dict[str, Any] = {"calls": [], "bot_trades": [], "challenge": []}
    ids = {c["id"] for c in calls}
    for c in calls:
        _keep(db, "removed_record", "signals", c)
        db.execute("DELETE FROM signals WHERE id = ?", (c["id"],))
        out["calls"].append({"tf": c["timeframe"], "status": c["status"]})
    # bots: trades / open positions taken from these calls (same coin, side, timeframe, opened around the call)
    for row in db.query("SELECT id, config, state FROM bots"):
        cfg, state = loads(row["config"], {}), loads(row["state"], {})
        for c in calls:
            if cfg.get("timeframe") != c["timeframe"]:
                continue
            lo, hi = int(c["created_at"]) - 15 * 60_000, int(c["created_at"]) + 30 * 60_000
            for t in db.query("SELECT * FROM bot_trades WHERE bot_id = ? AND symbol = ? AND side = ? AND opened_at BETWEEN ? AND ?",
                              (cfg["id"], SYMBOL, int(c["side"]), lo, hi)):
                pnl = float(t["pnl"] or 0.0)
                _keep(db, "removed_bot_trades", cfg["id"], t)
                db.execute("DELETE FROM bot_trades WHERE id = ?", (t["id"],))
                state["cash"] = float(state.get("cash", 0.0)) - pnl
                db.execute("UPDATE bot_equity SET equity = equity - ? WHERE bot_id = ? AND ts >= ?", (pnl, cfg["id"], int(t["closed_at"])))
                out["bot_trades"].append({"bot": cfg["id"], "pnl": round(pnl, 2)})
            for p in list(state.get("positions") or []):
                if p.get("symbol") == SYMBOL and lo <= int(p.get("opened_at") or 0) <= hi:
                    share = float(p.get("qty_open") or 0.0) / float(p.get("qty") or 1.0)
                    state["cash"] = float(state.get("cash", 0.0)) + float(p.get("margin") or 0.0) * share - float(p.get("realized") or 0.0)
                    state["positions"].remove(p)
                    out["bot_trades"].append({"bot": cfg["id"], "open_position_removed": True})
        db.execute("UPDATE bots SET state = ? WHERE id = ?", (dumps(state), row["id"]))
    # both challenges: trades from these calls; later trades of the same run and the balance shifted back
    from .hesper import Hesper, LastStand
    for cls in (Hesper, LastStand):
        st = dict(db.get_setting(cls.STATE_KEY, None) or {})
        try:
            trades = db.query(f"SELECT * FROM {cls.TRADES} WHERE symbol = ? AND opened_at >= ? AND opened_at < ?",
                              (SYMBOL, FROM_MS, TO_MS))
        except Exception:
            trades = []
        for t in trades:
            if t.get("signal_id") and t["signal_id"] not in ids:
                continue
            pnl, run = float(t["pnl"] or 0.0), int(t["run"])
            _keep(db, "removed_challenge_trades", cls.BOT_ID, t)
            db.execute(f"DELETE FROM {cls.TRADES} WHERE id = ?", (t["id"],))
            db.execute(f"UPDATE {cls.TRADES} SET balance_before = balance_before - ?, balance_after = balance_after - ? "
                       f"WHERE run = ? AND closed_at > ?", (pnl, pnl, run, int(t["closed_at"])))
            r = db.one(f"SELECT trades, wins FROM {cls.RUNS} WHERE run = ?", (run,))
            if r:
                db.execute(f"UPDATE {cls.RUNS} SET trades = ?, wins = ? WHERE run = ?",
                           (max(0, int(r["trades"] or 0) - 1), max(0, int(r["wins"] or 0) - (1 if pnl > 0 else 0)), run))
            if st and int(st.get("run") or 0) == run:
                st["cash"] = float(st.get("cash", 0.0)) - pnl
                st["trades"] = max(0, int(st.get("trades", 0)) - 1)
                st["wins"] = max(0, int(st.get("wins", 0)) - (1 if pnl > 0 else 0))
                if "equity" in st:
                    st["equity"] = float(st["equity"]) - pnl
                st["taken"] = [x for x in (st.get("taken") or []) if x not in ids]
            out["challenge"].append({"who": cls.BOT_ID, "run": run, "pnl": round(pnl, 2)})
        if st:
            db.set_setting(cls.STATE_KEY, st)
    return out


def remove_paxg_bot_trade_24nov(rt: Any) -> list[dict[str, Any]]:
    """Owner, 25 Nov 2026 (testing mode): the 15m bot's PAXG trade opened 24 Nov 20:29 Dubai (break-even stop, made
    with the bot's old targets before it mirrored the record) is removed; cash and later equity points set back."""
    db = rt.db
    out = []
    for t in db.query("SELECT * FROM bot_trades WHERE bot_id = 'futures-signal-ab-15m' AND symbol = 'PAXG/USDT' "
                      "AND exit_reason = 'breakeven stop' AND opened_at BETWEEN 1795537200000 AND 1795538400000"):
        pnl = float(t["pnl"] or 0.0)
        _keep(db, "removed_bot_trades", t["bot_id"], t)
        db.execute("DELETE FROM bot_trades WHERE id = ?", (t["id"],))
        row = db.one("SELECT id, state FROM bots WHERE id = ?", (t["bot_id"],))
        if row:
            st = loads(row["state"], {})
            st["cash"] = float(st.get("cash", 0.0)) - pnl
            db.execute("UPDATE bots SET state = ? WHERE id = ?", (dumps(st), row["id"]))
        db.execute("UPDATE bot_equity SET equity = equity - ? WHERE bot_id = ? AND ts >= ?", (pnl, t["bot_id"], int(t["closed_at"])))
        out.append({"bot": t["bot_id"], "pnl": round(pnl, 2)})
    return out
