"""v2.16 referral programme (owner decision 3 Nov 2026) - the engine's small part.

Everything that matters happens on the website and is enforced by the Firestore rules:
  * a member creates their code once: ref_codes/{code} {uid, created_at} + users/{uid}.ref_code (one batch, write-once);
  * a new account opened from a link (?ref=<code>) stores users/{uid}.referred_by (+ ref_via = the code) when the record
    is CREATED (never later, never yourself, the code must belong to that referrer);
  * the admin's approval of the friend's FIRST paid payment (> 0 USDT, not free) gives the referrer 1 free month in the
    same transaction (frontend/src/lib/membership.ts grantMembership; friend marked `referral_reward`, so only once).

Members cannot read other people's records, so they cannot count their friends themselves. The engine already holds
every users record (settings `users_cache`, re-read every 30 min) and writes each referrer's counts to
users/{uid}.referral_stats {joined, paid, months, updated_at} - only when a number changed (no reads; a few writes a
month). `months` = free referral months recorded in the referrer's history.
"""
from __future__ import annotations

from typing import Any

from ..db import now_ms


def stats(users: dict[str, dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for uid, u in users.items():
        ref = u.get("referred_by")
        if isinstance(ref, str) and ref and ref != uid and ref in users:
            s = out.setdefault(ref, {"joined": 0, "paid": 0, "months": 0})
            s["joined"] += 1
            if u.get("referral_reward"):
                s["paid"] += 1
    for uid, u in users.items():
        months = sum(1 for h in (u.get("history") or []) if isinstance(h, dict) and h.get("kind") == "referral")
        if months or u.get("ref_code"):
            out.setdefault(uid, {"joined": 0, "paid": 0, "months": 0})["months"] = months
    return out


def sync(rt: Any, sink: Any, now: int | None = None) -> dict[str, Any]:
    """Publish changed counts. Runs only after the users cache was refreshed (no Firestore reads of its own)."""
    now = now or now_ms()
    cache = rt.db.get_setting("users_cache", None) or {}
    at = int(cache.get("at") or 0)
    if not cache.get("users") or at <= int(rt.db.get_setting("ref_stats_at", 0) or 0):
        return {"skipped": "users unchanged"}
    sent = rt.db.get_setting("ref_stats_sent", None) or {}
    written = 0
    for uid, s in stats(cache["users"]).items():
        key = [s["joined"], s["paid"], s["months"]]
        if sent.get(uid) == key:
            continue
        sink.set(f"users/{uid}", {"referral_stats": {**s, "updated_at": now}}, merge=True)
        sent[uid] = key
        written += 1
    rt.db.set_setting("ref_stats_sent", sent)
    rt.db.set_setting("ref_stats_at", at)
    return {"written": written}
