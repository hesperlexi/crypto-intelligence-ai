"""22 Nov 2026: `sink.lean()` (lean is a property) crashed every engine cycle for ~1 h 40 min. Never call it."""
import re
from pathlib import Path


def test_lean_is_never_called_like_a_method():
    app = Path(__file__).resolve().parents[1] / "app"
    bad = [f"{p.name}:{i}" for p in app.rglob("*.py") for i, ln in enumerate(p.read_text().splitlines(), 1)
           if re.search(r"\bsink\.lean\(\)", ln)]
    assert not bad, bad
