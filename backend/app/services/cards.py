"""Share images for Telegram (V3.5 redesign, owner 26 Nov 2026: "the card hides logos and details when shared on Telegram;
make sure the text doesn't overlap; design it as per the Fable audit report").

Size: 1280 x 1024 LANDSCAPE. Telegram shows wide images whole (tall 4:5 cards were trimmed top and bottom, cutting the
logo and the footer) and keeps 1280 px on the long side, so nothing is rescaled. Everything sits inside a SAFE frame
(M = 64 px from every edge).

Design (Fable 5.2 audit, section J): graphite surfaces, hairline borders, ONE gold accent (brand mark, entry, key labels),
green / red ONLY for profit and loss, cyan ONLY for AI, IBM Plex Sans with one weight for figures, no glow, no stars, no
orbits, no gradients on numbers. Honesty (audit, reporting rule): every result is NET of fees and funding, states how many
signals it rests on and the period, says "paper" (tracked at real prices, no real money), never calls a result profitable
before 300 closed signals, never shows a grade or a model score as a chance of winning; leverage is a secondary line that
says losses magnify too.

No-overlap rule: every text goes through `_t`, which records its box. `layout_boxes(fn, *args)` returns the boxes of a
render; tests assert no two texts touch and every text lies inside the safe frame, for long names, tiny prices and big
numbers alike.

Cards: result_card / win_card (one closed signal, win or loss), wins_card (wins of the day / week with the losses),
weekly_card, week7_card, teaser_card (a free signal), briefing_card (AI market briefing), news_card (high-impact release).
Each returns PNG bytes (palette-quantised, well under Telegram's 10 MB photo limit).
"""
from __future__ import annotations

import io
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .. import brand
from ..pricefmt import fmt_price

ASSETS = Path(__file__).resolve().parent.parent / "assets"
W, H = 1280, 1024
M = 64                                       # safe frame: nothing inside this margin
GAP = 24
HEAD_B = 156                                 # bottom of the header block
FOOT_Y = H - 140                            # top of the footer block
BODY = (HEAD_B + 28, FOOT_Y - 28)            # vertical span of the content

INK = (17, 18, 21)                           # page
PANEL = (26, 27, 32)                         # card surface
PANEL_HI = (34, 36, 42)
LINE = (52, 54, 62)                          # hairline
GOLD = (232, 182, 55)                        # the one accent
GOLD_BG = (46, 39, 20)
WHITE = (236, 238, 241)
SILVER = (150, 158, 171)
MUTED = (104, 111, 124)
GREEN = (14, 203, 129)                       # profit only
RED = (246, 70, 93)                          # loss only
CYAN = (93, 241, 221)                        # AI only
RISK_BG = (64, 34, 40)

SITE_TEXT = brand.DISPLAY_URL
MIN_JUDGE = 300                              # audit: no result is "profitable" from fewer closed signals
_fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_PLEX = {"Regular": "Regular", "Medium": "Medium", "SemiBold": "SemiBold", "Bold": "Bold", "ExtraBold": "Bold"}
_BOXES: list[tuple[float, float, float, float, str]] | None = None


