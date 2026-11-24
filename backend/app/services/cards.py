"""Share images for Telegram and social posts: one design family (v2.77, owner brief 22 Nov 2026).

v2.77 "Midnight & gold": every card is a 1080 x 1350 portrait (4:5 - fills a phone screen in Telegram and fits an Instagram
feed post). Deep midnight-navy background with a cool light top right and a faint warm light bottom left, one thin gold orbit
arc (the logo's orbit) as the only decoration, a hairline frame with short gold corner marks. Same header on every card (logo,
spaced wordmark, one context line, the card's kind in a gold-outlined tag) and the same footer (site, note, brand line).
Type: Sora for titles and figures, Inter for text. Colour rules: gold only for brand marks, the entry and key labels; green =
a gain / a reached target, red = a loss / the stop, silver for supporting text. Signature element: the TRADE RAIL (stop ->
entry -> TP1-3, reached points lit) on signal and result cards - the app's own picture of a trade.

Cards: result_card / win_card (one closed signal, win or loss), wins_card (wins of the day / week, with the losses count),
weekly_card, week7_card, teaser_card (a free signal), briefing_card (AI market briefing with the mood dial), news_card
(high-impact release heads-up). The numbers on a card are exactly the ones in the caption (the real record), wins and losses
alike. Each function returns PNG bytes (palette-quantised; Telegram drafts keep up to 6 cards in one 1 MB document).
"""
from __future__ import annotations

import io
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import brand
from ..pricefmt import fmt_price

ASSETS = Path(__file__).resolve().parent.parent / "assets"
W, H = 1080, 1350
M = 72                                       # outer margin
# V3.1 (owner, 24 Nov 2026: "rework all the shareable cards", Binance font structure): graphite, IBM Plex Sans only,
# flat figures (no glow), Binance-style greens / reds / greys, the logo's neural mesh (cyan links, green / red neurons)
# in the top-right corner, a solid footer band with a gold rule.
INK = (16, 17, 20)                           # page bottom
NAVY = (23, 24, 29)                          # page top
PANEL = (28, 29, 35)                         # card surface
PANEL_HI = (37, 38, 46)
LINE = (48, 50, 58)                          # hairline
GOLD = (232, 182, 55)                        # the logo's gold (brand, entry, key labels)
GOLD_LIGHT = (246, 227, 122)
GOLD_DIM = (120, 92, 24)
WHITE = (234, 236, 239)
SILVER = (132, 142, 156)
MUTED = (94, 102, 115)
GREEN = (14, 203, 129)
RED = (246, 70, 93)
CYAN = (93, 241, 221)
COOL = (70, 110, 190)
FOOT = (13, 14, 17)
GOLD_SOFT = GOLD                              # old names kept for callers
AI = GOLD_LIGHT

SITE_TEXT = brand.DISPLAY_URL
_fonts: dict[tuple[str, str, int], ImageFont.FreeTypeFont] = {}
_PLEX = {"Regular": "Regular", "Medium": "Medium", "SemiBold": "SemiBold", "Bold": "Bold", "ExtraBold": "Bold"}


