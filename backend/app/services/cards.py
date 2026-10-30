"""Image cards for the Telegram channel: every post is a branded 1200x675 picture with the app logo.

v2.6 design: black + gold, radial gold glow, the real logo top-left, a glowing hero number (ROI on margin at the
signal card's suggested leverage; the price move beside it), aligned label/value grids on an 8 px grid. All text
is placed with baseline anchors and measured with textbbox / textlength so columns line up exactly.
Plain Pillow drawing, fonts (Inter, SIL Open Font Licence) and the logo ship in app/assets. Each function returns
PNG bytes (palette-quantised, ~100 KB: Telegram drafts keep up to 6 cards in one 1 MB Firestore document).
The numbers on a card are exactly the ones in the caption under it (the real record), wins and losses alike.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


from .. import brand
from ..pricefmt import fmt_price

ASSETS = Path(__file__).resolve().parent.parent / "assets"
W, H = 1200, 675
M = 56                                   # outer margin (8 px grid)
BG_TOP, BG_BOT = (16, 14, 10), (4, 4, 6)
GOLD = (240, 185, 11)
GOLD_SOFT = (199, 160, 64)
GREEN = (22, 199, 132)
RED = (234, 57, 67)
WHITE = (242, 242, 240)
MUTED = (150, 146, 136)
LINE = (58, 50, 34)
PANEL = (20, 18, 14)
PANEL_HI = (30, 26, 18)
INK = (8, 8, 10)

SITE_TEXT = brand.DISPLAY_URL
_fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _f(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(str(ASSETS / "fonts" / f"Inter-{weight}.otf"), size)
        except OSError:
            _fonts[key] = ImageFont.load_default(size)
    return _fonts[key]


def coin(sym: str) -> str:
    b = sym.split("/")[0]
    return "GOLD" if b == "PAXG" else b


def pair(sym: str) -> str:
    c = coin(sym)
    return c if c == "GOLD" else f"{c} / USDT"


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


# ---- drawing primitives ---------------------------------------------------------------------------------------

def _cap(font: ImageFont.FreeTypeFont) -> int:
    """Cap height: used to centre capital text optically inside pills and rows."""
    return -font.getbbox("H", anchor="ls")[1]


def _tw(d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    return int(round(d.textlength(text, font=font)))


def _fit(d: ImageDraw.ImageDraw, text: str, weight: str, size: int, max_w: int) -> ImageFont.FreeTypeFont:
    while size > 14 and d.textlength(text, font=_f(weight, size)) > max_w:
        size -= 2
    return _f(weight, size)


def _glow(img: Image.Image, draw_fn, color, radius: int, strength: float = 1.0) -> None:
    """Soft coloured glow: draw the shape on a mask, blur it, tint it onto the image."""
    mask = Image.new("L", img.size, 0)
    draw_fn(ImageDraw.Draw(mask))
    mask = mask.filter(ImageFilter.GaussianBlur(radius))
    if strength != 1.0:
        mask = mask.point(lambda v: min(255, int(v * strength)))
    img.paste(Image.new("RGB", img.size, color), (0, 0), mask)


def _radial(img: Image.Image, cx: int, cy: int, rx: int, ry: int, color, alpha: int) -> None:
    """Elliptical glow fading smoothly to nothing at its edge (no visible box)."""
    import numpy as np
    yy, xx = np.mgrid[0:img.height, 0:img.width]
    r = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    a = np.clip(1 - r, 0, 1) ** 2 * alpha
    mask = Image.fromarray(a.astype("uint8"), "L")
    img.paste(Image.new("RGB", img.size, color), (0, 0), mask)


def _panel(d: ImageDraw.ImageDraw, box, fill=PANEL, outline=LINE, r: int = 24, width: int = 2) -> None:
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def _pill(d: ImageDraw.ImageDraw, x: int, y: int, text: str, fg, bg, size: int = 20, h: int = 40,
          outline=None, align: str = "left", w: int | None = None) -> int:
    """Pill of height h (fixed width w, else fitted) with its top-left (top-right for align='right') at x, y.
    Returns the far x edge."""
    fn = _f("Bold", size)
    w = max(w or 0, _tw(d, text, fn) + 2 * 18)
    x0 = x if align == "left" else x - w
    d.rounded_rectangle((x0, y, x0 + w, y + h), radius=h // 2, fill=bg, outline=outline, width=2 if outline else 0)
    d.text((x0 + w / 2, y + h / 2 + _cap(fn) / 2), text, font=fn, fill=fg, anchor="ms")
    return x0 + w if align == "left" else x0


def _side_pill(d, x, y, side: str, size: int = 20, h: int = 40, w: int | None = None) -> int:
    col = GREEN if side == "LONG" else RED
    return _pill(d, x, y, side, INK, col, size, h, w=w)


def _chip(d, x, y, text, size: int = 20, h: int = 40, align: str = "left", w: int | None = None) -> int:
    return _pill(d, x, y, text, GOLD, PANEL_HI, size, h, outline=GOLD_SOFT, align=align, w=w)


def _base(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG_BOT)
    d = ImageDraw.Draw(img)
    for y in range(H):                                   # vertical gradient, warm black
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)))
    _radial(img, 150, 60, 520, 360, GOLD, 34)            # gold glow behind the logo
    _radial(img, W - 220, H // 2 + 20, 560, 420, GOLD, 22)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, W - 13, H - 13), radius=32, outline=GOLD_SOFT, width=2)
    d.rounded_rectangle((18, 18, W - 19, H - 19), radius=28, outline=(46, 38, 22), width=1)
    ls = 64
    try:
        logo = Image.open(ASSETS / "logo.png").convert("RGBA").resize((ls, ls), Image.LANCZOS)
        mask = Image.new("L", logo.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, ls - 1, ls - 1), radius=16, fill=255)
        logo.putalpha(Image.composite(logo.getchannel("A"), Image.new("L", logo.size, 0), mask))
        _glow(img, lambda m: m.rounded_rectangle((M, 40, M + ls, 40 + ls), radius=16, fill=150), GOLD, 14, 0.8)
        img.paste(logo, (M, 40), logo)
    except OSError:
        pass
    d = ImageDraw.Draw(img)
    tx = M + ls + 20
    d.text((tx, 66), "CRYPTO INTELLIGENCE AI", font=_f("ExtraBold", 26), fill=WHITE, anchor="ls")
    d.text((tx, 96), title, font=_fit(d, title, "SemiBold", 20, 620), fill=GOLD, anchor="ls")
    return img, d


def _footer(d: ImageDraw.ImageDraw, note: str = "Analysis only, not financial advice") -> None:
    y = 584
    d.line([(M, y), (W - M, y)], fill=LINE, width=2)
    d.text((M, y + 36), SITE_TEXT, font=_f("Bold", 22), fill=GOLD, anchor="ls")
    fn = _fit(d, note, "Medium", 18, W - 2 * M - 360)
    d.text((W - M, y + 36), note, font=fn, fill=MUTED, anchor="rs")
    small = _fit(d, brand.FOOTER, "Medium", 14, W - 2 * M)
    d.text((M, y + 62), brand.FOOTER, font=small, fill=(110, 106, 98), anchor="ls")


def _rows(d: ImageDraw.ImageDraw, box, rows: list[tuple[str, str, Any]], label_size: int = 18,
          value_size: int = 28) -> None:
    """Label / value list: labels left, values right, all on one baseline per row, hairlines between rows."""
    x0, y0, x1, y1 = box
    _panel(d, box)
    pad = 32
    rh = (y1 - y0) / len(rows)
    lf = _f("SemiBold", label_size)
    for i, (k, v, col) in enumerate(rows):
        top = y0 + rh * i
        vf = _fit(d, v, "Bold", value_size, int((x1 - x0) - 2 * pad - _tw(d, k.upper(), lf) - 24))
        base = top + rh / 2 + _cap(vf) / 2
        d.text((x0 + pad, base), k.upper(), font=lf, fill=MUTED, anchor="ls")
        d.text((x1 - pad, base), v, font=vf, fill=col, anchor="rs")
        if i:
            d.line([(x0 + pad, top), (x1 - pad, top)], fill=LINE, width=1)


def _hero(img: Image.Image, box, value: float, lev: int | None, price: float, sub: str | None = None,
          label: str | None = None) -> None:
    """The big glowing result: ROI on margin (or the price move, labelled, when there is no leverage)."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    col = GREEN if value > 0 else RED
    cx = (x0 + x1) // 2
    _radial(img, cx, (y0 + y1) // 2 - 10, (x1 - x0) // 2, (y1 - y0) // 2, col, 46)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=28, outline=tuple(int(c * 0.55) for c in col), width=2)
    lab = label or ("ROI ON MARGIN" if lev else "PRICE MOVE")
    labf = _f("Bold", 20)
    big = pct(value)
    fb = _fit(d, big, "ExtraBold", 124, (x1 - x0) - 64)
    subf = _fit(d, sub, "Medium", 17, (x1 - x0) - 48) if sub else None
    # vertical stack, centred in the box: label · number · (chip + price) · note
    parts = [_cap(labf), 32, _cap(fb)] + ([32, 40] if lev else []) + ([28, _cap(subf)] if sub else [])
    y = y0 + ((y1 - y0) - sum(parts)) / 2
    d.text((cx, y + _cap(labf)), lab, font=labf, fill=GOLD, anchor="ms")
    base = y + _cap(labf) + 32 + _cap(fb)
    _glow(img, lambda m: m.text((cx, base), big, font=fb, fill=255, anchor="ms"), col, 18, 1.6)
    d = ImageDraw.Draw(img)
    d.text((cx, base), big, font=fb, fill=col, anchor="ms")
    y = base
    if lev:
        y += 32
        lf = _f("Bold", 20)
        chip = f"{lev}x MARGIN"
        mv = f"price {pct(price)}"
        mf = _f("Medium", 22)
        tot = _tw(d, chip, lf) + 36 + 16 + _tw(d, mv, mf)
        e = _chip(d, int(cx - tot / 2), int(y), chip)
        d.text((e + 16, y + 20 + _cap(mf) / 2), mv, font=mf, fill=WHITE, anchor="ls")
        y += 40
    if sub:
        d.text((cx, y + 28 + _cap(subf)), sub, font=subf, fill=MUTED, anchor="ms")


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(buf, "PNG", optimize=True)
    return buf.getvalue()


TARGET = {"TP1": "TARGET 1 HIT", "TP2": "TARGET 2 HIT", "TP3": "ALL TARGETS HIT", "STOPPED": "STOPPED OUT",
          "EXPIRED": "CLOSED AT TIME LIMIT"}
HIT = {"TP1": "TP1", "TP2": "TP1 · TP2", "TP3": "TP1 · TP2 · TP3"}


# ---- cards ----------------------------------------------------------------------------------------------------

def result_card(w: dict[str, Any]) -> bytes:
    """One closed signal, win or loss, in the same clean layout."""
    val, lev, price = result(w)
    win = float(w["return_pct"]) > 0
    img, d = _base("Signal closed in profit" if win else "Signal closed at a loss")
    side = _side(w["side"])
    status = str(w.get("status") or "")
    lw = 528                                                # left column 56..584, right column 616..1144
    y = 144
    x = _pill(d, M, y, TARGET.get(status, "CLOSED IN PROFIT" if win else "CLOSED"), INK, GREEN if win else RED)
    x = _side_pill(d, x + 12, y, side)
    _chip(d, x + 12, y, str(w["timeframe"]).upper())
    name = pair(w["symbol"])
    nf = _fit(d, name, "ExtraBold", 72, lw)
    d.text((M, 264), name, font=nf, fill=WHITE, anchor="ls")
    exit_lbl = "Closed at"
    rows = [("Entry", px(w.get("entry")), WHITE), (exit_lbl, px(w.get("exit_price")), WHITE),
            ("Targets hit", HIT.get(status, "none"), GREEN if status in HIT else MUTED),
            ("Held", str(w.get("held") or "—"), WHITE)]
    _rows(d, (M, 304, M + lw, 552), rows)
    _hero(img, (616, 144, W - M, 552), val, lev, price, "half at TP1, a quarter at TP2 and TP3 · before fees")
    d = ImageDraw.Draw(img)
    _footer(d)
    return _png(img)


def win_card(w: dict[str, Any]) -> bytes:
    """One closed winning signal (the per-win Telegram post)."""
    return result_card(w)


def wins_card(wins: list[dict[str, Any]], period: str = "today", closed: int | None = None,
              losses: int | None = None) -> bytes:
    """Best winning signals of the day (or week), up to 5 rows, with the window's loss count beside them."""
    img, d = _base("Wins of the " + ("day" if period == "today" else "week"))
    rows = wins[:5]
    n = len(wins)
    d.text((M, 196), f"{n} winning signal{'s' if n != 1 else ''}", font=_f("ExtraBold", 48), fill=WHITE, anchor="ls")
    if closed is not None and losses is not None:
        sub = f"{closed} closed {'today' if period == 'today' else 'this week'} · {losses} loss{'es' if losses != 1 else ''} · every result is public"
    else:
        sub = "every result, wins and losses, is public in the app"
    d.text((M, 232), sub, font=_f("Medium", 20), fill=MUTED, anchor="ls")
    best = max((result(x)[0] for x in wins), default=0.0)
    lev_any = any(result(x)[1] for x in wins)
    d.text((W - M, 160), "BEST ROI ON MARGIN" if lev_any else "BEST PRICE MOVE", font=_f("Bold", 18), fill=GOLD, anchor="rs")
    bf = _f("ExtraBold", 56)
    bt = pct(best)
    _glow(img, lambda m: m.text((W - M, 224), bt, font=bf, fill=255, anchor="rs"), GREEN, 14, 1.4)
    d = ImageDraw.Draw(img)
    d.text((W - M, 224), bt, font=bf, fill=GREEN, anchor="rs")
    # table: COIN | SIDE | TF | RESULT | PRICE | ROI (right edge)
    x0, x1 = M, W - M
    cols = {"coin": x0 + 28, "side": x0 + 228, "tf": x0 + 360, "res": x0 + 470, "price": x1 - 300, "roi": x1 - 28}
    hy = 280
    hf = _f("SemiBold", 15)
    for k, lab, anc in (("coin", "COIN", "ls"), ("side", "SIDE", "ls"), ("tf", "TF", "ls"), ("res", "RESULT", "ls"),
                        ("price", "PRICE MOVE", "rs"), ("roi", "ROI · LEVERAGE", "rs")):
        d.text((cols[k], hy), lab, font=hf, fill=MUTED, anchor=anc)
    y, rh = 292, 52
    for i, x in enumerate(rows):
        top = y + i * (rh + 0)
        if i % 2 == 0:
            d.rounded_rectangle((x0, top + 3, x1, top + rh - 3), radius=14, fill=PANEL, outline=LINE, width=1)
        mid = top + rh / 2
        side = _side(x["side"])
        cf = _fit(d, coin(x["symbol"]), "Bold", 26, 190)
        d.text((cols["coin"], mid + _cap(cf) / 2), coin(x["symbol"]), font=cf, fill=WHITE, anchor="ls")
        _side_pill(d, cols["side"], int(mid - 15), side, 15, 30, w=96)
        _chip(d, cols["tf"], int(mid - 15), str(x["timeframe"]).upper(), 15, 30, w=72)
        rf = _f("Medium", 19)
        d.text((cols["res"], mid + _cap(rf) / 2), TARGET.get(x.get("status", ""), "IN PROFIT").title(), font=rf,
               fill=MUTED, anchor="ls")
        val, lev, price = result(x)
        d.text((cols["price"], mid + _cap(rf) / 2), pct(price), font=rf, fill=WHITE, anchor="rs")
        vf = _f("ExtraBold", 26)
        vt = pct(val)
        d.text((cols["roi"] - 76, mid + _cap(vf) / 2), vt, font=vf, fill=GREEN if val > 0 else RED, anchor="rs")
        if lev:
            _chip(d, cols["roi"], int(mid - 15), f"{lev}x", 15, 30, align="right", w=60)
        else:
            d.text((cols["roi"] - 30, mid + _cap(hf) / 2), "price", font=hf, fill=MUTED, anchor="ms")
    if n > len(rows):
        d.text((x1 - 28, 292 + 5 * rh + 22), f"+ {n - len(rows)} more in the app", font=_f("Medium", 16), fill=MUTED, anchor="rs")
    _footer(d)
    return _png(img)


def weekly_card(r: dict[str, Any]) -> bytes:
    """Last week's totals (wins AND losses) and best trades."""
    f = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b")  # noqa: E731
    img, d = _base(f"Weekly results · {f(r['week_start'])} – {f(r['week_end'] - 1)}")
    tot_price = float(r["total_return_pct"])
    roi = r.get("total_roi_pct")
    _hero(img, (M, 136, 584, 400), float(roi) if roi is not None else tot_price, None, tot_price,
          (f"price {pct(tot_price)} · " if roi is not None else "") + f"{r.get('closed', 0)} closed signals, all counted",
          "TOTAL ROI ON MARGIN" if roi is not None else "TOTAL PRICE MOVE")
    d = ImageDraw.Draw(img)
    kp = [("Wins", str(r["wins"]), GREEN), ("Losses", str(r["losses"]), RED),
          ("Win rate", f"{float(r['win_rate'] or 0):.0%}", WHITE)]
    gx, gw, gap = 616, (W - M - 616 - 2 * 16) // 3, 16
    for i, (k, v, c) in enumerate(kp):
        bx = gx + i * (gw + gap)
        _panel(d, (bx, 136, bx + gw, 400))
        d.text((bx + gw / 2, 192), k.upper(), font=_f("SemiBold", 17), fill=MUTED, anchor="ms")
        vf = _fit(d, v, "ExtraBold", 72, gw - 32)
        d.text((bx + gw / 2, 300), v, font=vf, fill=c, anchor="ms")
    best = [t for t in (r.get("best") or []) if float(t["return_pct"]) > 0][:3]
    if best:
        d.text((M, 436), "TOP SIGNALS", font=_f("SemiBold", 16), fill=MUTED, anchor="ls")
        cw = (W - 2 * M - 2 * 16) // 3
        for i, t in enumerate(best):
            bx = M + i * (cw + 16)
            _panel(d, (bx, 452, bx + cw, 560), r=18)
            nf = _fit(d, coin(t["symbol"]), "Bold", 28, cw - 200)
            d.text((bx + 24, 496), coin(t["symbol"]), font=nf, fill=WHITE, anchor="ls")
            d.text((bx + 24, 532), f"{_side(t['side'])} · {str(t['timeframe']).upper()}", font=_f("Medium", 17),
                   fill=GREEN if _side(t["side"]) == "LONG" else RED, anchor="ls")
            val, lev, price = result(t)
            vt = pct(val)
            d.text((bx + cw - 24, 496), vt, font=_fit(d, vt, "ExtraBold", 30, 180), fill=GREEN, anchor="rs")
            d.text((bx + cw - 24, 532), f"{lev}x · price {pct(price)}" if lev else "price move", font=_f("Medium", 16),
                   fill=MUTED, anchor="rs")
    _footer(d, "Past results don't guarantee future results")
    return _png(img)


def teaser_card(s: dict[str, Any], mins: int) -> bytes:
    """A free grade-A call that members received at least an hour earlier."""
    img, d = _base(f"Free signal · members got it {mins // 60} h {mins % 60:02d} min ago")
    side = _side(s["side"])
    y = 144
    x = _pill(d, M, y, "GRADE A", INK, GOLD)
    x = _side_pill(d, x + 12, y, side)
    x = _chip(d, x + 12, y, str(s["timeframe"]).upper())
    from ..engine.futures import signal_leverage
    lev = signal_leverage(s.get("entry"), s.get("stop"))
    if lev:
        _chip(d, x + 12, y, f"{lev}x SUGGESTED")
    name = pair(s["symbol"])
    d.text((M, 290), name, font=_fit(d, name, "ExtraBold", 84, W - 2 * M), fill=WHITE, anchor="ls")
    cells = [("Entry", px(s.get("entry")), WHITE), ("Stop-loss", px(s.get("stop")), RED),
             ("Target 1", px(s.get("tp1")), GREEN), ("Target 2", px(s.get("tp2")), GREEN),
             ("Target 3", px(s.get("tp3")), GREEN)]
    gap = 16
    cw = (W - 2 * M - 4 * gap) // 5
    vals = [v for _, v, _ in cells]
    size = 34                                              # one value size for all five cells, so they line up
    while size > 16 and any(d.textlength(v, font=_f("Bold", size)) > cw - 40 for v in vals):
        size -= 2
    for i, (k, v, c) in enumerate(cells):
        bx = M + i * (cw + gap)
        _panel(d, (bx, 352, bx + cw, 512), r=20)
        if i == 0:
            _glow(img, lambda m: m.rounded_rectangle((bx, 352, bx + cw, 512), radius=20, outline=200, width=3), GOLD, 8)
            d = ImageDraw.Draw(img)
        d.text((bx + 20, 400), k.upper(), font=_f("SemiBold", 16), fill=MUTED, anchor="ls")
        d.text((bx + 20, 468), v, font=_f("Bold", size), fill=c, anchor="ls")
    d.text((M, 552), "Members get every signal the moment it appears, with phone alerts.", font=_f("Medium", 20),
           fill=MUTED, anchor="ls")
    _footer(d, "Not financial advice · prices may have moved")
    return _png(img)
