"""Engine watchdog: tells the admins (phone notification) when the engine has stopped publishing, and again
when it is back. Runs on its own schedule, separate from the engine, so a failing engine cannot silence it.

    python -m app.watchdog --stale-minutes 75
"""
from __future__ import annotations

import argparse
import logging
import os
import time

log = logging.getLogger("watchdog")
STATE = "system/watchdog"


def check(sink, stale_minutes: float, now_ms: int | None = None) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    meta = sink.get("views/meta") or {}
    last = int(meta.get("updated_at") or 0)
    age_min = (now_ms - last) / 60_000 if last else float("inf")
    state = sink.get(STATE) or {}
    was_down = bool(state.get("down"))
    down = age_min > stale_minutes
    out = {"age_minutes": None if last == 0 else round(age_min, 1), "down": down, "notified": None}
    msg = None
    if down and (not was_down or now_ms - int(state.get("notified_at") or 0) > 12 * 3_600_000):
        hrs = "never" if last == 0 else (f"{age_min / 60:.1f} hours" if age_min >= 90 else f"{age_min:.0f} minutes")
        msg = {"title": "Engine stopped", "url": "/health", "tag": "engine-watchdog",
               "body": f"No new signals for {hrs}. Open GitHub > Actions > 'Engine (every 15 minutes)' to see why, "
                       f"or run it once by hand. Signals and bots are paused until it runs again."}
    elif not down and was_down:
        msg = {"title": "Engine running again", "url": "/", "tag": "engine-watchdog",
               "body": "The engine is publishing signals again."}
    if msg:
        out["notified"] = sink.send_push([msg])          # no uid: goes to the admins' devices
        log.info("notified: %s -> %s", msg["title"], out["notified"])
    sink.set(STATE, {"down": down, "checked_at": now_ms, "last_engine_update": last,
                     "notified_at": now_ms if msg and down else int(state.get("notified_at") or 0) if down else 0})
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="python -m app.watchdog")
    ap.add_argument("--stale-minutes", type=float, default=75)
    a = ap.parse_args()
    from .sinks import FirestoreSink
    print(check(FirestoreSink(None, os.environ.get("FIREBASE_PROJECT_ID") or None), a.stale_minutes))


if __name__ == "__main__":
    main()
