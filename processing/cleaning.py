"""Reusable cleaning / normalisation helpers and the raw -> standard record transform.

Nothing in here knows about HTML or the network; it only works on plain values.
"""

import re
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit

from .schema import SOURCE_BOOKS, SOURCE_QUOTES

_WS = re.compile(r"\s+")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
MISSING_TOKENS = {"", "n/a", "na", "none", "null", "nan", "-", "--"}
_RATING_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_QUOTE_CHARS = "“”‘’\"'"
_PUNCT_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ",
})


def clean_whitespace(value):
    """Collapse runs of whitespace (incl. non-breaking spaces) and strip. Empty -> None."""
    if value is None:
        return None
    text = _WS.sub(" ", str(value).replace(" ", " ")).strip()
    return text or None


def normalize_missing(value):
    """Turn blank / 'N/A' / 'null' style placeholders into None."""
    text = clean_whitespace(value)
    if text is None or text.casefold() in MISSING_TOKENS:
        return None
    return text


def normalize_text(value):
    """Aggressive normalisation used for *comparison* only (duplicate keys).

    NFKC, case-folded, curly quotes/dashes flattened, punctuation removed,
    whitespace collapsed. Never used for the stored value.
    """
    text = clean_whitespace(value)
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", text).translate(_PUNCT_MAP).casefold()
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    return _WS.sub(" ", text).strip()


def strip_wrapping_quotes(value):
    text = clean_whitespace(value)
    return clean_whitespace(text.strip(_QUOTE_CHARS)) if text else None


def parse_price(raw):
    """'£51.77', 'Â£51.77', '1,234.50' -> float. Unparseable -> None."""
    text = clean_whitespace(raw)
    if text is None:
        return None
    match = _NUMBER.search(text)
    if not match:
        return None
    try:
        return round(float(match.group().replace(",", "")), 2)
    except ValueError:
        return None


def detect_currency(raw):
    text = raw or ""
    if "£" in text:
        return "GBP"
    if "$" in text:
        return "USD"
    if "€" in text:
        return "EUR"
    return None


def parse_rating(raw):
    """'Three' / 'three stars' / '3' / '3.0' -> number. Range is checked by validation."""
    text = clean_whitespace(raw)
    if text is None:
        return None
    lowered = text.casefold()
    for word, number in _RATING_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            return number
    match = re.search(r"\d+(?:\.\d+)?", lowered)
    if match:
        number = float(match.group())
        return int(number) if number.is_integer() else number
    return None


def normalize_url(url, base=None):
    """Absolute, tidy http(s) URL, or None if it can't be made one."""
    text = clean_whitespace(url)
    if text is None:
        return None
    if base:
        text = urljoin(base, text)
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/",
                       parts.query, ""))  # fragment dropped


def is_valid_url(url):
    return normalize_url(url) is not None


def clean_tags(tags):
    """List of tags -> cleaned, lower-cased, de-duplicated (order kept)."""
    seen, out = set(), []
    for tag in tags or []:
        text = normalize_missing(tag)
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text.casefold())
    return out


def _empty_record(source, scraped_at):
    return {"source": source, "source_url": None, "name_or_title": None, "category": None,
            "price": None, "currency": None, "rating": None, "author": None, "tags": [],
            "description": None, "availability": None, "scraped_at": scraped_at}


def clean_record(raw, scraped_at):
    """Convert one raw scraper dict into the standard schema (never invents data)."""
    source = clean_whitespace(raw.get("source"))
    rec = _empty_record(source, scraped_at)
    rec["source_url"] = normalize_url(raw.get("source_url"))
    rec["description"] = normalize_missing(raw.get("description"))
    rec["category"] = normalize_missing(raw.get("category"))
    rec["author"] = normalize_missing(raw.get("author"))
    rec["tags"] = clean_tags(raw.get("tags"))

    if source == SOURCE_BOOKS:
        rec["name_or_title"] = normalize_missing(raw.get("title"))
        rec["price"] = parse_price(raw.get("price_raw"))
        rec["currency"] = detect_currency(raw.get("price_raw")) if rec["price"] is not None else None
        rec["rating"] = parse_rating(raw.get("rating_raw"))
        rec["availability"] = normalize_missing(raw.get("availability_raw"))
    elif source == SOURCE_QUOTES:
        rec["name_or_title"] = strip_wrapping_quotes(raw.get("title"))
    else:  # unknown source: keep what we can; validation will reject it
        rec["name_or_title"] = normalize_missing(raw.get("title"))
    return rec
