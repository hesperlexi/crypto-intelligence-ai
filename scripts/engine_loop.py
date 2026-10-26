"""Always-on engine (v2.3): one GitHub job ticks every 5 minutes for up to ~70 minutes per call.

GitHub starts scheduled workflows late (often 40-60 minutes apart), so instead of one tick per run the engine job
keeps itself alive: engine.yml calls this script five times in a row (saving the state to the Actions cache after
each call), which keeps one job running for ~5 h 50 min; the next scheduled run is already queued and takes over.

Each tick runs in a fresh process (`python -m app.worker tick`), exactly like before, after a fast-forward to the
newest code on main (so engine fixes go live within 5 minutes; workflow changes still need the next run). The loop stops early when:
  * the nightly training merge has started (it waits for this job to save the state and end, then takes over;
    it restarts the engine when it is done);
  * the stop file exists (an earlier call in the same job decided to stop).
Firestore guard: if this job has written more than WRITE_SOFT_CAP view documents, the gap grows to 10 minutes so the
free daily quota is never used up.

Usage (from backend/):  python ../scripts/engine_loop.py --minutes 70 --stop-file "$RUNNER_TEMP/engine-stop"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

EVERY_S = 300
SLOW_EVERY_S = 600
WRITE_SOFT_CAP = 3000
COUNT_FILE_SUFFIX = ".writes"


def merge_waiting() -> bool:
    """True when a train.yml run's merge job is running (it is waiting for the engine's state)."""
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return False

    def get(url: str) -> dict:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                   "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    try:
        runs = get(f"https://api.github.com/repos/{repo}/actions/workflows/train.yml/runs?status=in_progress&per_page=5")
        for run in runs.get("workflow_runs", []):
            jobs = get(run["jobs_url"] + "?per_page=50").get("jobs", [])
            if any(j["name"].startswith("merge") and j["status"] == "in_progress" for j in jobs):
                return True
        return False
    except Exception as exc:                       # the API being slow must never stop the engine
        print(f"merge check failed: {exc}", flush=True)
        return False


def update_code() -> None:
    """Fast-forward to the newest code on main, so a change goes live at the next tick instead of the next run."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        before = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "-C", root, "pull", "--ff-only", "-q", "origin", "main"], capture_output=True, timeout=60)
        after = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if before and after and before != after:
            print(f"engine loop: code updated {before[:7]} -> {after[:7]}", flush=True)
            changed = subprocess.run(["git", "-C", root, "diff", "--name-only", before, after],
                                     capture_output=True, text=True).stdout
            if "backend/requirements-worker.txt" in changed:
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                                os.path.join(root, "backend", "requirements-worker.txt")], timeout=600)
    except Exception as exc:                       # never let an update problem stop the engine
        print(f"engine loop: code update skipped ({exc})", flush=True)


def tick(budget: int) -> int:
    """Run one engine cycle; returns the number of view documents it wrote (0 if unknown)."""
    try:
        p = subprocess.run([sys.executable, "-m", "app.worker", "tick", "--budget", str(budget)],
                           capture_output=True, text=True, timeout=budget + 600)
    except subprocess.TimeoutExpired:
        print("::warning::engine tick hung and was stopped", flush=True)
        return 0
    sys.stdout.write(p.stdout[-4000:])
    sys.stderr.write(p.stderr[-6000:])
    m = re.search(r'"written": ?(\d+)', p.stdout + p.stderr)
    if p.returncode:
        print(f"::warning::engine tick exited with {p.returncode}", flush=True)
    return int(m.group(1)) if m else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=70)
    ap.add_argument("--budget", type=int, default=280)
    ap.add_argument("--stop-file", default="")
    a = ap.parse_args()
    stop = a.stop_file
    count_file = (stop + COUNT_FILE_SUFFIX) if stop else ""
    if stop and os.path.exists(stop):
        print("engine loop: stopped earlier in this job", flush=True)
        return
    written = int(open(count_file).read() or 0) if count_file and os.path.exists(count_file) else 0
    end = time.time() + a.minutes * 60
    n = 0
    while True:
        if merge_waiting():
            print("::notice::training merge is running: handing over the engine state", flush=True)
            if stop:
                open(stop, "w").write("merge")
            return
        update_code()
        started = time.time()
        written += tick(a.budget)
        n += 1
        if count_file:
            open(count_file, "w").write(str(written))
            with open(stop + ".ticks", "a") as f:     # engine.yml saves the state only after a call that ticked
                f.write(f"{int(started)}\n")
        gap = SLOW_EVERY_S if written > WRITE_SOFT_CAP else EVERY_S
        nxt = started + gap
        print(f"engine loop: tick {n} took {time.time() - started:.0f}s, {written} documents written in this job",
              flush=True)
        if nxt + a.budget > end:                   # not enough time for another full tick in this call
            return
        time.sleep(max(0.0, nxt - time.time()))


if __name__ == "__main__":
    main()
