"""Shared test setup. v2.40: the older bot-migration tests check exact bot line-ups, so the one-time 15m TP1-0.8R test
bot migration is off in tests unless a test turns it on (tests/test_tp08_v240.py)."""
import os

os.environ.setdefault("TEST_BOT_TP08", "0")
os.environ.setdefault("ADD_MSTR", "0")          # v2.49 one-time MSTR watchlist addition: tests/test_futures_only_v249.py
os.environ.setdefault("CHALLENGE_SLOTS", "1")      # v3.2 challenges: older tests check one all-in trade at a time (tests/test_challenge_slots.py)
os.environ.setdefault("HESPER_RISK_PCT", "0")
os.environ.setdefault("LASTSTAND_RISK_PCT", "0")
os.environ.setdefault("RECORD_MIRROR", "0")      # v3.1 bots mirror the record call; older bot tests use their own plan (tests/test_record_mirror.py)
os.environ.setdefault("DEMO_ONLY_TFS", "")     # v2.64 1d demo-only: older policy tests check the v2.12 line-up; tests/test_demo_1d_v264.py
