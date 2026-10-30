"""Trade management: follows one call through a candle path and says how it ended. Pure and deterministic.

Used by the live record (services/tracking.py, signals and shadow_signals), the research replays (app/research.py)
and - through the per-candle helpers `giveback_exit`, `trail_level`, `time_exit_due` and `observe` - by the demo bots.

Standard rules (always on, exactly the v2.4 record):
  * three exits 50 % / 25 % / 25 % at TP1 / TP2 / TP3 (`runner`: one exit of the whole position at the runner target);
  * after TP1 the stop moves to break-even (entry), after TP2 to TP1 (runner: also to TP2 after TP3);
  * inside one candle the stop is checked first (the order of high and low is unknown: assume the worse);
  * a stop exit fills at the stop level; the call expires at the last close of the horizon.
Managed exits (params["managed"], setting MANAGED_EXITS, default off):
  * give-back: once the best open profit reached >= arm_r (before TP1), a retrace to peak * (1 - frac) closes the
    whole position. Within a candle: stop first, then give-back against the peak of PRIOR candles using this
    candle's adverse extreme, then the peak is updated with this candle's favourable extreme. Fills at the threshold,
    or at the open when the candle opens beyond it;
  * ATR trailing stop after TP1: stop = best(rule level, extreme close -/+ k * ATR), never loosened;
  * time stop: after `time_stop_bars` signal-timeframe bars, if TP1 was not reached and open profit < min_r, close at
    the close.
peak_r / peak_pct (best open profit since the fill, in R and in %) are always recorded.
"""
from __future__ import annotations

from typing import Any, Iterable

TP_WEIGHTS = (0.5, 0.25, 0.25)
DEFAULT_PARAMS = {"managed": False, "giveback_arm_r": 0.6, "giveback_frac": 0.5, "trail_atr_k": 2.0,
                  "time_stop_bars": 12, "time_stop_min_r": 0.25}
MANAGED_REASONS = ("giveback", "trail", "time")


# ---- per-candle helpers (shared with services/bots.py) ------------------------------------------------------

def new_state(side: int, entry: float, stop: float, atr: float | None = None) -> dict[str, Any]:
    """Serializable management state of one position (bots keep it inside their JSON state)."""
    risk = abs(float(entry) - float(stop))
    return {"side": int(side), "entry": float(entry), "risk": risk, "atr": float(atr) if atr else None,
            "peak_r": 0.0, "extreme_close": None, "trail": None, "time_checked": False}


def r_of(st: dict[str, Any], price: float) -> float:
    return st["side"] * (float(price) - st["entry"]) / st["risk"] if st["risk"] > 0 else 0.0


def price_at_r(st: dict[str, Any], r: float) -> float:
    return st["entry"] + st["side"] * r * st["risk"]


def giveback_exit(st: dict[str, Any], op: float, hi: float, lo: float, p: dict[str, Any], tp1_hit: bool) -> float | None:
    """Exit price when the give-back rule fires in this candle (checked AFTER the stop, BEFORE `observe`)."""
    if not p.get("managed") or tp1_hit or st["risk"] <= 0:
        return None
    peak = st["peak_r"]                                  # from prior candles only
    if peak < float(p["giveback_arm_r"]) - 1e-12:
        return None
    thr_r = peak * (1 - float(p["giveback_frac"]))
    adverse = lo if st["side"] > 0 else hi
    if r_of(st, adverse) > thr_r + 1e-12:
        return None
    thr = price_at_r(st, thr_r)
    return float(op) if r_of(st, op) <= thr_r else float(thr)       # gap through the threshold: the open


def observe(st: dict[str, Any], hi: float, lo: float, cl: float, favourable: bool = True) -> None:
    """Update the peak (favourable extreme, or only the close when `favourable` is False) and the extreme close."""
    fav = (hi if st["side"] > 0 else lo) if favourable else cl
    st["peak_r"] = max(st["peak_r"], r_of(st, fav))
    if st["extreme_close"] is None or st["side"] * (cl - st["extreme_close"]) > 0:
        st["extreme_close"] = float(cl)


