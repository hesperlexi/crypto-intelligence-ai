"""Read-only: the 15m calls the live filters blocked vs the ones published, from the record start and since a date.
python -m app.guard15_live --since-ms <ms> --out x.json (research_guard15.live, plus a split from `since-ms`)."""
from __future__ import annotations

import argparse
import json

from .db import Database
from . import research_guard15 as G


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--since-ms", type=int, default=0)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    db = Database(a.db)
    out = {"ok": True, "all": G.live(db)}
    if a.since_ms:
        from .services import tracking
        closed = tuple(tracking.CLOSED_STATUSES)
        rej = db.query("SELECT * FROM rejected_signals WHERE timeframe = '15m' AND created_at >= ?", (a.since_ms,))
        pub = db.query("SELECT * FROM signals WHERE timeframe = '15m' AND side != 0 AND created_at >= ?", (a.since_ms,))
        done = lambda rows: [x for x in (G._r(r) for r in rows if r.get("status") in closed and r.get("fill_status") != "NOT_FILLED") if x is not None]
        by = {}
        for flag in sorted({r.get("reject_flag") or "?" for r in rej}):
            rows = [r for r in rej if (r.get("reject_flag") or "?") == flag]
            by[flag] = {"blocked": len(rows), **G._stats(done(rows))}
        out["since"] = {"from": a.since_ms, "published": {"calls": len(pub), **G._stats(done(pub))},
                        "rejected_by_filter": by, "rejected_all": {"blocked": len(rej), **G._stats(done(rej))}}
    s = json.dumps(out, indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)


if __name__ == "__main__":
    main()
