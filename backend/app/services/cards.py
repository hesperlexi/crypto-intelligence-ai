"""Image cards for the Telegram channel (v2.3): every post is a branded 1200x675 picture with the app logo.

Plain Pillow drawing, fonts (Inter, SIL Open Font Licence) and the logo ship in app/assets. Each function returns
PNG bytes. The numbers on a card are exactly the ones in the caption under it (the real record).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
W, H = 1200, 675
BG_TOP, BG_BOT = (14, 17, 24), (6, 8, 12)
GOLD = (240, 185, 11)
GREEN = (22, 199, 132)
RED = (234, 57, 67)
WHITE = (240, 242, 245)
MUTED = (138, 146, 160)
PANEL = (24, 28, 37)
SITE_TEXT = "crypapp-6a9b9.web.app"
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


def px(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}" if v >= 100 else f"{v:,.4f}" if v >= 1 else f"{v:.6g}"


def _side(s: Any) -> str:
    if isinstance(s, str):
        return s.upper()
    return "LONG" if s and s > 0 else "SHORT"


def _base(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG_BOT)
    d = ImageDraw.Draw(img)
    for y in range(H):                                   # vertical gradient
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)))
    glow = Image.new("L", (W, H), 0)                     # soft gold glow, top right
    ImageDraw.Draw(glow).ellipse((W - 420, -300, W + 200, 220), fill=22)
    img.paste(Image.new("RGB", (W, H), GOLD), (0, 0), glow.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((14, 14, W - 15, H - 15), radius=28, outline=(*GOLD, 255), width=3)
    try:
        logo = Image.open(ASSETS / "logo.png").convert("RGBA").resize((76, 76), Image.LANCZOS)
        mask = Image.new("L", logo.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 75, 75), radius=18, fill=255)
        a = logo.getchannel("A")
        logo.putalpha(Image.composite(a, Image.new("L", logo.size, 0), mask))
        img.paste(logo, (52, 46), logo)
    except OSError:
        pass
    d.text((146, 52), "CRYPTO INTELLIGENCE AI", font=_f("ExtraBold", 30), fill=WHITE)
    d.text((146, 92), title, font=_f("SemiBold", 22), fill=GOLD)
    return img, d


def _footer(d: ImageDraw.ImageDraw, note: str = "Not financial advice") -> None:
    d.line([(52, H - 82), (W - 52, H - 82)], fill=(44, 50, 62), width=2)
    d.text((52, H - 62), SITE_TEXT, font=_f("Bold", 24), fill=GOLD)
    fn = _f("Medium", 20)
    d.text((W - 52 - d.textlength(note, font=fn), H - 59), note, font=fn, fill=MUTED)


def _pill(d: ImageDraw.ImageDraw, x: int, y: int, text: str, fg, bg, size: int = 22) -> int:
    fn = _f("Bold", size)
    w = d.textlength(text, font=fn)
    d.rounded_rectangle((x, y, x + w + 36, y + size + 22), radius=(size + 22) // 2, fill=bg)
    d.text((x + 18, y + 9), text, font=fn, fill=fg)
    return int(x + w + 36)


def _fit(d: ImageDraw.ImageDraw, text: str, weight: str, size: int, max_w: int) -> ImageFont.FreeTypeFont:
    while size > 14 and d.textlength(text, font=_f(weight, size)) > max_w:
        size -= 2
    return _f(weight, size)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


TARGET = {"TP1": "TARGET 1 HIT", "TP2": "TARGET 2 HIT", "TP3": "ALL TARGETS HIT"}


def win_card(w: dict[str, Any]) -> bytes:
    """One closed winning signal."""
    img, d = _base("Signal closed in profit")
    side = _side(w["side"])
    x = _pill(d, 52, 170, TARGET.get(w.get("status", ""), "CLOSED IN PROFIT"), (6, 8, 12), GREEN)
    _pill(d, x + 14, 170, f"{side} · {str(w['timeframe']).upper()}", WHITE, GREEN if side == "LONG" else RED)
    name = coin(w["symbol"]) + ("" if coin(w["symbol"]) == "GOLD" else " / USDT")
    d.text((52, 238), name, font=_fit(d, name, "ExtraBold", 84, 640), fill=WHITE)
    ret = f"+{float(w['return_pct']):.1f}%"
    fr = _fit(d, ret, "ExtraBold", 150, 480)
    d.text((W - 52 - d.textlength(ret, font=fr), 210), ret, font=fr, fill=GREEN)
    d.text((W - 52 - d.textlength("signal result", font=_f("Medium", 22)), 392), "signal result",
           font=_f("Medium", 22), fill=MUTED)
    d.rounded_rectangle((52, 440, W - 52, 560), radius=20, fill=PANEL)
    cols = [("Entry", px(w.get("entry"))), ("Closed at", px(w.get("exit_price"))),
            ("Held", w.get("held") or "—")]
    cw = (W - 104) / len(cols)
    for i, (k, v) in enumerate(cols):
        cx = 52 + cw * i + 32
        d.text((cx, 462), k.upper(), font=_f("SemiBold", 18), fill=MUTED)
        d.text((cx, 492), str(v), font=_fit(d, str(v), "Bold", 40, int(cw - 50)), fill=WHITE)
    _footer(d)
    return _png(img)


def wins_card(wins: list[dict[str, Any]], period: str = "today") -> bytes:
    """Best winning signals of the day (or week), up to 5 rows."""
    img, d = _base("Wins of the " + ("day" if period == "today" else "week"))
    rows = wins[:5]
    total = sum(float(x["return_pct"]) for x in wins)
    head = f"{len(wins)} winning signal{'s' if len(wins) != 1 else ''}"
    d.text((52, 160), head, font=_f("ExtraBold", 54), fill=WHITE)
    tot = f"+{total:.1f}%"
    d.text((W - 52 - d.textlength(tot, font=_f("ExtraBold", 54)), 160), tot, font=_f("ExtraBold", 54), fill=GREEN)
    y, rh = 244, 62
    for x in rows:
        d.rounded_rectangle((52, y, W - 52, y + rh - 10), radius=14, fill=PANEL)
        side = _side(x["side"])
        d.text((76, y + 12), coin(x["symbol"]), font=_f("Bold", 30), fill=WHITE)
        d.text((290, y + 17), f"{side} · {str(x['timeframe']).upper()}", font=_f("SemiBold", 22),
               fill=GREEN if side == "LONG" else RED)
        d.text((520, y + 17), TARGET.get(x.get("status", ""), "IN PROFIT").title(), font=_f("Medium", 22), fill=MUTED)
        r = f"+{float(x['return_pct']):.1f}%"
        d.text((W - 76 - d.textlength(r, font=_f("Bold", 30)), y + 12), r, font=_f("Bold", 30), fill=GREEN)
        y += rh
    if len(wins) > len(rows):
        d.text((76, y - 6), f"+ {len(wins) - len(rows)} more", font=_f("Medium", 20), fill=MUTED)
    _footer(d)
    return _png(img)


def weekly_card(r: dict[str, Any]) -> bytes:
    """Last week's totals (wins AND losses) and best trades."""
    f = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d %b")  # noqa: E731
    img, d = _base(f"Weekly results · {f(r['week_start'])} – {f(r['week_end'] - 1)}")
    tot = float(r["total_return_pct"])
    big = f"{tot:+.1f}%"
    d.text((52, 150), big, font=_f("ExtraBold", 120), fill=GREEN if tot >= 0 else RED)
    d.text((56, 300), "total of all closed signals", font=_f("Medium", 22), fill=MUTED)
    kp = [("Wins", str(r["wins"]), GREEN), ("Losses", str(r["losses"]), RED),
          ("Win rate", f"{float(r['win_rate']):.0%}", WHITE)]
    x0, bw = 640, 160
    for i, (k, v, c) in enumerate(kp):
        bx = x0 + i * (bw + 12)
        d.rounded_rectangle((bx, 165, bx + bw, 300), radius=18, fill=PANEL)
        d.text((bx + 20, 182), k.upper(), font=_f("SemiBold", 17), fill=MUTED)
        d.text((bx + 20, 216), v, font=_fit(d, v, "ExtraBold", 54, bw - 34), fill=c)
    best = [t for t in (r.get("best") or []) if float(t["return_pct"]) > 0][:3]
    y = 352
    if best:
        d.text((52, y), "TOP SIGNALS", font=_f("SemiBold", 18), fill=MUTED)
        y += 34
        cw = (W - 104 - 24) / 3
        for i, t in enumerate(best):
            bx = 52 + i * (cw + 12)
            d.rounded_rectangle((bx, y, bx + cw, y + 120), radius=16, fill=PANEL)
            d.text((bx + 22, y + 16), coin(t["symbol"]), font=_f("Bold", 30), fill=WHITE)
            d.text((bx + 22, y + 56), f"{_side(t['side'])} · {str(t['timeframe']).upper()}", font=_f("Medium", 20), fill=MUTED)
            rr = f"+{float(t['return_pct']):.1f}%"
            d.text((bx + cw - 22 - d.textlength(rr, font=_f("ExtraBold", 36)), y + 40), rr,
                   font=_f("ExtraBold", 36), fill=GREEN)
    _footer(d, "Past results don't guarantee future results")
    return _png(img)


