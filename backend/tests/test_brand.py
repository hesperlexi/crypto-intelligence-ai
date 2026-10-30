"""Brand values and price formatting (audit A6)."""
from app import brand
from app.pricefmt import fmt_price


def test_brand_values_match_the_contract():
    assert brand.URL == "https://www.cryptointelai.com" and brand.SUPPORT_EMAIL == "support@cryptointelai.com"
    assert brand.VERSION == "2.1.0"
    assert brand.FOOTER == ("Crypto Intelligence AI v2.1.0 · www.cryptointelai.com · support@cryptointelai.com · "
                            "Analysis only, not financial advice.")
    assert brand.TELEGRAM_CHANNEL == "@crypappai"


def test_tiny_prices_never_use_scientific_notation():
    from app.services import cards, telegram
    for v in (0.0000123456, 3e-9, 0.00009999, -0.00005, 1e-12):
        for f in (fmt_price, cards.px, telegram._px):
            s = f(v)
            assert "e" not in s.lower(), (v, s)
            assert float(s.replace(",", "")) != 0
    assert fmt_price(0.0000123456) == "0.0000123456"
    assert fmt_price(12345.678) == "12,345.68" and fmt_price(1.5) == "1.5000" and fmt_price(None) == "—"


def test_posts_use_the_brand_site_not_the_old_url():
    from app.services import cards, telegram
    assert telegram.SITE == brand.URL and cards.SITE_TEXT == "www.cryptointelai.com"
    assert "web.app" not in telegram.SITE