def trail_level(st: dict[str, Any], rule_level: float, p: dict[str, Any], tp1_hit: bool) -> float:
    """Active stop after TP1 with the ATR trail (never looser than the rule level, never loosened)."""
    if not p.get("managed") or not tp1_hit or not st.get("atr") or st["extreme_close"] is None:
        return rule_level
    cand = st["extreme_close"] - st["side"] * float(p["trail_atr_k"]) * st["atr"]
    if st["trail"] is None or st["side"] * (cand - st["trail"]) > 0:
        st["trail"] = float(cand)
    return st["trail"] if st["side"] * (st["trail"] - rule_level) > 0 else rule_level


def time_exit_due(st: dict[str, Any], candle_end_ts: int, start_ts: int, bar_ms: int, close: float,
                  p: dict[str, Any], tp1_hit: bool) -> bool:
    """True once, at the first candle ending at/after start + time_stop_bars bars, if TP1 not hit and profit < min_r."""
    if not p.get("managed") or tp1_hit or st["time_checked"]:
        return False
    if candle_end_ts < start_ts + int(p["time_stop_bars"]) * bar_ms:
        return False
    st["time_checked"] = True
    return r_of(st, close) < float(p["time_stop_min_r"])


# ---- whole-path follow ----------------------------------------------------------------------------------------

def _rows(path: Any) -> list[tuple[int, float, float, float, float]]:
    if hasattr(path, "itertuples"):
        return [(int(t), float(o), float(h), float(l), float(c))
                for t, o, h, l, c in zip(path["ts"], path["open"], path["high"], path["low"], path["close"])]
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in path]