def _f(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """IBM Plex Sans (every text on a card)."""
    key = ("plex", weight, size)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(str(ASSETS / "fonts" / f"IBMPlexSans-{_PLEX.get(weight, 'Medium')}.ttf"), size)
        except OSError:
            try:
                _fonts[key] = ImageFont.truetype(str(ASSETS / "fonts" / f"Inter-{weight}.otf"), size)
            except OSError:
                _fonts[key] = ImageFont.load_default(size)
    return _fonts[key]


def _s(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """Titles and figures: the same family (one typeface, Binance style)."""
    return _f(weight, size)


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
    """(headline %, leverage or None, price move %): ROI on margin when the leverage is known, else the price move."""
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


# ---- drawing primitives ---------------------------------------------------------------------------------------

def _cap(font: ImageFont.FreeTypeFont) -> int:
    """Cap height: centres capitals optically inside pills and rows."""
    return -font.getbbox("H", anchor="ls")[1]


def _tw(d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    return int(round(d.textlength(text, font=font)))


def _fit(d: ImageDraw.ImageDraw, text: str, weight: str, size: int, max_w: int, sora: bool = False) -> ImageFont.FreeTypeFont:
    mk = _s if sora else _f
    while size > 14 and d.textlength(text, font=mk(weight, size)) > max_w:
        size -= 2
    return mk(weight, size)


def _spaced(d: ImageDraw.ImageDraw, xy, text: str, font, fill, track: float, anchor: str = "ls") -> int:
    """Letter-spaced capitals. anchor 'ls' (left) or 'rs' (right end at x)."""
    width = sum(d.textlength(ch, font=font) + track for ch in text) - track
    x, y = xy
    if anchor == "rs":
        x -= width
    elif anchor == "ms":
        x -= width / 2
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill, anchor="ls")
        x += d.textlength(ch, font=font) + track
    return int(width)


def _glow(img: Image.Image, draw_fn, color, radius: int, strength: float = 1.0) -> None:
    mask = Image.new("L", img.size, 0)
    draw_fn(ImageDraw.Draw(mask))
    mask = mask.filter(ImageFilter.GaussianBlur(radius))
    if strength != 1.0:
        mask = mask.point(lambda v: min(255, int(v * strength)))
    img.paste(Image.new("RGB", img.size, color), (0, 0), mask)


def _grad_text(img: Image.Image, xy, text: str, font, top, bottom, anchor: str = "ls") -> int:
    """Text filled with a soft vertical gradient (figures)."""
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=font, fill=255, anchor=anchor)
    box = mask.getbbox()
    if not box:
        return 0
    x0, y0, x1, y1 = box
    h = max(1, y1 - y0)
    grad = Image.new("RGB", (x1 - x0, h))
    gd = ImageDraw.Draw(grad)
    for i in range(h):
        t = i / h
        gd.line([(0, i), (x1 - x0, i)], fill=tuple(int(top[c] + (bottom[c] - top[c]) * t) for c in range(3)))
    img.paste(grad, (x0, y0), mask.crop(box))
    return x1 - x0


def _figure(img: Image.Image, xy, value: float, font, anchor: str = "ls", text: str | None = None) -> int:
    """A result figure: flat green for a gain, red for a loss, white for nothing (V3.1: no glow, no gradient)."""
    t = text if text is not None else pct(value)
    col = GREEN if value > 0 else RED if value < 0 else WHITE
    d = ImageDraw.Draw(img)
    d.text(xy, t, font=font, fill=col, anchor=anchor)
    return int(d.textlength(t, font=font))


def _pill(d: ImageDraw.ImageDraw, x: int, y: int, text: str, fg, bg=None, outline=None, size: int = 17, h: int = 40,
          align: str = "left", w: int | None = None, track: float = 0.6) -> int:
    """Tag (V3.1: Binance-style rounded rectangle, light tracking); top-left (top-right for align='right') at x, y."""
    fn = _f("SemiBold", max(size, 17))
    track = min(track, 1.0)
    tw = sum(d.textlength(ch, font=fn) + track for ch in text) - track
    w = max(w or 0, int(tw) + 2 * 16)
    x0 = x if align == "left" else x - w
    d.rounded_rectangle((x0, y, x0 + w, y + h), radius=8, fill=bg, outline=outline, width=1 if outline else 0)
    _spaced(d, (x0 + w / 2, y + h / 2 + _cap(fn) / 2), text, fn, fg, track, anchor="ms")
    return x0 + w if align == "left" else x0


def _side_pill(d, x, y, side: str, **kw) -> int:
    col = GREEN if side == "LONG" else RED
    return _pill(d, x, y, side, col, bg=tuple(int(c * 0.16 + INK[i] * 0.84) for i, c in enumerate(col)), outline=col, **kw)


def _chip(d, x, y, text, **kw) -> int:
    return _pill(d, x, y, text, SILVER, bg=PANEL_HI, outline=LINE, **kw)


def _gold_chip(d, x, y, text, **kw) -> int:
    return _pill(d, x, y, text, GOLD, bg=(44, 37, 18), outline=None, **kw)


def _panel(d: ImageDraw.ImageDraw, box, fill=PANEL, outline=LINE, r: int = 16) -> None:
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=1)


def _label(d, xy, text, size: int = 15, fill=SILVER, anchor: str = "ls") -> int:
    """V3.1: sentence-case label (no spaced capitals)."""
    t = str(text)
    t = t[:1].upper() + t[1:]
    fn = _f("Medium", max(18, size + 3))
    d.text(xy, t, font=fn, fill=fill, anchor="ls" if anchor == "ls" else anchor)
    return int(d.textlength(t, font=fn))


def _background(img: Image.Image) -> None:
    """V3.1: graphite (lighter at the top), the logo's neural mesh in the top-right corner (cyan links, neurons green / red)."""
    import numpy as np
    yy = np.linspace(0, 1, H)[:, None, None]
    arr = np.array(NAVY, float) * (1 - yy) + np.array(INK, float) * yy
    arr = np.broadcast_to(arr, (H, W, 3)).copy()
    yy2, xx2 = np.mgrid[0:H, 0:W].astype(float)
    warm = np.clip(1 - np.hypot(xx2 - W * 0.92, yy2 - H * 0.0) / (W * 0.75), 0, 1) ** 2
    arr += warm[..., None] * np.array(GOLD, float) * 0.06
    img.paste(Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB"))
    d = ImageDraw.Draw(img, "RGBA")
    rng = np.random.default_rng(13)
    pts = []
    while len(pts) < 22:
        x, y = W * (0.52 + rng.random() * 0.5), H * (rng.random() * 0.13)
        if not (x > W - M - 260 and 50 < y < 130):          # keep clear of the kind tag
            pts.append((x, y))
    lim = W * 0.13
    for i, p in enumerate(pts):
        for q in pts[i + 1:]:
            dist = ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5
            if dist < lim:
                d.line([p, q], fill=CYAN + (int(70 * (1 - dist / lim)),), width=1)
    for i, (x, y) in enumerate(pts):
        c = RED if i % 2 else GREEN
        d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=c + (150,))


def _frame(img: Image.Image) -> None:
    """V3.1: no frame (the footer band closes the card)."""
    return None


HEAD_Y = 176                                 # the header's divider


