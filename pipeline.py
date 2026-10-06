"""Orchestration: scrape -> clean -> validate -> deduplicate -> consolidate -> write."""

import csv
import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from processing.cleaning import clean_record
from processing.deduplication import deduplicate
from processing.quality import build_quality_report
from processing.schema import FIELDS, SOURCE_BOOKS, SOURCE_QUOTES, TAG_SEPARATOR
from processing.validation import validate_record
from scrapers.books_scraper import BooksScraper
from scrapers.http_client import HttpClient
from scrapers.quotes_scraper import QuotesScraper

log = logging.getLogger(__name__)


def _csv_row(rec, extra=()):
    row = {k: rec.get(k) for k in FIELDS}
    row["tags"] = TAG_SEPARATOR.join(rec.get("tags") or [])
    for k in extra:
        row[k] = rec.get(k)
    return row


def _write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_scrapers(cfg, client):
    scrapers = []
    if "books" in cfg["sources"]:
        scrapers.append(BooksScraper(client, cfg["books_url"], cfg["max_pages"], cfg["books_details"]))
    if "quotes" in cfg["sources"]:
        scrapers.append(QuotesScraper(client, cfg["quotes_url"], cfg["max_pages"], cfg["author_details"]))
    return scrapers


def run(cfg):
    started = time.monotonic()
    started_at = datetime.now(timezone.utc)
    scraped_at = started_at.isoformat(timespec="seconds")
    out_dir = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    client = HttpClient(timeout=cfg["timeout"], max_retries=cfg["retries"], backoff=cfg["backoff"],
                        delay=cfg["delay"], respect_robots=not cfg["ignore_robots"])

    per_source, cleaned_all, rejected = {}, [], []

    for scraper in build_scrapers(cfg, client):
        name = scraper.source
        stats = {"collected": 0, "cleaned": 0, "rejected_in_cleaning": 0, "rejected_in_validation": 0,
                 "failed_pages": [], "parse_warnings": 0, "status": "ok"}
        per_source[name] = stats
        try:
            raw = scraper.scrape()
        except Exception:  # a whole source failing must not stop the other one
            log.exception("%s: scraper crashed; continuing with remaining sources", name)
            stats["status"] = "crashed"
            raw = []
        stats["collected"] = len(raw)
        stats["failed_pages"] = list(scraper.failed_pages)
        stats["parse_warnings"] = scraper.parse_warnings
        if scraper.failed_pages:
            stats["status"] = stats["status"] if stats["status"] == "crashed" else "partial"

        for item in raw:
            try:
                rec = clean_record(item, scraped_at)
            except Exception as exc:
                log.exception("%s: cleaning failed for %r", name, item.get("source_url"))
                stats["rejected_in_cleaning"] += 1
                rejected.append({"source": name, "source_url": item.get("source_url"),
                                 "name_or_title": item.get("title"), "stage": "cleaning",
                                 "reasons": f"exception: {exc}"})
                continue
            stats["cleaned"] += 1
            problems = validate_record(rec)
            if problems:
                stats["rejected_in_validation"] += 1
                rejected.append({"source": rec["source"], "source_url": rec["source_url"],
                                 "name_or_title": rec["name_or_title"], "stage": "validation",
                                 "reasons": "; ".join(problems)})
                continue
            cleaned_all.append(rec)

    unique, duplicates = deduplicate(cleaned_all)
    dup_counts = Counter(d["source"] for d in duplicates)
    final_counts = Counter(r["source"] for r in unique)
    for name, stats in per_source.items():
        stats["valid"] = stats["cleaned"] - stats["rejected_in_validation"]
        stats["duplicates_removed"] = dup_counts.get(name, 0)
        stats["final"] = final_counts.get(name, 0)

    _write_csv(out_dir / "final_dataset.csv", [_csv_row(r) for r in unique], FIELDS)
    _write_csv(out_dir / "rejected_records.csv", rejected,
               ["source", "source_url", "name_or_title", "stage", "reasons"])
    dup_extra = ["duplicate_reason", "duplicate_of_url", "duplicate_of_title"]
    _write_csv(out_dir / "duplicates_report.csv", [_csv_row(d, dup_extra) for d in duplicates],
               FIELDS + dup_extra)

    with open(out_dir / "data_quality_report.json", "w", encoding="utf-8") as fh:
        json.dump(build_quality_report(unique, rejected, duplicates), fh, indent=2, ensure_ascii=False)

    reasons = Counter()
    for r in rejected:
        for reason in r["reasons"].split("; "):
            reasons[reason] += 1

    summary = {
        "run_started_at": scraped_at,
        "execution_time_seconds": round(time.monotonic() - started, 2),
        "http": client.stats,
        "per_source": per_source,
        "totals": {
            "collected": sum(s["collected"] for s in per_source.values()),
            "after_cleaning": sum(s["cleaned"] for s in per_source.values()),
            "rejected_total": len(rejected),
            "rejected_reasons": dict(reasons),
            "duplicates_detected": len(duplicates),
            "duplicates_removed": len(duplicates),
            "final_records": len(unique),
        },
        "settings": {k: cfg[k] for k in ("sources", "max_pages", "delay", "retries", "books_details",
                                          "author_details")},
    }
    with open(out_dir / "summary_report.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    log.info("Done: %d collected, %d rejected, %d duplicates removed, %d final records in %.1fs",
             summary["totals"]["collected"], len(rejected), len(duplicates), len(unique),
             summary["execution_time_seconds"])
    return summary
