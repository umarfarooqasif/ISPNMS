import re

from sqlalchemy import text
from sqlalchemy.orm import Session


def normalize_mobile(raw: str | None) -> str | None:
    """Pakistani mobile numbers to E.164 (+923XXXXXXXXX). Returns None if not recognisable.

    Accepts 03XXXXXXXXX, 3XXXXXXXXX, 923XXXXXXXXX, +923XXXXXXXXX, 00923XXXXXXXXX with any
    spaces/dashes. The raw value is always kept separately; this only powers matching/search.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("03"):
        digits = "92" + digits[1:]
    elif len(digits) == 10 and digits.startswith("3"):
        digits = "92" + digits
    if len(digits) == 12 and digits.startswith("923"):
        return "+" + digits
    return None


def mask_cnic(cnic: str | None) -> str | None:
    if not cnic:
        return None
    digits = re.sub(r"\D", "", cnic)
    return "*" * max(len(digits) - 4, 0) + digits[-4:] if digits else "****"


def next_code(db: Session, seq: str, prefix: str) -> str:
    n = db.execute(text(f"SELECT nextval('{seq}')")).scalar_one()
    return f"{prefix}-{n:06d}"


def normalize_alias(value: str) -> str:
    """'Star 3', 'star-3' and 'STAR3' all map to 'star3'."""
    return re.sub(r"[\s\-_]+", "", value.strip().lower())