def _base(title: str, tag: str = "REAL RECORD") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Background and the header: logo tile, name, one context line, the card's kind; a divider under it."""
    img = Image.new("RGB", (W, H), INK)
    _background(img)
    ls, y0 = 76, 60
    try:
        logo = Image.open(ASSETS / "logo.png").convert("RGBA").resize((ls, ls), Image.LANCZOS)
        img.paste(logo, (M, y0), logo)
    except OSError:
        pass
    d = ImageDraw.Draw(img)
    tx = M + ls + 20
    d.text((tx, y0 + 34), "Crypto Intelligence AI", font=_f("SemiBold", 30), fill=WHITE, anchor="ls")
    tag = tag.replace("AI  ·  ", "").strip().upper()
    tag_w = _tw(d, tag, _f("SemiBold", 17)) + 40
    d.text((tx, y0 + 66), title, font=_fit(d, title, "Regular", 21, W - 2 * M - ls - 20 - tag_w - 24), fill=SILVER, anchor="ls")
    _pill(d, W - M, y0 + 18, tag, GOLD, bg=(44, 37, 18), size=17, h=40, align="right")
    d.line([(M, HEAD_Y - 8), (W - M, HEAD_Y - 8)], fill=LINE, width=1)
    return img, d


FOOT_Y = H - 118                             # top of the footer band