def follow(side: int, entry: float, stop: float, tps: list[float], path: Iterable, *, runner_target: float | None = None,
           atr: float | None = None, params: dict[str, Any] | None = None, complete: bool = False,
           first_is_fill: bool = False, start_ts: int | None = None, bar_ms: int | None = None,
           path_ms: int = 900_000) -> dict[str, Any]:
    """Follow one call through `path` (ts, open, high, low, close; ts = candle open), starting at the fill.

    complete: the path covers the whole horizon (an unfinished call then expires at the last close).
    first_is_fill: the first candle is the one in which a limit entry filled - its stop counts (worse case), its
    favourable move does not (it may have happened before the fill); only its close counts for the peak.
    Returns {status, hits, stop_hit, exit_reason, exit_price, legs, return_pct, return_r, peak_r, peak_pct,
    closed_ts, managed, events}. status OPEN = still running (return_pct marks it at the last close)."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    rows = _rows(path)
    entry, stop = float(entry), float(stop)
    tps = [float(t) for t in tps]
    st = new_state(side, entry, stop, atr)
    risk_pct = st["risk"] / entry * 100 if entry else 0.0
    start_ts = rows[0][0] if start_ts is None and rows else start_ts
    bar_ms = bar_ms or path_ms
    hit = [False, False, False]
    stop_hit = final_hit = False
    closed_ts: int | None = None
    level = stop
    final = runner_target
    exit_reason: str | None = None
    managed_exit_px: float | None = None
    events: list[dict[str, Any]] = []
    for i, (ts, op, hi, lo, cl) in enumerate(rows):
        fill_candle = first_is_fill and i == 0
        if (side > 0 and lo <= level) or (side < 0 and hi >= level):
            stop_hit, closed_ts = True, ts
            events.append({"ts": ts, "type": "stop", "price": level})
            break
        gb = None if fill_candle else giveback_exit(st, op, hi, lo, p, hit[0])
        if gb is not None:
            managed_exit_px, closed_ts, exit_reason = gb, ts, "giveback"
            events.append({"ts": ts, "type": "giveback", "price": gb, "peak_r": st["peak_r"]})
            break
        observe(st, hi, lo, cl, favourable=not fill_candle)
        if not fill_candle:
            before = list(hit)
            for k, tp in enumerate(tps):
                if (side > 0 and hi >= tp) or (side < 0 and lo <= tp):
                    hit[k] = True
            for k in range(3):
                if hit[k] and not before[k]:
                    events.append({"ts": ts, "type": f"tp{k + 1}", "price": tps[k]})
            if final is None:
                level = tps[0] if hit[1] else entry if hit[0] else stop
                if hit[2]:
                    closed_ts = ts
                    break
            else:
                level = tps[1] if hit[2] else tps[0] if hit[1] else entry if hit[0] else stop
                if (side > 0 and hi >= final) or (side < 0 and lo <= final):
                    final_hit, closed_ts = True, ts
                    hit = [True, True, True]
                    events.append({"ts": ts, "type": "runner_target", "price": final})
                    break
        level = trail_level(st, level, p, hit[0])
        if time_exit_due(st, ts + path_ms, int(ts if start_ts is None else start_ts), bar_ms, cl, p, hit[0]):
            managed_exit_px, closed_ts, exit_reason = cl, ts, "time"
            events.append({"ts": ts, "type": "time", "price": cl})
            break
    if not rows:
        return {"status": "OPEN", "hits": hit, "stop_hit": False, "exit_reason": None, "exit_price": None, "legs": [],
                "return_pct": None, "return_r": None, "peak_r": 0.0, "peak_pct": 0.0, "closed_ts": None, "managed": 0,
                "events": []}
    expired = closed_ts is None and complete
    last_close = rows[-1][4]              # expiry exits at the last close of the path (only used when nothing else fired)
    fallback = level if stop_hit else managed_exit_px if managed_exit_px is not None else last_close
    if final is None:
        legs = [{"weight": w, "price": tps[k] if hit[k] else fallback} for k, w in enumerate(TP_WEIGHTS)]
    else:
        legs = [{"weight": 1.0, "price": final if final_hit else fallback}]
    ret = float(sum(l["weight"] * side * (l["price"] / entry - 1) for l in legs)) * 100
    if exit_reason in ("giveback", "time"):
        status = "TP2" if hit[1] else "TP1" if hit[0] else "EXPIRED"
    elif final is None:
        status = "STOPPED" if stop_hit and not hit[0] else "TP3" if hit[2] else \
            ("TP2" if hit[1] else "TP1" if hit[0] else "EXPIRED") if (stop_hit or expired) else "OPEN"
    else:
        status = "TP3" if final_hit else "STOPPED" if stop_hit and not hit[0] else \
            ("TP3" if hit[2] else "TP2" if hit[1] else "TP1" if hit[0] else "EXPIRED") if (stop_hit or expired) else "OPEN"
    if closed_ts is None and expired:
        closed_ts = rows[-1][0]
        events.append({"ts": closed_ts, "type": "expired", "price": last_close})
    if exit_reason is None:
        if stop_hit:
            if not hit[0]:
                exit_reason = "stop"
            elif st.get("trail") is not None and abs(level - st["trail"]) < 1e-12 and p.get("managed"):
                exit_reason = "trail"
            elif abs(level - entry) < 1e-12:
                exit_reason = "break_even"
            else:
                exit_reason = "trail"            # the rule stop locked in TP1 (after TP2) or TP2 (runner after TP3)
        elif status == "TP3":
            exit_reason = "tp3"
        elif expired:
            exit_reason = "expired"
    managed = int(exit_reason in ("giveback", "time") or
                  (exit_reason == "trail" and stop_hit and st.get("trail") is not None and abs(level - st["trail"]) < 1e-12
                   and bool(p.get("managed"))))
    exit_price = None if status == "OPEN" else (final if final_hit else fallback)
    return {"status": status, "hits": hit, "stop_hit": stop_hit, "exit_reason": exit_reason if status != "OPEN" else None,
            "exit_price": exit_price, "legs": legs, "return_pct": ret,
            "return_r": ret / risk_pct if risk_pct else None, "peak_r": st["peak_r"],
            "peak_pct": st["peak_r"] * risk_pct, "closed_ts": closed_ts if status != "OPEN" else None,
            "managed": managed if status != "OPEN" else 0, "events": events}


def find_fill(side: int, entry: float, path: Iterable, until_ts: int | None = None) -> int | None:
    """Index of the first candle (opened before `until_ts`) that trades through a limit entry, else None."""
    for i, (ts, op, hi, lo, cl) in enumerate(_rows(path)):
        if until_ts is not None and ts >= until_ts:
            return None
        if (side > 0 and lo <= entry) or (side < 0 and hi >= entry):
            return i
    return None
