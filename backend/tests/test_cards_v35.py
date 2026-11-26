"""V3.5 Telegram cards: landscape 1280 x 1024, no text overlaps, every text inside the safe frame, honest labels."""
from PIL import Image
import io

from app.services import cards as C

NOW = 1795000000000
LONG_WIN = dict(symbol="BTC/USDT", timeframe="4h", side="LONG", status="TP2", return_pct=2.84, entry=91250.5, stop=89900,
                tp1=92600, tp2=93400, tp3=94800, exit_price=93400, held="9 h 20 min", leverage=10, roi_pct=28.4)
TINY_LOSS = dict(symbol="1000BONK/USDT", timeframe="15m", side="SHORT", status="STOPPED", return_pct=-1.37, entry=0.00002153,
                 stop=0.00002191, tp1=0.00002115, tp2=0.00002096, tp3=0.0000207, exit_price=0.00002191, held="47 min", leverage=25)
WINS = [dict(symbol=s, timeframe="15m", side="LONG", status="TP3", return_pct=r, leverage=25)
        for s, r in [("FARTCOIN/USDT", 155.55), ("ANTHROPIC/USDT", 3.1), ("ETH/USDT", 1.0), ("SOL/USDT", 0.4),
                     ("DOGE/USDT", 0.3), ("XRP/USDT", 0.2)]]


def cases():
    return [
        (C.result_card, (LONG_WIN,)), (C.result_card, (TINY_LOSS,)),
        (C.wins_card, (WINS, "today", 19, 12)), (C.wins_card, (WINS[:1], "week")),
        (C.weekly_card, (dict(week_start=NOW - 7 * 864e5, week_end=NOW, total_return_pct=-1234.56, total_roi_pct=-9999.9,
                              closed=23, wins=11, losses=12, win_rate=0.48, curve=[0, 1, -2],
                              best=[dict(symbol="1000SHIB/USDT", side="SHORT", timeframe="15m", return_pct=2.2)]),)),
        (C.week7_card, (dict(closed=3, wins=1, win_rate=0.33, avg_return_pct=-0.5,
                             best=dict(symbol="FARTCOIN/USDT", side="LONG", timeframe="15m", return_pct=5.5)), NOW)),
        (C.teaser_card, (dict(symbol="XAG/USDT", side=-1, timeframe="15m", grade="A", entry=31.245, stop=31.61, tp1=30.88,
                              tp2=30.6, tp3=30.2, leverage=22), 130)),
        (C.briefing_card, (dict(at=NOW, mood="BULL", source="ai", text="word " * 200, bullets=["fact " * 30] * 5),)),
        (C.news_card, (dict(event="A very long release name " * 6, at=NOW, mins=30, why="why " * 120),)),
    ]


def test_cards_are_landscape_and_never_overlap():
    for fn, args in cases():
        png = fn(*args)
        assert Image.open(io.BytesIO(png)).size == (1280, 1024)
        bad = C.overlaps(C.layout_boxes(fn, *args))
        assert bad == [], (fn.__name__, bad[:3])


def test_cards_state_net_paper_and_sample_size():
    texts = " ".join(b[4] for b in C.layout_boxes(C.result_card, LONG_WIN))
    assert "Net result after fees and funding" in texts and "Paper trading" in texts and "Leverage magnifies losses" in texts
    week7 = " ".join(b[4] for b in C.layout_boxes(C.week7_card, cases()[5][1][0], NOW))
    assert "too few to judge" in week7 and "profitable" not in week7.lower()