def _footer(d: ImageDraw.ImageDraw, note: str = "Analysis only, not financial advice", img: Image.Image | None = None) -> None:
    d.rectangle((0, FOOT_Y, W, H), fill=FOOT)
    d.rectangle((0, FOOT_Y, W, FOOT_Y + 2), fill=GOLD)
    d.text((M, FOOT_Y + 56), SITE_TEXT, font=_f("SemiBold", 28), fill=GOLD, anchor="ls")
    d.text((W - M, FOOT_Y + 56), note, font=_fit(d, note, "Medium", 20, W - 2 * M - 420), fill=WHITE, anchor="rs")
    d.text((M, FOOT_Y + 92), brand.FOOTER, font=_fit(d, brand.FOOTER, "Regular", 17, W - 2 * M), fill=MUTED, anchor="ls")


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    # k-means refinement keeps the small brand colours (red / green figures) exact in the 256-colour palette
    img.quantize(256, method=Image.Quantize.MEDIANCUT, kmeans=3, dither=Image.Dither.FLOYDSTEINBERG).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _rail(img: Image.Image, box, side: str, levels: dict[str, float | None], hit: set[str], price: float | None = None,
          exit_at: float | None = None, show_prices: bool = True) -> None:
    """The trade rail: stop -> entry -> TP1-3 on one line (always drawn left = stop, right = last target), positions by
    price when the levels are known; reached points lit green, the stop red when hit, the entry gold."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    keys = [k for k in ("stop", "entry", "tp1", "tp2", "tp3") if _num(levels.get(k)) is not None]
    if "entry" not in keys:
        keys = ["stop", "entry", "tp1", "tp2", "tp3"]
        pos = {k: i / 4 for i, k in enumerate(keys)}
    else:
        s = 1 if side == "LONG" else -1
        vals = {k: float(levels[k]) * s for k in keys}
        lo, hi = min(vals.values()), max(vals.values())
        span = (hi - lo) or 1.0
        pos = {k: (vals[k] - lo) / span for k in keys}
        # keep labels apart: at least 13 % between neighbours, in order
        order = sorted(keys, key=lambda k: pos[k])
        for i in range(1, len(order)):
            pos[order[i]] = max(pos[order[i]], pos[order[i - 1]] + 0.13)
        top = pos[order[-1]]
        if top > 1:
            for k in keys:
                pos[k] = pos[k] / top
    ly = (y0 + y1) // 2 - 14
    X = lambda p: x0 + 14 + p * (x1 - x0 - 28)                  # noqa: E731
    ex = X(pos.get("entry", 0.25))
    d.line([(X(0), ly), (X(1), ly)], fill=LINE, width=4)
    d.line([(X(0), ly), (ex, ly)], fill=(90, 44, 52), width=4)            # risk side
    reached = [k for k in ("tp1", "tp2", "tp3") if k in hit and k in pos]
    if reached:
        far = max(pos[k] for k in reached)
        _glow(img, lambda m: m.line([(ex, ly), (X(far), ly)], fill=200, width=8), GREEN, 7, 0.5)
        d = ImageDraw.Draw(img)
        d.line([(ex, ly), (X(far), ly)], fill=GREEN, width=4)
    if "stop" in hit and "stop" in pos:
        d.line([(X(pos["stop"]), ly), (ex, ly)], fill=RED, width=4)
    names = {"stop": "STOP", "entry": "ENTRY", "tp1": "TP1", "tp2": "TP2", "tp3": "TP3"}
    lf = _f("Bold", 14)
    pf = _f("SemiBold", 17)
    for k, p in pos.items():
        x = X(p)
        if k == "entry":
            d.polygon([(x, ly - 13), (x + 13, ly), (x, ly + 13), (x - 13, ly)], fill=GOLD, outline=GOLD_LIGHT)
            col = GOLD
        else:
            on = k in hit
            col = (RED if k == "stop" else GREEN) if on else (RED if k == "stop" else SILVER)
            r = 11 if on else 9
            d.ellipse((x - r, ly - r, x + r, ly + r), fill=col if on else INK, outline=col, width=3)
            if on and k != "stop":
                d.line([(x - 5, ly), (x - 1, ly + 4), (x + 6, ly - 4)], fill=INK, width=3)
        _spaced(d, (x, ly - 28), names[k], lf, col, 1.6, anchor="ms")
        if show_prices and _num(levels.get(k)) is not None:
            v = px(levels[k])
            pf_ = pf if d.textlength(v, font=pf) < 150 else _f("SemiBold", 14)
            d.text((x, ly + 40), v, font=pf_, fill=WHITE if k == "entry" else SILVER, anchor="ms")


def _stat_grid(d, box, cells: list[tuple[str, str, Any]], cols: int = 2) -> None:
    """Hairline grid of label / value cells."""
    x0, y0, x1, y1 = box
    _panel(d, box)
    rows = math.ceil(len(cells) / cols)
    cw, rh = (x1 - x0) / cols, (y1 - y0) / rows
    for i, (k, v, c) in enumerate(cells):
        cx, cy = x0 + (i % cols) * cw, y0 + (i // cols) * rh
        if i % cols:
            d.line([(cx, cy + 18), (cx, cy + rh - 18)], fill=LINE, width=1)
        if i >= cols:
            d.line([(cx + 18, cy), (cx + cw - 18, cy)], fill=LINE, width=1)
        _label(d, (cx + 28, cy + rh / 2 - 12), k, 14)
        d.text((cx + 28, cy + rh / 2 + 26), v, font=_fit(d, v, "SemiBold", 30, int(cw - 56), sora=True), fill=c, anchor="ls")


def _curve(img: Image.Image, box, values: list[float], baseline: float = 0.0) -> None:
    """Running total line: green above the baseline, red below, soft fill, end dot."""
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
    d.line([(x0, by), (x1, by)], fill=(156, 166, 186, 70), width=1)
    pts = [(X(i), Y(v)) for i, v in enumerate(vals)]
    for i in range(len(pts) - 1):
        (ax, ay), (bx, bys) = pts[i], pts[i + 1]
        up = (vals[i] + vals[i + 1]) / 2 >= baseline
        col = GREEN if up else RED
        d.polygon([(ax, ay), (bx, bys), (bx, by), (ax, by)], fill=col + (34,))
    for i in range(len(pts) - 1):
        up = (vals[i] + vals[i + 1]) / 2 >= baseline
        d.line([pts[i], pts[i + 1]], fill=(GREEN if up else RED) + (255,), width=4)
    ex, ey = pts[-1]
    end = GREEN if vals[-1] >= baseline else RED
    d.ellipse((ex - 9, ey - 9, ex + 9, ey + 9), fill=end + (255,), outline=WHITE + (255,), width=2)


def _wrap(d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
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
    return lines


def _coin_title(d, img, y: int, sym: str, max_w: int = W - 2 * M) -> int:
    """Ticker large in white, '/ USDT' small in silver beside it. Returns the baseline y."""
    c = coin(sym)
    f = _fit(d, c, "ExtraBold", 118, max_w - 170, sora=True)
    d.text((M, y), c, font=f, fill=WHITE, anchor="ls")
    if c not in ("GOLD", "SILVER"):
        d.text((M + _tw(d, c, f) + 16, y), "/ USDT", font=_s("SemiBold", 30), fill=SILVER, anchor="ls")
    return y


TARGET = {"TP1": "TARGET 1 HIT", "TP2": "TARGET 2 HIT", "TP3": "ALL TARGETS HIT", "STOPPED": "STOPPED OUT"}
HIT = {"TP1": "TP1", "TP2": "TP1 · TP2", "TP3": "TP1 · TP2 · TP3"}


def _status_label(x: dict[str, Any], default: str) -> str:
    """Result label; a call the admin closed at market says so (v2.8)."""
    st = str(x.get("status") or "")
    if st == "EXPIRED" or x.get("exit_reason") == "admin_close":
        # owner 24 Nov 2026: no grey area - a call closed at the market price is the win or loss it was
        return "WIN AT MARKET" if (_num(x.get("return_pct")) or 0) > 0 else "LOSS AT MARKET"
    return TARGET.get(st, default)


# ---- cards ----------------------------------------------------------------------------------------------------

def result_card(w: dict[str, Any]) -> bytes:
    """One closed signal, win or loss, in the same layout (losses are never dressed up)."""
    val, lev, price = result(w)
    win = float(w["return_pct"]) > 0
    status = str(w.get("status") or "")
    img, d = _base("Signal closed in profit" if win else "Signal closed at a loss", "REAL RECORD")
    side = _side(w["side"])
    y = 214
    lab = _status_label(w, "CLOSED IN PROFIT" if win else "CLOSED")
    col = GREEN if win else RED
    x = _pill(d, M, y, lab, col, bg=tuple(int(c * 0.16 + INK[i] * 0.84) for i, c in enumerate(col)), outline=col)
    x = _side_pill(d, x + 12, y, side)
    _chip(d, x + 12, y, str(w["timeframe"]).upper())
    _coin_title(d, img, 388, w["symbol"])
    # hero
    _label(d, (M, 474), "ROI on margin" if lev else "Price move after fees", 16, GOLD)
    fb = _s("ExtraBold", 168)
    while fb.size > 60 and d.textlength(pct(val), font=fb) > W - 2 * M:
        fb = _s("ExtraBold", fb.size - 8)
    _figure(img, (M - 4, 636), val, fb)
    d = ImageDraw.Draw(img)
    sub = f"{lev}x margin  ·  {pct(price)} price move after fees" if lev else "half at TP1, a quarter at TP2 and TP3"
    d.text((M, 690), sub, font=_f("Medium", 24), fill=SILVER, anchor="ls")
    # rail
    hit = {"TP1": {"tp1"}, "TP2": {"tp1", "tp2"}, "TP3": {"tp1", "tp2", "tp3"}}.get(status, set())
    if status == "STOPPED" or (not win and status not in HIT):
        hit = hit | ({"stop"} if status == "STOPPED" else set())
    _panel(d, (M, 736, W - M, 900))
    _rail(img, (M + 36, 752, W - M - 36, 900), side, {k: w.get(k) for k in ("stop", "entry", "tp1", "tp2", "tp3")}, hit)
    d = ImageDraw.Draw(img)
    _stat_grid(d, (M, 924, W - M, FOOT_Y - 48), [("Entry", px(w.get("entry")), WHITE), ("Closed at", px(w.get("exit_price")), WHITE),
                                           ("Targets hit", HIT.get(status, "none"), GREEN if status in HIT else SILVER),
                                           ("Held", str(w.get("held") or "—"), WHITE)])
    _footer(d, "Wins and losses are all public", img=img)
    return _png(img)


def win_card(w: dict[str, Any]) -> bytes:
    """One closed winning signal (the per-win Telegram post)."""
    return result_card(w)


def wins_card(wins: list[dict[str, Any]], period: str = "today", closed: int | None = None,
              losses: int | None = None) -> bytes:
    """Best winning signals of the day (or week), up to 6 rows, with the window's loss count beside them."""
    img, d = _base("Wins of the " + ("day" if period == "today" else "week"), "REAL RECORD")
    n = len(wins)
    d.text((M, 290), f"{n} win{'s' if n != 1 else ''}", font=_s("ExtraBold", 96), fill=WHITE, anchor="ls")
    if closed is not None and losses is not None:
        sub = f"{closed} closed {'today' if period == 'today' else 'this week'}  ·  {losses} loss{'es' if losses != 1 else ''}  ·  every result is public"
    else:
        sub = "Every result, wins and losses, is public in the app"
    d.text((M, 340), sub, font=_fit(d, sub, "Medium", 22, W - 2 * M), fill=SILVER, anchor="ls")
    best = max((result(x)[0] for x in wins), default=0.0)
    lev_any = any(result(x)[1] for x in wins)
    _label(d, (W - M, 198 + 20), "Best ROI" if lev_any else "Best move", 14, GOLD, anchor="rs")
    _figure(img, (W - M, 290), best, _s("ExtraBold", 56), anchor="rs")
    d = ImageDraw.Draw(img)
    rows = wins[:6]
    tally = closed is not None and losses is not None
    bottom = (FOOT_Y - 48 - 124 - 32) if tally else FOOT_Y - 48
    top, gap = 392, 14
    rh = int(max(96, min(170, (bottom - top) / max(1, len(rows)) - gap)))
    for i, x in enumerate(rows):
        y = top + i * (rh + gap)
        _panel(d, (M, y, W - M, y + rh))
        side = _side(x["side"])
        d.rounded_rectangle((M, y + 18, M + 5, y + rh - 18), radius=2, fill=GREEN if side == "LONG" else RED)
        cf = _fit(d, coin(x["symbol"]), "Bold", 36, 220, sora=True)
        mid = y + rh / 2
        d.text((M + 32, mid - 2), coin(x["symbol"]), font=cf, fill=WHITE, anchor="ls")
        sl = f"{side}  ·  {str(x['timeframe']).upper()}  ·  {_status_label(x, 'IN PROFIT').title()}"
        d.text((M + 32, mid + 32), sl, font=_f("Medium", 19), fill=SILVER, anchor="ls")
        val, lev, price = result(x)
        _figure(img, (W - M - 28, mid + 4), val, _s("ExtraBold", 40), anchor="rs")
        d = ImageDraw.Draw(img)
        d.text((W - M - 28, mid + 34), (f"{lev}x  ·  {pct(price)} move" if lev else "price move after fees"),
               font=_f("Medium", 17), fill=SILVER, anchor="rs")
    if n > len(rows):
        d.text((W - M, top + len(rows) * (rh + gap) + 14), f"+ {n - len(rows)} more in the app", font=_f("Medium", 18), fill=SILVER, anchor="rs")
    if tally:                               # the whole window, losses included
        ty = FOOT_Y - 48 - 124                  # anchored above the footer
        _stat_grid(d, (M, ty, W - M, ty + 124), [("Closed", str(closed), WHITE), ("Wins", str(max(0, closed - losses)), GREEN),
                                               ("Losses", str(losses), RED)], cols=3)
    _footer(d, "After fees · leverage magnifies losses", img=img)
    return _png(img)


