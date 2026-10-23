"""Write firestore.rules from firestore.rules.template using the ADMIN_EMAILS environment variable."""
import os
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
emails = [e.strip().lower() for e in re.split(r"[,\s;]+", os.environ.get("ADMIN_EMAILS", "")) if e.strip()]
bad = [e for e in emails if not re.fullmatch(r"[^@\s'\"]+@[^@\s'\"]+\.[^@\s'\"]+", e)]
if not emails or bad:
    sys.exit("Set the ADMIN_EMAILS repository variable to your Google e-mail address(es), comma-separated. "
             f"Invalid: {bad}" if bad else "Set the ADMIN_EMAILS repository variable (GitHub: Settings > Secrets and variables > Actions > Variables).")
text = (root / "firestore.rules.template").read_text().replace("__ADMIN_EMAILS__", ", ".join(f"'{e}'" for e in emails))
(root / "firestore.rules").write_text(text)
print(f"firestore.rules written for {len(emails)} account(s)")
