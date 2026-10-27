"""Diagnostic: one engine cycle that prints every thread's stack every 120 s (to find where a cycle hangs).
Run from backend/: python ../scripts/diag_tick.py [--local DIR]"""
import faulthandler
import os
import sys

sys.path.insert(0, os.getcwd())

faulthandler.dump_traceback_later(120, repeat=True, file=sys.stderr)
sys.argv = ["app.worker", "tick", "--budget", "280", *sys.argv[1:]]
from app.worker import main  # noqa: E402

main()