def _week_range(r: dict[str, Any]) -> str:
    f = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b")  # noqa: E731
    return f"{f(r['week_start'])} – {f(r['week_end'] - 1)}"


def weekly_card(r: dict[str, Any]) -> bytes:
    """Last week's totals (wins AND losses), the running total and the best trades."""
    img, d = _base(f"Weekly results  ·  {_week_range(r)}", "WEEKLY REPORT")
    tot_price = float(r["total_return_pct"])
    roi = r.get("total_roi_pct")
    head = float(roi) if roi is not None else tot_price
    _label(d, (M, 238), "Total ROI on margin" if roi is not None else "Total price move", 16, GOLD)
    fb = _s("ExtraBold", 150)
    while fb.size > 60 and d.textlength(pct(head), font=fb) > W - 2 * M:
        fb = _s("ExtraBold", fb.size - 8)
    _figure(img, (M - 4, 390), head, fb)
    d = ImageDraw.Draw(img)
    sub = (f"{pct(tot_price)} price move after fees  ·  " if roi is not None else "") + f"{r.get('closed', 0)} closed signals, all counted"
    d.text((M, 440), sub, font=_fit(d, sub, "Medium", 22, W - 2 * M), fill=SILVER, anchor="ls")
    curve = r.get("curve") or []
    if len(curve) >= 2:
        _panel(d, (M, 480, W - M, 720))
        _label(d, (M + 28, 520), "Running total through the week", 13)
        _curve(img, (M + 28, 540, W - M - 28, 696), [c if not isinstance(c, dict) else c.get("v", c.get("value")) for c in curve])
        d = ImageDraw.Draw(img)
        ys = 744
    else:
        ys = 492
    cells = [("Closed", str(r.get("closed", 0)), WHITE), ("Wins", str(r["wins"]), GREEN), ("Losses", str(r["losses"]), RED),
             ("Win rate", f"{float(r['win_rate'] or 0):.0%}", WHITE)]
    _stat_grid(d, (M, ys, W - M, ys + 150), cells, cols=4)
    best = [t for t in (r.get("best") or []) if float(t["return_pct"]) > 0][:3]
    y = ys + 196
    if best:
        _label(d, (M, y), "Top signals", 14, GOLD)
        y += 22
        rh = max(64, min(96, (H - 176 - y) // max(1, len(best)) - 10))
        for t in best:
            _panel(d, (M, y, W - M, y + rh), r=18)
            side = _side(t["side"])
            d.text((M + 28, y + rh / 2 + 11), coin(t["symbol"]), font=_s("Bold", 30), fill=WHITE, anchor="ls")
            d.text((M + 220, y + rh / 2 + 8), f"{side}  ·  {str(t['timeframe']).upper()}", font=_f("Medium", 19),
                   fill=GREEN if side == "LONG" else RED, anchor="ls")
            val, lev, price = result(t)
            _figure(img, (W - M - 28, y + rh / 2 + 12), val, _s("ExtraBold", 32), anchor="rs")
            d = ImageDraw.Draw(img)
            y += rh + 10
    _footer(d, "Past results don't guarantee future results", img=img)
    return _png(img)


def teaser_card(s: dict[str, Any], mins: int) -> bytes:
    """A free grade-A call that members received earlier (levels shown: it is the free sample)."""
    side = _side(s["side"])
    img, d = _base(f"Members got this {mins // 60} h {mins % 60:02d} min ago", "FREE SIGNAL")
    from ..engine.futures import in_policy, signal_leverage
    lev = s.get("leverage") or signal_leverage(s.get("entry"), s.get("stop"), symbol=s.get("symbol"),
                                               grade=s.get("grade") or "A", timeframe=s.get("timeframe"))
    y = 214
    x = _gold_chip(d, M, y, f"GRADE {s.get('grade') or 'A'}")
    x = _chip(d, x + 12, y, str(s["timeframe"]).upper())
    if lev:
        _chip(d, x + 12, y, f"{lev}x {'BY ENGINE' if in_policy(s.get('timeframe')) else 'SUGGESTED'}")
    _coin_title(d, img, 388, s["symbol"])
    col = GREEN if side == "LONG" else RED
    act = "GO LONG" if side == "LONG" else "GO SHORT"
    af = _s("ExtraBold", 72)
    tri = ([(M, 492), (M + 52, 492), (M + 26, 446)] if side == "LONG" else [(M, 446), (M + 52, 446), (M + 26, 492)])
    _glow(img, lambda m: (m.polygon(tri, fill=255), m.text((M + 72, 500), act, font=af, fill=255, anchor="ls")), col, 12, 0.35)
    d = ImageDraw.Draw(img)
    d.polygon(tri, fill=col)
    d.text((M + 72, 500), act, font=af, fill=col, anchor="ls")
    d.text((M, 548), "The AI's trend reading and its forecast agree on this one.", font=_f("Medium", 22), fill=SILVER, anchor="ls")
    _panel(d, (M, 592, W - M, 756))
    _rail(img, (M + 36, 608, W - M - 36, 756), side, {k: s.get(k) for k in ("stop", "entry", "tp1", "tp2", "tp3")}, set())
    d = ImageDraw.Draw(img)
    cells = [("Entry", px(s.get("entry")), GOLD), ("Stop-loss", px(s.get("stop")), RED), ("Target 1 · close 50%", px(s.get("tp1")), GREEN),
             ("Target 2 · close 25%", px(s.get("tp2")), GREEN), ("Target 3 · close 25%", px(s.get("tp3")), GREEN),
             ("Leverage", f"{lev}x" if lev else "—", WHITE)]
    _stat_grid(d, (M, 780, W - M, FOOT_Y - 110), cells, cols=2)
    d.text((M, FOOT_Y - 56), "Members get every signal the moment it appears, with phone alerts.", font=_f("Medium", 20), fill=SILVER, anchor="ls")
    _footer(d, "Not financial advice · prices may have moved", img=img)
    return _png(img)


def week7_card(r: dict[str, Any], now: int) -> bytes:
    """Last 7 days of the public record after fees: closed count, win rate, average, best / worst, sample-size note."""
    f = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b")  # noqa: E731
    img, d = _base(f"Last 7 days  ·  {f(now - 7 * 86_400_000)} – {f(now)}  ·  after fees", "7-DAY RECORD")
    n = int(r.get("closed") or 0)
    avg = float(r["avg_return_pct"]) if r.get("avg_return_pct") is not None else 0.0
    _label(d, (M, 238), "Average per signal", 16, GOLD)
    _figure(img, (M - 4, 390), avg, _s("ExtraBold", 150))
    d = ImageDraw.Draw(img)
    d.text((M, 440), f"{n} closed signal{'s' if n != 1 else ''}, wins and losses  ·  price move after fees", font=_f("Medium", 22),
           fill=SILVER, anchor="ls")
    wr = f"{float(r['win_rate']):.0%}" if r.get("win_rate") is not None else "—"
    _stat_grid(d, (M, 492, W - M, 642), [("Closed", str(n), WHITE), ("Wins", str(r.get("wins") or 0), GREEN),
                                          ("Losses", str(max(0, n - int(r.get("wins") or 0))), RED), ("Win rate", wr, WHITE)], cols=4)
    # win-rate ring + best / worst
    cx, cy, rr = M + 150, 890, 130
    d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=LINE, width=16)
    if r.get("win_rate") is not None:
        d.arc((cx - rr, cy - rr, cx + rr, cy + rr), -90, -90 + 360 * float(r["win_rate"]), fill=GREEN, width=16)
    d.text((cx, cy + 14), wr, font=_s("ExtraBold", 48), fill=WHITE, anchor="ms")
    d.text((cx, cy + 50), "won", font=_f("Medium", 19), fill=SILVER, anchor="ms")
    bx = M + 340
    for i, (lab, x) in enumerate((("Best", r.get("best")), ("Worst", r.get("worst")))):
        y = 740 + i * 160
        _panel(d, (bx, y, W - M, y + 136))
        _label(d, (bx + 26, y + 40), lab, 13, GOLD if i == 0 else SILVER)
        if x:
            name = f"{coin(x['symbol'])} {_side(x['side'])} · {str(x['timeframe']).upper()}"
            d.text((bx + 26, y + 88), name, font=_fit(d, name, "Bold", 26, 300, sora=True), fill=WHITE, anchor="ls")
            _figure(img, (W - M - 26, y + 88), float(x["return_pct"]), _s("ExtraBold", 36), anchor="rs")
            d = ImageDraw.Draw(img)
        else:
            d.text((bx + 26, y + 88), "—", font=_s("Bold", 26), fill=SILVER, anchor="ls")
    note = r.get("sample_note") or "Equal size per signal · price move after a 0.15% round trip and funding · no leverage"
    for i, ln in enumerate(_wrap(d, note, _f("Medium", 19), W - 2 * M)[:2]):
        d.text((M, FOOT_Y - 92 + i * 30), ln, font=_f("Medium", 19), fill=GOLD if r.get("sample_note") else SILVER, anchor="ls")
    _footer(d, "Past results don't guarantee future results", img=img)
    return _png(img)


def _dial(img: Image.Image, cx: int, cy: int, r: int, value: float) -> None:
    """Mood dial: half ring red (bearish) -> silver -> green (bullish), gold needle at value in [-1, 1]."""
    d = ImageDraw.Draw(img)
    steps = 60
    for i in range(steps):
        a0 = 180 + i * 180 / steps
        a1 = a0 + 180 / steps + 0.6
        t = i / (steps - 1)
        if t < 0.5:
            k = t / 0.5
            c = tuple(int(RED[j] + (SILVER[j] * 0.55 - RED[j]) * k) for j in range(3))
        else:
            k = (t - 0.5) / 0.5
            c = tuple(int(SILVER[j] * 0.55 + (GREEN[j] - SILVER[j] * 0.55) * k) for j in range(3))
        d.arc((cx - r, cy - r, cx + r, cy + r), a0, a1, fill=c, width=18)
    for i in range(11):
        a = math.radians(180 + i * 18)
        d.line([(cx + (r - 34) * math.cos(a), cy + (r - 34) * math.sin(a)), (cx + (r - 26) * math.cos(a), cy + (r - 26) * math.sin(a))],
               fill=MUTED, width=2)
    a = math.radians(270 + 90 * max(-1.0, min(1.0, value)))
    tip = (cx + (r - 40) * math.cos(a), cy + (r - 40) * math.sin(a))
    _glow(img, lambda m: m.line([(cx, cy), tip], fill=220, width=8), GOLD, 6, 0.5)
    d = ImageDraw.Draw(img)
    d.line([(cx, cy), tip], fill=GOLD_LIGHT, width=5)
    d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=GOLD, outline=GOLD_LIGHT, width=2)
    d.text((cx - r, cy + 40), "Bearish", font=_f("SemiBold", 17), fill=RED, anchor="ms")
    d.text((cx + r, cy + 40), "Bullish", font=_f("SemiBold", 17), fill=GREEN, anchor="ms")


