"""Read-only check (owner, 26 Nov 2026: "the 5 trades I asked you to remove were taken again, with no new-signal alert").

python -m app.diag_removed --out x.json. Times, timeframes and states only (no coin, side or levels: the result is public)."""
from __future__ import annotations

import argparse
import json

from .db import Database, loads
from .services.owner_removals import UPDATES_FROM_MS


def run(db: Database) -> dict:
    out: dict = {"flag": db.get_setting("remove_waiting_ena_26nov_v31", None)}
    try:
        removed = db.query("SELECT id, removed_at, row FROM removed_record WHERE removed_at >= ?", (UPDATES_FROM_MS,))
    except Exception:
        removed = []
    rem = {}
    for r in removed:
        row = loads(r["row"], {}) or {}
        rem[row.get("id")] = {"removed_at": r["removed_at"], "symbol": row.get("symbol"), "tf": row.get("timeframe"),
                              "bar_ts": row.get("bar_ts"), "created_at": row.get("created_at")}
    out["removed"] = [{"tf": v["tf"], "created_at": v["created_at"], "removed_at": v["removed_at"]} for v in rem.values()]
    calls = db.query("SELECT id, symbol, timeframe, bar_ts, created_at, fill_status, filled_at, status, closed_at, payload "
                     "FROM signals WHERE side != 0 AND created_at >= ? ORDER BY created_at", (UPDATES_FROM_MS,))
    rows = []
    for c in calls:
        same_id = c["id"] in rem
        same_coin = [v for v in rem.values() if v["symbol"] == c["symbol"] and v["tf"] == c["timeframe"]]
        try:
            news = db.query("SELECT type, created_at FROM alert_events WHERE symbol = ? AND created_at >= ? AND created_at <= ?",
                            (c["symbol"], int(c["created_at"]) - 60_000, int(c["created_at"]) + 30 * 60_000))
        except Exception:
            news = []
        pl = loads(c["payload"], {}) or {}
        rows.append({"n": len(rows) + 1, "tf": c["timeframe"], "created_at": c["created_at"], "fill": c["fill_status"],
                     "filled_at": c["filled_at"], "status": c["status"], "closed_at": c["closed_at"],
                     "same_id_as_removed": same_id,
                     "same_coin_tf_as_removed": bool(same_coin),
                     "same_candle_as_removed": any(v["bar_ts"] == c["bar_ts"] for v in same_coin),
                     "minutes_after_removal": round((int(c["created_at"]) - min(v["removed_at"] for v in same_coin)) / 60000, 1) if same_coin else None,
                     "entry_mode": (pl.get("entry_rule") or {}).get("mode"),
                     "alert_events_near_publication": sorted({e["type"] for e in news}),
                     "alert_events_n": len(news)})
    out["calls_since_cutoff"] = rows
    for tbl in ("hesper_trades", "laststand_trades"):
        try:
            out[tbl] = db.query(f"SELECT opened_at, closed_at FROM {tbl} WHERE opened_at >= ? ORDER BY opened_at", (UPDATES_FROM_MS,))
        except Exception as e:
            out[tbl] = str(e)
    for key in ("hesper_state", "laststand_state"):
        st = db.get_setting(key, {}) or {}
        out[key] = {"open": [{"opened_at": p.get("opened_at"), "signal_in_record": (p.get("info") or {}).get("signal_id") in {c["id"] for c in calls},
                              "signal_was_removed": (p.get("info") or {}).get("signal_id") in rem}
                             for p in st.get("positions") or []],
                    "pending": len(st.get("pending") or [])}
    bots = []
    for b in db.query("SELECT id, state FROM bots"):
        st = loads(b["state"], {}) or {}
        for p in st.get("positions") or []:
            if int(p.get("opened_at") or 0) >= UPDATES_FROM_MS:
                sid = (p.get("info") or {}).get("signal_id")
                bots.append({"bot_tf": b["id"].split("-")[-1], "opened_at": p.get("opened_at"),
                             "signal_in_record": sid in {c["id"] for c in calls}, "signal_was_removed": sid in rem})
    out["bot_positions_since_cutoff"] = bots
    try:
        out["state_newest_signal"] = (db.one("SELECT MAX(created_at) AS t FROM signals") or {}).get("t")
    except Exception as e:
        out["state_newest_signal"] = str(e)
    try:
        out["state_newest_prediction"] = (db.one("SELECT MAX(created_at) AS t FROM predictions") or {}).get("t")
    except Exception as e:
        out["state_newest_prediction"] = str(e)
    # what the engine decided on each removed coin / timeframe after the removal (rule names only)
    seen = []
    for v in rem.values():
        try:
            ds = db.query("SELECT ts, rule FROM decisions WHERE symbol = ? AND timeframe = ? AND ts >= ? ORDER BY ts",
                          (v["symbol"], v["tf"], v["removed_at"]))
        except Exception:
            ds = []
        seen.append({"tf": v["tf"], "after_removal": [{"ts": d["ts"], "rule": d["rule"]} for d in ds][-12:]})
    out["decisions_after_removal"] = seen
    # phone notifications sent by the ticks of the last 4 hours (counts and error types only)
    pushes = []
    try:
        newest = int((db.one("SELECT MAX(started_at) AS t FROM engine_runs WHERE kind = 'tick'") or {}).get("t") or 0)
        for r in db.query("SELECT started_at, detail FROM engine_runs WHERE kind = 'tick' AND started_at >= ? ORDER BY started_at",
                          (newest - 4 * 3_600_000,)):
            det = loads(r["detail"], {}) or {}
            p = det.get("push")
            if p is not None:
                errs = (p or {}).get("errors") or []
                pushes.append({"at": r["started_at"], "sent": (p or {}).get("sent"), "devices": (p or {}).get("devices"),
                               "error": (str((p or {}).get("error"))[:120] if (p or {}).get("error") else None),
                               "error_types": sorted({str(e).split(":")[0] for e in errs}),
                               "reason": (p or {}).get("reason")})
            st = (det.get("steps") or {}).get("push")
            if st and not st.get("ok"):
                pushes.append({"at": r["started_at"], "step_error": str(st.get("error"))[:160]})
    except Exception as e:
        pushes.append({"error": str(e)[:200]})
    out["pushes"] = pushes
    out["fs"] = {k: db.get_setting(k, None) for k in ("fs_blocked_until", "fs_reads_blocked_until")}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    db = Database()
    json.dump(run(db), open(a.out, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
