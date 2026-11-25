"""Read-only: per timeframe, the published calls vs the calls each live filter blocked (followed with the record's rules),
net R. python -m app.filters_live --since-ms <ms> --out x.json"""
from __future__ import annotations

import argparse
import json

from .db import Database
from . import research_guard15 as G


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--since-ms", type=int, default=0)
    ap.add_argument("--until-ms", type=int, default=10**15)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    from .research_verdict import frozen_copy
    db = Database(frozen_copy(a.db))          # V3.2: private copy without the forward-holdout period
    from .services import tracking
    closed = tuple(tracking.CLOSED_STATUSES)
    done = lambda rows: [x for x in (G._r(r) for r in rows if r.get("status") in closed and r.get("fill_status") != "NOT_FILLED") if x is not None]
    out = {"ok": True, "since": a.since_ms, "until": a.until_ms, "tf": {}}
    pub_all = db.query("SELECT * FROM signals WHERE side != 0 AND created_at >= ? AND created_at < ?", (a.since_ms, a.until_ms))
    rej_all = db.query("SELECT * FROM rejected_signals WHERE created_at >= ? AND created_at < ?", (a.since_ms, a.until_ms))
    for tf in sorted({r["timeframe"] for r in pub_all + rej_all}):
        pub = [r for r in pub_all if r["timeframe"] == tf]
        rej = [r for r in rej_all if r["timeframe"] == tf]
        by = {}
        for flag in sorted({r.get("reject_flag") or "?" for r in rej}):
            rows = [r for r in rej if (r.get("reject_flag") or "?") == flag]
            by[flag] = {"blocked": len(rows), **G._stats(done(rows))}
        grades = {}
        for g in ("A", "B"):
            rows = [r for r in pub if (json.loads(r.get("payload") or "{}") or {}).get("grade") == g]
            grades[g] = G._stats(done(rows))
        out["tf"][tf] = {"published": {"calls": len(pub), **G._stats(done(pub))}, "published_by_grade": grades,
                         "rejected_by_filter": by, "rejected_all": {"blocked": len(rej), **G._stats(done(rej))}}
    s = json.dumps(out, indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)


if __name__ == "__main__":
    main()