def briefing_card(b: dict[str, Any]) -> bytes:
    """The AI market briefing: mood dial, the text and the bullet facts."""
    at = int(b.get("at") or 0)
    when = datetime.fromtimestamp(at / 1000, timezone.utc).strftime("%d %b  ·  %H:%M UTC") if at else ""
    img, d = _base(f"Market briefing  ·  {when}", "AI BRIEFING")
    mood = str(b.get("mood") or "")
    word, col, val = {"BULL": ("Leaning bullish", GREEN, 0.55), "BEAR": ("Leaning bearish", RED, -0.55)}.get(mood, ("Mixed", GOLD, 0.0))
    br = ((b.get("facts") or {}).get("breadth") or {}) if isinstance(b.get("facts"), dict) else {}
    try:                                    # needle = share of coins above their 4H EMA50 (-1 none .. +1 all)
        of = float(br.get("of") or 0)
        if of > 0:
            val = max(-1.0, min(1.0, 2 * float(br.get("above_ema50_4h") or 0) / of - 1))
    except (TypeError, ValueError, AttributeError):
        pass
    _label(d, (M, 238), "Market mood", 16, GOLD)
    d.text((M, 318), word, font=_s("ExtraBold", 66), fill=col, anchor="ls")
    if b.get("source") == "ai":
        _chip(d, M, 350, "AI SUMMARY")
    _dial(img, W - M - 190, 400, 176, val)
    d = ImageDraw.Draw(img)
    body = _f("Regular", 34)
    lines = _wrap(d, str(b.get("text") or ""), body, W - 2 * M)[:8]
    y = 560
    for ln in lines:
        d.text((M, y), ln, font=body, fill=WHITE, anchor="ls")
        y += 52
    bullets = [_wrap(d, str(t), _f("SemiBold", 23), W - 2 * M - 92)[:2] for t in (b.get("bullets") or [])[:5]]
    if bullets:
        need = sum(32 * len(x) + 26 for x in bullets) + 70
        top = max(y + 24, FOOT_Y - 48 - need)   # anchored above the footer
        _panel(d, (M, top, W - M, top + need))
        _label(d, (M + 32, top + 46), "Key facts", 13, GOLD)
        yy = top + 92
        for ln in bullets:
            d.ellipse((M + 34, yy - 15, M + 44, yy - 5), fill=GOLD)
            for j, part in enumerate(ln):
                d.text((M + 62, yy + j * 32), part, font=_f("SemiBold", 23), fill=WHITE if j == 0 else SILVER, anchor="ls")
            yy += 32 * len(ln) + 26
    _footer(d, "Context, not advice", img=img)
    return _png(img)


