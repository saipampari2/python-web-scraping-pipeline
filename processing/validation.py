"""Record validation. Returns a list of human-readable problems (empty list = valid)."""

import math

from .cleaning import is_valid_url
from .schema import KNOWN_SOURCES, RATING_MAX, RATING_MIN, SOURCE_BOOKS, SOURCE_QUOTES


def validate_record(rec):
    problems = []

    if rec.get("source") not in KNOWN_SOURCES:
        problems.append("unrecognised source")
    if not rec.get("name_or_title"):
        problems.append("missing name_or_title")
    if not rec.get("source_url"):
        problems.append("missing source_url")
    elif not is_valid_url(rec["source_url"]):
        problems.append("invalid source_url")

    price = rec.get("price")
    if price is not None:
        if isinstance(price, bool) or not isinstance(price, (int, float)) or math.isnan(price):
            problems.append("price is not numeric")
        elif price < 0:
            problems.append("negative price")

    rating = rec.get("rating")
    if rating is not None:
        if isinstance(rating, bool) or not isinstance(rating, (int, float)):
            problems.append("rating is not numeric")
        elif not RATING_MIN <= rating <= RATING_MAX:
            problems.append(f"rating {rating} outside {RATING_MIN}-{RATING_MAX}")

    # Source-specific "required where applicable" fields
    if rec.get("source") == SOURCE_BOOKS:
        if price is None:
            problems.append("book missing price")
        if rating is None:
            problems.append("book missing rating")
    elif rec.get("source") == SOURCE_QUOTES:
        if not rec.get("author"):
            problems.append("quote missing author")

    return problems
