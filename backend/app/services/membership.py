"""Memberships: who is active, and the notifications around payments and renewals.

The website writes users/{uid} (status, expires_at, payment); the Firestore rules lock people out when a
membership ends. The engine only (1) pauses alerts of people who are no longer active, (2) tells the admins when a
new payment proof arrives, and (3) reminds members a few days before their membership ends.
"""
from __future__ import annotations

from typing import Any

DAY_MS = 86_400_000
REMIND_DAYS = (1, 3)        # smallest first: one reminder 3 days before, another on the last day


def is_active(u: dict[str, Any] | None, now: int) -> bool:
    """No record = an admin (members always have one). Approved with no end date = permanent member."""
    if u is None:
        return True
    if u.get("status") != "approved":
        return False
    exp = u.get("expires_at")
    return not exp or int(exp) > now


def inactive_uids(users: dict[str, dict[str, Any]], now: int) -> set[str]:
    return {uid for uid, u in users.items() if not is_active(u, now)}


def notifications(users: dict[str, dict[str, Any]], seen: dict[str, Any], now: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Push messages that are due, and the updated 'already sent' markers (kept in the engine's settings)."""
    msgs: list[dict[str, str]] = []
    seen = dict(seen or {})
    for uid, u in users.items():
        who = u.get("name") or u.get("email") or uid
        p = u.get("payment") or {}
        # a new (or replaced) proof -> the admins' devices (no uid = admins)
        if p.get("status") == "submitted" and p.get("submitted_at"):
            key = f"proof:{uid}:{p['submitted_at']}"
            if key not in seen:
                months = int(p.get("months") or 0)
                plan = "1 year" if months == 12 else f"{months} month{'s' if months != 1 else ''}"
                msgs.append({"title": "Payment proof received",
                             "body": f"{who} sent {p.get('amount')} {p.get('currency', 'USDT')} for {plan}. Check it on the Users page.",
                             "url": "/users", "tag": key})
                seen[key] = now
        # renewal reminders -> that member's devices
        exp = u.get("expires_at")
        if u.get("status") == "approved" and exp:
            days = (int(exp) - now) / DAY_MS
            for d in REMIND_DAYS:
                if not 0 < days <= d:
                    continue
                key = f"remind:{uid}:{exp}:{d}"
                if key not in seen and p.get("status") != "submitted":
                    msgs.append({"title": "Membership ending soon",
                                 "body": f"Your Crypto Intelligence AI membership ends in {max(1, round(days))} day{'s' if round(days) > 1 else ''}. Renew in Settings to keep access.",
                                 "url": "/settings", "tag": key, "uid": uid})
                    seen[key] = now
                break
    # forget markers older than 120 days
    seen = {k: v for k, v in seen.items() if isinstance(v, (int, float)) and now - v < 120 * DAY_MS}
    return msgs, seen