def news_card(m: dict[str, Any]) -> bytes:
    """High-impact US release heads-up: countdown, the release, what it usually means, the signal pause."""
    img, d = _base("Economic calendar  ·  United States", "HIGH-IMPACT NEWS")
    at = int(_num(m.get("at")) or 0)
    mins = int(_num(m.get("mins")) or 0)
    event = str(m.get("event") or m.get("title") or "High-impact release")
    _label(d, (M, 238), "Releasing in", 16, GOLD)
    d.text((M, 390), f"{mins} min" if mins else "Now", font=_s("ExtraBold", 150), fill=WHITE, anchor="ls")
    if at:
        d.text((M, 444), datetime.fromtimestamp(at / 1000, timezone.utc).strftime("%H:%M UTC  ·  %a %d %b"), font=_f("Medium", 24),
               fill=SILVER, anchor="ls")
    # impact meter
    _label(d, (W - M, 238), "Impact", 14, SILVER, anchor="rs")
    for i in range(3):
        x = W - M - (2 - i) * 34 - 24
        d.rounded_rectangle((x, 330 - (i + 1) * 26, x + 24, 330), radius=5, fill=RED)
    d.text((W - M, 366), "High", font=_s("Bold", 26), fill=RED, anchor="rs")
    _panel(d, (M, 496, W - M, 720))
    _label(d, (M + 32, 546), "The release", 13, GOLD)
    for j, ln in enumerate(_wrap(d, event, _s("Bold", 44), W - 2 * M - 64)[:2]):
        d.text((M + 32, 610 + j * 54), ln, font=_s("Bold", 44), fill=WHITE, anchor="ls")
    why = str(m.get("why") or "").strip() or "Big US data releases often move Bitcoin and the whole market both ways within minutes."
    _label(d, (M, 784), "Why it matters", 14, GOLD)
    y = 830
    for ln in _wrap(d, why, _f("Medium", 26), W - 2 * M)[:4]:
        d.text((M, y), ln, font=_f("Medium", 26), fill=WHITE, anchor="ls")
        y += 38
    # signal pause strip: -45 min ... release ... +30 min
    y = max(y + 30, FOOT_Y - 190)
    _label(d, (M, y), "New signals pause around it", 14, SILVER)
    bx0, bx1, by = M, W - M, y + 50
    d.rounded_rectangle((bx0, by - 6, bx1, by + 6), radius=6, fill=PANEL_HI)
    px0 = bx0 + (bx1 - bx0) * 0.12
    px1 = bx0 + (bx1 - bx0) * 0.88
    rel = px0 + (px1 - px0) * 45 / 75
    d.rounded_rectangle((px0, by - 6, px1, by + 6), radius=6, fill=(90, 44, 52))
    d.ellipse((rel - 12, by - 12, rel + 12, by + 12), fill=RED, outline=WHITE, width=2)
    d.text((px0, by + 40), "−45 min", font=_f("SemiBold", 18), fill=SILVER, anchor="ms")
    d.text((rel, by + 40), "release", font=_f("SemiBold", 18), fill=WHITE, anchor="ms")
    d.text((px1, by + 40), "+30 min", font=_f("SemiBold", 18), fill=SILVER, anchor="ms")
    _footer(d, "Calendar fact, not advice", img=img)
    return _png(img)
