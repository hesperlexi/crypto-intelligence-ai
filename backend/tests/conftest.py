"""Shared test setup. v2.40: the older bot-migration tests check exact bot line-ups, so the one-time 15m TP1-0.8R test
bot migration is off in tests unless a test turns it on (tests/test_tp08_v240.py)."""
import os

os.environ.setdefault("TEST_BOT_TP08", "0")
