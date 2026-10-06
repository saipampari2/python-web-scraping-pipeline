"""Data-quality report built from the final records (bonus feature).

Per source: field completeness, price/rating statistics, category spread, URL uniqueness.
Overall: rejection and duplicate rates.
"""

from collections import Counter, defaultdict

from .schema import FIELDS


def _filled(value):
    return value is not None and value != "" and value != []


def build_quality_report(records, rejected, duplicates):
    by_source = defaultdict(list)
    for rec in records:
        by_source[rec["source"]].append(rec)

    sources = {}
    for source, rows in by_source.items():
        n = len(rows)
        completeness = {}
        for field in FIELDS:
            filled = sum(1 for r in rows if _filled(r.get(field)))
            completeness[field] = {"filled": filled, "missing": n - filled,
                                   "completeness_pct": round(100 * filled / n, 1)}
        entry = {
            "records": n,
            "distinct_source_urls": len({r["source_url"] for r in rows}),
            "field_completeness": completeness,
        }
        prices = [r["price"] for r in rows if r.get("price") is not None]
        if prices:
            entry["price"] = {"min": min(prices), "max": max(prices),
                              "mean": round(sum(prices) / len(prices), 2)}
        ratings = Counter(r["rating"] for r in rows if r.get("rating") is not None)
        if ratings:
            entry["rating_distribution"] = {str(k): ratings[k] for k in sorted(ratings)}
        categories = Counter(r["category"] for r in rows if r.get("category"))
        if categories:
            entry["distinct_categories"] = len(categories)
            entry["largest_categories"] = dict(categories.most_common(5))
        authors = {r["author"] for r in rows if r.get("author")}
        if authors:
            entry["distinct_authors"] = len(authors)
            entry["avg_tags_per_record"] = round(sum(len(r.get("tags") or []) for r in rows) / n, 2)
        sources[source] = entry

    total_seen = len(records) + len(rejected) + len(duplicates)
    return {
        "overall": {
            "final_records": len(records),
            "rejected": len(rejected),
            "duplicates_removed": len(duplicates),
            "rejection_rate_pct": round(100 * len(rejected) / total_seen, 2) if total_seen else 0.0,
            "duplicate_rate_pct": round(100 * len(duplicates) / total_seen, 2) if total_seen else 0.0,
        },
        "per_source": sources,
    }