def _f(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(str(ASSETS / "fonts" / f"IBMPlexSans-{_PLEX.get(weight, 'Medium')}.ttf"), size)
        except OSError:
            _fonts[key] = ImageFont.load_default(size)
    return _fonts[key]


_s = _f                                      # old name kept for callers


# ---- formatting -----------------------------------------------------------------------------------------------

def coin(sym: str) -> str:
    b = str(sym).split("/")[0]
    return {"PAXG": "GOLD", "XAG": "SILVER"}.get(b, b)


def pair(sym: str) -> str:
    c = coin(sym)
    return c if c in ("GOLD", "SILVER") else f"{c} / USDT"


def px(v: float | None) -> str:
    return fmt_price(v)      # no scientific notation for coins below 0.0001


def _side(s: Any) -> str:
    if isinstance(s, str):
        return s.upper()
    return "LONG" if s and s > 0 else "SHORT"


def result(x: dict[str, Any]) -> tuple[float, int | None, float]:
    """(ROI on margin or the price move, leverage or None, net price move %)."""
    ret = float(x["return_pct"])
    lev = x.get("leverage")
    roi = x.get("roi_pct")
    if roi is None and lev:
        roi = ret * float(lev)
    if roi is None or not lev:
        return ret, None, ret
    return float(roi), int(lev), ret


def pct(v: float, dp: int = 2) -> str:
    return f"{v:+,.{dp}f}%"


def _num(v: Any) -> float | None:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _pl(v: float | None) -> tuple[int, int, int]:
    return GREEN if (v or 0) > 0 else RED if (v or 0) < 0 else WHITE


# ---- text with recorded boxes ---------------------------------------------------------------------------------

def _t(d: ImageDraw.ImageDraw, xy, text: str, font, fill, anchor: str = "ls") -> float:
    """Draw text and record its box (the no-overlap test reads them). Returns the text width."""
    text = str(text)
    d.text(xy, text, font=font, fill=fill, anchor=anchor)
    if _BOXES is not None and text.strip():
        b = d.textbbox(xy, text, font=font, anchor=anchor)
        _BOXES.append((b[0], b[1], b[2], b[3], text))
    return d.textlength(text, font=font)


def _fit(d, text: str, weight: str, size: int, max_w: float, min_size: int = 16) -> ImageFont.FreeTypeFont:
    while size > min_size and d.textlength(str(text), font=_f(weight, size)) > max_w:
        size -= 2
    return _f(weight, size)


def _clip(d, text: str, font, max_w: float) -> str:
    """Shorten with an ellipsis so it never runs past max_w (last resort after _fit)."""
    text = str(text)
    if d.textlength(text, font=font) <= max_w:
        return text
    while text and d.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _wrap(d, text: str, font, max_w: float, max_lines: int) -> list[str]:
    lines, cur = [], ""
    for w in str(text).split():
        t = f"{cur} {w}".strip()
        if cur and d.textlength(t, font=font) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _clip(d, lines[-1] + " …", font, max_w)
    return [_clip(d, ln, font, max_w) for ln in lines]


def _cap(font) -> float:
    return -font.getbbox("H", anchor="ls")[1]


# ---- shapes ---------------------------------------------------------------------------------------------------

def _panel(d, box, fill=PANEL, r: int = 14) -> None:
    d.rounded_rectangle(box, radius=r, fill=fill, outline=LINE, width=1)


def _pill(d, x: float, y: float, text: str, fg, bg=PANEL_HI, outline=None, align: str = "left", h: int = 38) -> float:
    """Tag with top-left at (x, y) (top-right with align='right'). Returns the far edge."""
    fn = _f("SemiBold", 18)
    w = d.textlength(text, font=fn) + 32
    x0 = x if align == "left" else x - w
    d.rounded_rectangle((x0, y, x0 + w, y + h), radius=8, fill=bg, outline=outline, width=1 if outline else 0)
    _t(d, (x0 + w / 2, y + h / 2 + _cap(fn) / 2), text, fn, fg, anchor="ms")
    return x0 + w if align == "left" else x0


def _side_pill(d, x, y, side: str) -> float:
    col = GREEN if side == "LONG" else RED
    return _pill(d, x, y, side, col, bg=tuple(int(c * 0.14 + INK[i] * 0.86) for i, c in enumerate(col)), outline=col)


def _label(d, xy, text: str, fill=SILVER, size: int = 19, anchor: str = "ls") -> float:
    return _t(d, xy, text, _f("Medium", size), fill, anchor=anchor)


def _cells(d, box, cells: list[tuple[str, str, Any]], cols: int) -> None:
    """Panel of label / value cells in a grid with hairlines; values shrink to fit their cell."""
    x0, y0, x1, y1 = box
    _panel(d, box)
    rows = math.ceil(len(cells) / cols)
    cw, rh = (x1 - x0) / cols, (y1 - y0) / rows
    vf_size = int(min(34, rh * 0.36))
    for i, (k, v, c) in enumerate(cells):
        cx, cy = x0 + (i % cols) * cw, y0 + (i // cols) * rh
        if i % cols:
            d.line([(cx, cy + 14), (cx, cy + rh - 14)], fill=LINE, width=1)
        if i >= cols:
            d.line([(cx + 14, cy), (cx + cw - 14, cy)], fill=LINE, width=1)
        lf = _fit(d, k, "Medium", 18, cw - 44, 14)
        _t(d, (cx + 22, cy + rh * 0.40), _clip(d, k, lf, cw - 44), lf, SILVER)
        vf = _fit(d, v, "SemiBold", vf_size, cw - 44, 16)
        _t(d, (cx + 22, cy + rh * 0.40 + vf.size + 12), _clip(d, v, vf, cw - 44), vf, c)


def _background(img: Image.Image) -> None:
    """Flat graphite, a slightly lighter band behind the header (no mesh, no glow, no stars)."""
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, H), fill=INK)
    d.rectangle((0, 0, W, HEAD_B + 8), fill=(21, 22, 26))


