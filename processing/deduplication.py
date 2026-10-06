"""Duplicate detection.

Two records are duplicates when they come from the same source AND either
  * their *content keys* match after normalisation, or
  * (sources with a unique page per record only) their normalised URLs match.

Content keys
  Books to Scrape : normalised title + price
  Quotes to Scrape: normalised quote text + normalised author

The first occurrence is kept; later ones are removed from the final dataset but
returned (with the reason and what they duplicate) so they can be audited in
output/duplicates_report.csv.
"""

from .cleaning import normalize_text
from .schema import SOURCE_BOOKS, SOURCE_QUOTES

# Sources where every record has its own URL (quotes share their listing-page URL).
UNIQUE_URL_SOURCES = {SOURCE_BOOKS}


def content_key(rec):
    source = rec.get("source")
    title = normalize_text(rec.get("name_or_title"))
    if source == SOURCE_BOOKS:
        return (source, title, rec.get("price"))
    if source == SOURCE_QUOTES:
        return (source, title, normalize_text(rec.get("author")))
    return (source, title)


def deduplicate(records):
    """Return (unique_records, duplicate_records)."""
    seen_content, seen_url = {}, {}
    unique, duplicates = [], []

    for rec in records:
        ckey = content_key(rec)
        ukey = (rec["source"], rec["source_url"]) if rec["source"] in UNIQUE_URL_SOURCES else None

        original, reason = None, None
        if ckey in seen_content:
            original, reason = seen_content[ckey], "same normalised content"
        elif ukey is not None and ukey in seen_url:
            original, reason = seen_url[ukey], "same source_url"

        if original is not None:
            dup = dict(rec)
            dup["duplicate_reason"] = reason
            dup["duplicate_of_url"] = original["source_url"]
            dup["duplicate_of_title"] = original["name_or_title"]
            duplicates.append(dup)
            continue

        seen_content[ckey] = rec
        if ukey is not None:
            seen_url[ukey] = rec
        unique.append(rec)

    return unique, duplicates