def teaser_card(s: dict[str, Any], mins: int) -> bytes:
    """A free grade-A call that members received at least an hour earlier."""
    img, d = _base(f"Free signal · members got it {mins // 60} h {mins % 60:02d} min ago")
    side = _side(s["side"])
    x = _pill(d, 52, 170, "GRADE A", (6, 8, 12), GOLD)
    _pill(d, x + 14, 170, f"{side} · {str(s['timeframe']).upper()}", WHITE, GREEN if side == "LONG" else RED)
    name = coin(s["symbol"]) + ("" if coin(s["symbol"]) == "GOLD" else " / USDT")
    d.text((52, 238), name, font=_fit(d, name, "ExtraBold", 84, W - 104), fill=WHITE)
    cells = [("Entry", px(s.get("entry")), WHITE), ("Stop-loss", px(s.get("stop")), RED),
             ("Target 1", px(s.get("tp1")), GREEN), ("Target 2", px(s.get("tp2")), GREEN),
             ("Target 3", px(s.get("tp3")), GREEN)]
    cw = (W - 104 - 4 * 12) / 5
    for i, (k, v, c) in enumerate(cells):
        bx = 52 + i * (cw + 12)
        d.rounded_rectangle((bx, 380, bx + cw, 520), radius=18, fill=PANEL)
        d.text((bx + 18, 400), k.upper(), font=_f("SemiBold", 17), fill=MUTED)
        d.text((bx + 18, 440), v, font=_fit(d, v, "Bold", 36, int(cw - 30)), fill=c)
    _footer(d, "Not financial advice · prices may have moved")
    return _png(img)