def _base(title: str, tag: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Header inside the safe frame: logo, name, one context line, the card's kind; a hairline under it."""
    img = Image.new("RGB", (W, H), INK)
    _background(img)
    ls, y0 = 72, M - 4
    try:
        logo = Image.open(ASSETS / "logo.png").convert("RGBA").resize((ls, ls), Image.LANCZOS)
        img.paste(logo, (M, y0), logo)
    except OSError:
        pass
    d = ImageDraw.Draw(img)
    tag = tag.upper()
    tag_w = d.textlength(tag, font=_f("SemiBold", 18)) + 32
    tx = M + ls + 20
    room = W - M - tag_w - 28 - tx
    _t(d, (tx, y0 + 32), "Crypto Intelligence AI", _fit(d, "Crypto Intelligence AI", "SemiBold", 30, room), WHITE)
    tf = _fit(d, title, "Regular", 21, room, 16)
    _t(d, (tx, y0 + 64), _clip(d, title, tf, room), tf, SILVER)
    _pill(d, W - M, y0 + 17, tag, GOLD, bg=GOLD_BG, align="right")
    d.line([(M, HEAD_B), (W - M, HEAD_B)], fill=LINE, width=1)
    return img, d


def _footer(d, note: str) -> None:
    """Footer inside the safe frame: site in gold, the card's honesty note, the standing line."""
    d.line([(M, FOOT_Y), (W - M, FOOT_Y)], fill=LINE, width=1)
    sf = _f("SemiBold", 24)
    sw = _t(d, (M, FOOT_Y + 40), SITE_TEXT, sf, GOLD)
    nf = _fit(d, note, "Medium", 19, W - 2 * M - sw - 40, 14)
    _t(d, (W - M, FOOT_Y + 40), _clip(d, note, nf, W - 2 * M - sw - 40), nf, WHITE, anchor="rs")
    std = "Paper trading: signals tracked at real prices, no real money · Analysis only, not financial advice"
    stf = _fit(d, std, "Regular", 17, W - 2 * M, 13)
    _t(d, (M, FOOT_Y + 72), std, stf, MUTED)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.quantize(256, method=Image.Quantize.MEDIANCUT, kmeans=3, dither=Image.Dither.NONE).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _coin_title(d, x: float, y: float, sym: str, max_w: float) -> float:
    """Ticker large in white, '/ USDT' small in silver beside it (shrinks to fit). Returns the baseline y."""
    c = coin(sym)
    suffix = "" if c in ("GOLD", "SILVER") else "/ USDT"
    sf = _f("Medium", 26)
    sw = d.textlength(suffix, font=sf) + 16 if suffix else 0
    f = _fit(d, c, "Bold", 96, max_w - sw, 36)
    cw = _t(d, (x, y), _clip(d, c, f, max_w - sw), f, WHITE)
    if suffix:
        _t(d, (x + cw + 16, y), suffix, sf, SILVER)
    return y


def _hero(d, x: float, y: float, value: float, max_w: float, size: int = 112, text: str | None = None) -> None:
    t = text if text is not None else pct(value)
    _t(d, (x, y), t, _fit(d, t, "Bold", size, max_w, 40), _pl(value))


def _rail(d, box, side: str, levels: dict[str, float | None], hit: set[str], show_prices: bool = True) -> None:
    """Stop -> entry -> TP1-3 on one line (left = stop). Points placed by price, then spread so labels never touch."""
    x0, y0, x1, y1 = box
    keys = [k for k in ("stop", "entry", "tp1", "tp2", "tp3") if _num(levels.get(k)) is not None]
    names = {"stop": "STOP", "entry": "ENTRY", "tp1": "TP1", "tp2": "TP2", "tp3": "TP3"}
    lf, pf = _f("SemiBold", 17), _f("Medium", 18)
    if "entry" not in keys or len(keys) < 2:
        keys = ["stop", "entry", "tp1", "tp2", "tp3"]
        pos = {k: i / 4 for i, k in enumerate(keys)}
        show_prices = False
    else:
        s = 1 if side == "LONG" else -1
        vals = {k: float(levels[k]) * s for k in keys}
        lo, hi = min(vals.values()), max(vals.values())
        span = (hi - lo) or 1.0
        pos = {k: (vals[k] - lo) / span for k in keys}
    # minimum gap from the widest label / price, then rescale into [0, 1]
    inner = (x1 - x0) - 120
    widest = max(max(d.textlength(names[k], font=lf), d.textlength(px(levels.get(k)), font=pf) if show_prices else 0) for k in keys)
    gap = min(0.5, (widest + 22) / inner)
    order = sorted(keys, key=lambda k: pos[k])
    for i in range(1, len(order)):
        pos[order[i]] = max(pos[order[i]], pos[order[i - 1]] + gap)
    top = pos[order[-1]] or 1.0
    if top > 1:
        for k in keys:
            pos[k] /= top
    ly = (y0 + y1) / 2
    X = lambda p: x0 + 60 + p * inner                       # noqa: E731
    ex = X(pos.get("entry", 0.25))
    lo_x, hi_x = X(min(pos.values())), X(max(pos.values()))
    d.line([(lo_x, ly), (hi_x, ly)], fill=LINE, width=4)
    if "stop" in pos:
        d.line([(X(pos["stop"]), ly), (ex, ly)], fill=RED if "stop" in hit else RISK_BG, width=4)
    reached = [k for k in ("tp1", "tp2", "tp3") if k in hit and k in pos]
    if reached:
        d.line([(ex, ly), (X(max(pos[k] for k in reached)), ly)], fill=GREEN, width=4)
    for k, p in pos.items():
        x = X(p)
        if k == "entry":
            d.polygon([(x, ly - 12), (x + 12, ly), (x, ly + 12), (x - 12, ly)], fill=GOLD)
            col = GOLD
        else:
            on = k in hit
            col = (RED if k == "stop" else GREEN) if on else (RED if k == "stop" else SILVER)
            r = 10 if on else 8
            d.ellipse((x - r, ly - r, x + r, ly + r), fill=col if on else INK, outline=col, width=3)
        _t(d, (x, ly - 26), names[k], lf, col, anchor="ms")
        if show_prices:
            _t(d, (x, ly + 42), px(levels.get(k)), pf, WHITE if k == "entry" else SILVER, anchor="ms")


def _curve(img: Image.Image, box, values: list[float], baseline: float = 0.0) -> None:
    vals = [v for v in (_num(x) for x in values) if v is not None]
    if len(vals) < 2:
        return
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0, x1, y1 = box
    lo, hi = min(vals + [baseline]), max(vals + [baseline])
    span = (hi - lo) or 1.0
    X = lambda i: x0 + i / (len(vals) - 1) * (x1 - x0)          # noqa: E731
    Y = lambda v: y1 - (v - lo) / span * (y1 - y0)              # noqa: E731
    by = Y(baseline)
    d.line([(x0, by), (x1, by)], fill=LINE + (255,), width=1)
    pts = [(X(i), Y(v)) for i, v in enumerate(vals)]
    for i in range(len(pts) - 1):
        up = (vals[i] + vals[i + 1]) / 2 >= baseline
        d.line([pts[i], pts[i + 1]], fill=(GREEN if up else RED) + (255,), width=3)
    ex, ey = pts[-1]
    d.ellipse((ex - 6, ey - 6, ex + 6, ey + 6), fill=_pl(vals[-1] - baseline or 1) + (255,))


TARGET = {"TP1": "TARGET 1 HIT", "TP2": "TARGET 2 HIT", "TP3": "ALL TARGETS HIT", "STOPPED": "STOPPED OUT"}
HIT = {"TP1": "TP1", "TP2": "TP1 · TP2", "TP3": "TP1 · TP2 · TP3"}


def _status_label(x: dict[str, Any], default: str) -> str:
    st = str(x.get("status") or "")
    if st == "EXPIRED" or x.get("exit_reason") == "admin_close":
        return "WIN AT MARKET" if (_num(x.get("return_pct")) or 0) > 0 else "LOSS AT MARKET"
    return TARGET.get(st, default)


def _sample(n: int) -> str:
    return (f"{n} closed signals: too few to judge (needs {MIN_JUDGE})" if n < MIN_JUDGE
            else f"{n} closed signals")


# ---- cards ----------------------------------------------------------------------------------------------------

def result_card(w: dict[str, Any]) -> bytes:
    """One closed signal, win or loss, same layout (losses are never dressed up). Headline = net price move."""
    val, lev, net = result(w)
    win = net > 0
    status = str(w.get("status") or "")
    side = _side(w["side"])
    img, d = _base(f"Signal closed {'in profit' if win else 'at a loss'}  ·  {pair(w['symbol'])}  ·  {str(w['timeframe']).upper()}",
                   "SIGNAL RESULT")
    LW = 640                                               # left column width
    y = BODY[0]
    col = GREEN if win else RED
    x = _pill(d, M, y, _status_label(w, "CLOSED IN PROFIT" if win else "CLOSED"), col,
              bg=tuple(int(c * 0.14 + INK[i] * 0.86) for i, c in enumerate(col)), outline=col)
    x = _side_pill(d, x + 10, y, side)
    _pill(d, x + 10, y, str(w["timeframe"]).upper(), SILVER)
    _coin_title(d, M, y + 140, w["symbol"], LW)
    _label(d, (M, y + 196), "Net result after fees and funding", GOLD)
    _hero(d, M, y + 316, net, LW)
    sub = (f"At {lev}x margin: {pct(val)} on margin. Leverage magnifies losses too." if lev
           else "Half closed at TP1, a quarter at TP2 and at TP3.")
    sf = _fit(d, sub, "Medium", 21, LW, 15)
    _t(d, (M, y + 362), _clip(d, sub, sf, LW), sf, SILVER)
    # right: facts
    rx = M + LW + GAP
    _cells(d, (rx, y, W - M, y + 382), [("Entry", px(w.get("entry")), GOLD), ("Closed at", px(w.get("exit_price")), WHITE),
                                        ("Targets hit", HIT.get(status, "none"), GREEN if status in HIT else SILVER),
                                        ("Held", str(w.get("held") or "—"), WHITE)], cols=1)
    # rail across the bottom
    hit = {"TP1": {"tp1"}, "TP2": {"tp1", "tp2"}, "TP3": {"tp1", "tp2", "tp3"}}.get(status, set())
    if status == "STOPPED":
        hit = {"stop"}
    _panel(d, (M, y + 410, W - M, BODY[1]))
    _label(d, (M + 24, y + 448), "How the signal played out", SILVER, 17)
    _rail(d, (M, y + 440, W - M, BODY[1]), side, {k: w.get(k) for k in ("stop", "entry", "tp1", "tp2", "tp3")}, hit)
    _footer(d, "Every result is published, wins and losses")
    return _png(img)


def win_card(w: dict[str, Any]) -> bytes:
    return result_card(w)


def wins_card(wins: list[dict[str, Any]], period: str = "today", closed: int | None = None,
              losses: int | None = None) -> bytes:
    """Wins of the day / week next to the whole window's tally (losses included)."""
    when = "today" if period == "today" else "this week"
    img, d = _base(f"Signals closed {when}  ·  net after fees", "WINS " + ("TODAY" if period == "today" else "THIS WEEK"))
    LW = 420
    y = BODY[0]
    n = len(wins)
    _label(d, (M, y + 22), "Winning signals", GOLD)
    _t(d, (M, y + 130), str(n), _f("Bold", 112), WHITE)
    if closed is not None and losses is not None:
        _cells(d, (M, y + 170, M + LW, y + 330), [("Closed", str(closed), WHITE), ("Wins", str(max(0, closed - losses)), GREEN),
                                                  ("Losses", str(losses), RED)], cols=3)
        note = "Every closed signal counts, losses included."
    else:
        note = "Losses are published in the app as well."
    ny = y + 372 if closed is not None and losses is not None else y + 186
    for i, ln in enumerate(_wrap(d, note, _f("Medium", 20), LW, 2)):
        _t(d, (M, ny + i * 30), ln, _f("Medium", 20), SILVER)
    # right: the wins
    rx, rw = M + LW + GAP, W - M - (M + LW + GAP)
    rows = wins[:5]
    top, bottom = y, BODY[1] - (36 if n > len(rows) else 0)
    rh = min(112, (bottom - top - 10 * max(0, len(rows) - 1)) / max(1, len(rows)))
    for i, x in enumerate(rows):
        yy = top + i * (rh + 10)
        _panel(d, (rx, yy, W - M, yy + rh))
        side = _side(x["side"])
        val, lev, net = result(x)
        fig = pct(net)
        ff = _f("Bold", int(min(40, rh * 0.38)))
        fw = d.textlength(fig, font=ff)
        _t(d, (W - M - 24, yy + rh / 2 + 4), fig, ff, _pl(net), anchor="rs")
        name_w = rw - 48 - fw - 24
        cf = _fit(d, coin(x["symbol"]), "Bold", int(min(34, rh * 0.32)), name_w, 16)
        _t(d, (rx + 24, yy + rh / 2 - 4), _clip(d, coin(x["symbol"]), cf, name_w), cf, WHITE)
        meta = f"{side} · {str(x['timeframe']).upper()} · {_status_label(x, 'IN PROFIT').title()}" + (f" · {lev}x: {pct(val)}" if lev else "")
        mf = _fit(d, meta, "Medium", 17, name_w, 13)
        _t(d, (rx + 24, yy + rh / 2 + 26), _clip(d, meta, mf, name_w), mf, SILVER)
    if n > len(rows):
        _label(d, (W - M, BODY[1] - 6), f"+ {n - len(rows)} more in the app", SILVER, 18, anchor="rs")
    _footer(d, "Net after fees · leverage magnifies losses")
    return _png(img)


def _week_range(r: dict[str, Any]) -> str:
    f = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b")  # noqa: E731
    return f"{f(r['week_start'])} – {f(r['week_end'] - 1)}"


def weekly_card(r: dict[str, Any]) -> bytes:
    """Last week's totals (wins AND losses), the running total and the best signals."""
    img, d = _base(f"Weekly results  ·  {_week_range(r)}  ·  net after fees", "WEEKLY REPORT")
    n = int(r.get("closed") or 0)
    tot = float(r["total_return_pct"])
    LW = 560
    y = BODY[0]
    _label(d, (M, y + 22), "Total net price move, equal size per signal", GOLD)
    _hero(d, M, y + 140, tot, LW, 104)
    roi = r.get("total_roi_pct")
    sub = f"On margin at each signal's leverage: {pct(float(roi))}. Leverage magnifies losses too." if roi is not None else _sample(n)
    for i, ln in enumerate(_wrap(d, sub, _f("Medium", 20), LW, 2)):
        _t(d, (M, y + 182 + i * 28), ln, _f("Medium", 20), SILVER)
    wr = f"{float(r['win_rate'] or 0):.0%}"
    _cells(d, (M, y + 250, M + LW, y + 400), [("Closed", str(n), WHITE), ("Wins", str(r["wins"]), GREEN),
                                              ("Losses", str(r["losses"]), RED), ("Won", wr, WHITE)], cols=4)
    if roi is not None:
        _t(d, (M, y + 436), _sample(n), _f("Medium", 19), GOLD if n < MIN_JUDGE else SILVER)
    # right: curve + best
    rx = M + LW + GAP
    curve = [c if not isinstance(c, dict) else c.get("v", c.get("value")) for c in (r.get("curve") or [])]
    cy1 = y + 250
    _panel(d, (rx, y, W - M, cy1))
    _label(d, (rx + 22, y + 36), "Running total through the week", SILVER, 17)
    if len(curve) >= 2:
        _curve(img, (rx + 22, y + 58, W - M - 22, cy1 - 22), curve)
        d = ImageDraw.Draw(img)
    else:
        _label(d, (rx + 22, y + 140), "Not enough closed signals for a line yet.", MUTED, 18)
    best = [t for t in (r.get("best") or []) if float(t["return_pct"]) > 0][:3]
    by = cy1 + GAP
    if best:
        rh = min(70, (BODY[1] - by - 8 * (len(best) - 1)) / len(best))
        for t in best:
            _panel(d, (rx, by, W - M, by + rh))
            side = _side(t["side"])
            fig = pct(float(t["return_pct"]))
            ff = _f("Bold", 28)
            fw = d.textlength(fig, font=ff)
            _t(d, (W - M - 20, by + rh / 2 + 10), fig, ff, _pl(float(t["return_pct"])), anchor="rs")
            lab = f"{coin(t['symbol'])}  ·  {side}  ·  {str(t['timeframe']).upper()}"
            lf = _fit(d, lab, "SemiBold", 22, W - M - rx - 60 - fw, 14)
            _t(d, (rx + 20, by + rh / 2 + 8), _clip(d, lab, lf, W - M - rx - 60 - fw), lf, WHITE)
            by += rh + 8
    _footer(d, "Past results do not guarantee future results")
    return _png(img)


def teaser_card(s: dict[str, Any], mins: int) -> bytes:
    """A free grade-A call members received earlier (the levels are the free sample)."""
    side = _side(s["side"])
    img, d = _base(f"Members received this {mins // 60} h {mins % 60:02d} min ago  ·  prices may have moved", "FREE SIGNAL")
    from ..engine.futures import in_policy, signal_leverage
    lev = s.get("leverage") or signal_leverage(s.get("entry"), s.get("stop"), symbol=s.get("symbol"),
                                               grade=s.get("grade") or "A", timeframe=s.get("timeframe"))
    LW = 600
    y = BODY[0]
    x = _pill(d, M, y, f"GRADE {s.get('grade') or 'A'}", GOLD, bg=GOLD_BG)
    x = _pill(d, x + 10, y, str(s["timeframe"]).upper(), SILVER)
    if lev:
        _pill(d, x + 10, y, f"{lev}x {'BY ENGINE' if in_policy(s.get('timeframe')) else 'SUGGESTED'}", SILVER)
    _coin_title(d, M, y + 140, s["symbol"], LW)
    col = GREEN if side == "LONG" else RED
    act = "GO LONG" if side == "LONG" else "GO SHORT"
    af = _f("Bold", 64)
    tri = ([(M, y + 236), (M + 44, y + 236), (M + 22, y + 196)] if side == "LONG" else [(M, y + 196), (M + 44, y + 196), (M + 22, y + 236)])
    d.polygon(tri, fill=col)
    _t(d, (M + 62, y + 238), act, af, col)
    note = "The grade ranks how many checks agree; it is not a chance of winning."
    for i, ln in enumerate(_wrap(d, note, _f("Medium", 20), LW, 2)):
        _t(d, (M, y + 286 + i * 28), ln, _f("Medium", 20), SILVER)
    rx = M + LW + GAP
    _cells(d, (rx, y, W - M, y + 382), [("Entry", px(s.get("entry")), GOLD), ("Stop-loss", px(s.get("stop")), RED),
                                        ("Target 1 · close 50%", px(s.get("tp1")), WHITE), ("Target 2 · close 25%", px(s.get("tp2")), WHITE),
                                        ("Target 3 · close 25%", px(s.get("tp3")), WHITE), ("Leverage", f"{lev}x" if lev else "—", WHITE)], cols=2)
    _panel(d, (M, y + 410, W - M, BODY[1]))
    _label(d, (M + 24, y + 448), "The plan: stop, entry and targets", SILVER, 17)
    _rail(d, (M, y + 440, W - M, BODY[1]), side, {k: s.get(k) for k in ("stop", "entry", "tp1", "tp2", "tp3")}, set())
    _footer(d, "Members get every signal the moment it appears")
    return _png(img)


def week7_card(r: dict[str, Any], now: int) -> bytes:
    """Last 7 days of the public record, net after fees: count, win share, average, best / worst, sample note."""
    f = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b")  # noqa: E731
    img, d = _base(f"Last 7 days  ·  {f(now - 7 * 86_400_000)} – {f(now)}  ·  net after fees", "7-DAY RECORD")
    n = int(r.get("closed") or 0)
    avg = float(r["avg_return_pct"]) if r.get("avg_return_pct") is not None else 0.0
    LW = 560
    y = BODY[0]
    _label(d, (M, y + 22), "Average net result per signal", GOLD)
    _hero(d, M, y + 140, avg, LW, 104)
    _t(d, (M, y + 184), f"{n} closed signal{'s' if n != 1 else ''}, wins and losses, equal size", _f("Medium", 20), SILVER)
    wr = f"{float(r['win_rate']):.0%}" if r.get("win_rate") is not None else "—"
    wins = int(r.get("wins") or 0)
    _cells(d, (M, y + 230, M + LW, y + 380), [("Closed", str(n), WHITE), ("Wins", str(wins), GREEN),
                                              ("Losses", str(max(0, n - wins)), RED), ("Won", wr, WHITE)], cols=4)
    note = r.get("sample_note") or _sample(n)
    for i, ln in enumerate(_wrap(d, note, _f("Medium", 20), LW, 3)):
        _t(d, (M, y + 420 + i * 28), ln, _f("Medium", 20), GOLD if n < MIN_JUDGE else SILVER)
    rx = M + LW + GAP
    bh = (BODY[1] - y - GAP) / 2
    for i, (lab, x) in enumerate((("Best", r.get("best")), ("Worst", r.get("worst")))):
        yy = y + i * (bh + GAP)
        _panel(d, (rx, yy, W - M, yy + bh))
        _label(d, (rx + 24, yy + 42), lab, GOLD if i == 0 else SILVER)
        if x:
            fig = pct(float(x["return_pct"]))
            ff = _f("Bold", 48)
            fw = d.textlength(fig, font=ff)
            _t(d, (W - M - 24, yy + bh / 2 + 36), fig, ff, _pl(float(x["return_pct"])), anchor="rs")
            name = f"{coin(x['symbol'])} {_side(x['side'])} · {str(x['timeframe']).upper()}"
            room = W - M - rx - 72 - fw
            nf = _fit(d, name, "SemiBold", 28, room, 15)
            _t(d, (rx + 24, yy + bh / 2 + 30), _clip(d, name, nf, room), nf, WHITE)
        else:
            _label(d, (rx + 24, yy + bh / 2 + 30), "—", SILVER, 26)
    _footer(d, "Past results do not guarantee future results")
    return _png(img)


def _dial(d, cx: float, cy: float, r: float, value: float) -> None:
    """Breadth dial: half ring, red (few coins up) to green (most coins up); a white needle (no glow)."""
    steps = 48
    for i in range(steps):
        a0 = 180 + i * 180 / steps
        t = i / (steps - 1)
        c = tuple(int(RED[j] + (GREEN[j] - RED[j]) * t) for j in range(3)) if 0.4 > t or t > 0.6 else MUTED
        d.arc((cx - r, cy - r, cx + r, cy + r), a0, a0 + 180 / steps + 0.5, fill=c, width=14)
    a = math.radians(270 + 90 * max(-1.0, min(1.0, value)))
    d.line([(cx, cy), (cx + (r - 30) * math.cos(a), cy + (r - 30) * math.sin(a))], fill=WHITE, width=5)
    d.ellipse((cx - 11, cy - 11, cx + 11, cy + 11), fill=WHITE)


def briefing_card(b: dict[str, Any]) -> bytes:
    """The AI market briefing: mood, breadth dial, the text and the key facts."""
    at = int(b.get("at") or 0)
    when = datetime.fromtimestamp(at / 1000, timezone.utc).strftime("%d %b  ·  %H:%M UTC") if at else ""
    img, d = _base(f"Market briefing  ·  {when}  ·  context, not advice", "AI BRIEFING")
    mood = str(b.get("mood") or "")
    word, col = {"BULL": ("Leaning bullish", GREEN), "BEAR": ("Leaning bearish", RED)}.get(mood, ("Mixed", WHITE))
    val = {"BULL": 0.5, "BEAR": -0.5}.get(mood, 0.0)
    br = ((b.get("facts") or {}).get("breadth") or {}) if isinstance(b.get("facts"), dict) else {}
    share = None
    try:
        of = float(br.get("of") or 0)
        if of > 0:
            share = float(br.get("above_ema50_4h") or 0) / of
            val = max(-1.0, min(1.0, 2 * share - 1))
    except (TypeError, ValueError, AttributeError):
        pass
    LW = 420
    y = BODY[0]
    _label(d, (M, y + 22), "Market mood (4H)", GOLD)
    _t(d, (M, y + 84), word, _fit(d, word, "Bold", 50, LW), col)
    if b.get("source") == "ai":
        _pill(d, M, y + 110, "AI SUMMARY", CYAN, bg=(18, 44, 44))
    _dial(d, M + LW / 2, y + 330, 150, val)
    if share is not None:
        cap = f"{share:.0%} of coins above their 4H average"
        _t(d, (M + LW / 2, y + 380), cap, _fit(d, cap, "Medium", 19, LW, 14), SILVER, anchor="ms")
    # right: the text and the facts
    rx, rw = M + LW + GAP, W - M - (M + LW + GAP)
    body = _f("Regular", 26)
    lines = _wrap(d, str(b.get("text") or ""), body, rw, 6)
    yy = y + 22
    for ln in lines:
        _t(d, (rx, yy + 8), ln, body, WHITE)
        yy += 38
    bullets = [_wrap(d, str(t), _f("Medium", 21), rw - 70, 2) for t in (b.get("bullets") or [])[:4]]
    if bullets:
        need = 56 + sum(30 * len(x) + 16 for x in bullets)
        top = max(yy + 16, BODY[1] - need)
        if top + need > BODY[1]:                       # trim facts until they fit
            while bullets and top + 56 + sum(30 * len(x) + 16 for x in bullets) > BODY[1]:
                bullets.pop()
            need = 56 + sum(30 * len(x) + 16 for x in bullets)
        if bullets:
            _panel(d, (rx, top, W - M, top + need))
            _label(d, (rx + 24, top + 38), "Key facts", GOLD, 17)
            fy = top + 76
            for ln in bullets:
                d.ellipse((rx + 26, fy - 13, rx + 34, fy - 5), fill=GOLD)
                for j, part in enumerate(ln):
                    _t(d, (rx + 50, fy + j * 30), part, _f("Medium", 21), WHITE if j == 0 else SILVER)
                fy += 30 * len(ln) + 16
    _footer(d, "Context from measured data, not advice")
    return _png(img)


def news_card(m: dict[str, Any]) -> bytes:
    """High-impact US release heads-up: countdown, the release, why it matters, the signal pause."""
    img, d = _base("Economic calendar  ·  United States", "HIGH-IMPACT NEWS")
    at = int(_num(m.get("at")) or 0)
    mins = int(_num(m.get("mins")) or 0)
    event = str(m.get("event") or m.get("title") or "High-impact release")
    LW = 420
    y = BODY[0]
    _label(d, (M, y + 22), "Releasing in", GOLD)
    big = f"{mins} min" if mins else "Now"
    _t(d, (M, y + 140), big, _fit(d, big, "Bold", 104, LW), WHITE)
    if at:
        _t(d, (M, y + 184), datetime.fromtimestamp(at / 1000, timezone.utc).strftime("%H:%M UTC  ·  %a %d %b"), _f("Medium", 21), SILVER)
    _label(d, (M, y + 250), "Impact", SILVER)
    for i in range(3):
        bx = M + i * 34
        d.rounded_rectangle((bx, y + 300 - (i + 1) * 18, bx + 24, y + 300), radius=4, fill=RED)
    _t(d, (M + 118, y + 298), "High", _f("SemiBold", 26), RED)
    rx, rw = M + LW + GAP, W - M - (M + LW + GAP)
    _panel(d, (rx, y, W - M, y + 190))
    _label(d, (rx + 24, y + 40), "The release", GOLD, 17)
    ef = _fit(d, event, "Bold", 34, (rw - 48) * 2.2, 22)
    for j, ln in enumerate(_wrap(d, event, ef, rw - 48, 3 if ef.size <= 26 else 2)):
        _t(d, (rx + 24, y + 92 + j * (ef.size + 10)), ln, ef, WHITE)
    why = str(m.get("why") or "").strip() or "Big US data releases often move Bitcoin and the whole market both ways within minutes."
    _label(d, (rx, y + 234), "Why it matters", GOLD, 17)
    for i, ln in enumerate(_wrap(d, why, _f("Medium", 23), rw, 4)):
        _t(d, (rx, y + 274 + i * 34), ln, _f("Medium", 23), WHITE)
    # signal pause strip across the bottom: -45 min ... release ... +30 min
    sy = BODY[1] - 120
    _panel(d, (M, sy, W - M, BODY[1]))
    _label(d, (M + 24, sy + 38), "New signals pause around it", SILVER, 18)
    bx0, bx1, by = M + 60, W - M - 60, sy + 70
    d.rounded_rectangle((bx0, by - 5, bx1, by + 5), radius=5, fill=PANEL_HI)
    p0, p1 = bx0 + (bx1 - bx0) * 0.15, bx0 + (bx1 - bx0) * 0.85
    rel = p0 + (p1 - p0) * 45 / 75
    d.rounded_rectangle((p0, by - 5, p1, by + 5), radius=5, fill=RISK_BG)
    d.ellipse((rel - 10, by - 10, rel + 10, by + 10), fill=RED)
    for x, t in ((p0, "−45 min"), (rel, "release"), (p1, "+30 min")):
        _t(d, (x, by + 36), t, _f("SemiBold", 18), WHITE if t == "release" else SILVER, anchor="ms")
    _footer(d, "Calendar fact, not advice")
    return _png(img)


# ---- checks -----------------------------------------------------------------------------------------------------

def layout_boxes(fn, *args) -> list[tuple[float, float, float, float, str]]:
    """Render a card and return every text box it drew (used by the no-overlap tests)."""
    global _BOXES
    _BOXES = []
    try:
        fn(*args)
        return list(_BOXES)
    finally:
        _BOXES = None


def overlaps(boxes: list[tuple[float, float, float, float, str]], pad: float = 2.0) -> list[tuple[str, str]]:
    """Pairs of texts whose boxes touch (pad px apart at least) and texts outside the safe frame."""
    out = []
    for i, a in enumerate(boxes):
        if a[0] < M - 1 or a[2] > W - M + 1 or a[1] < M - 8 or a[3] > H - M + 12:
            out.append((a[4], "outside the safe frame"))
        for b in boxes[i + 1:]:
            if a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad:
                out.append((a[4], b[4]))
    return out
