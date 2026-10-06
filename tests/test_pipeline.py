"""End-to-end tests against the local mock site (no internet needed)."""

import csv
import json

import pytest

import main
import pipeline
from mock_site import MockSite
from scrapers.books_scraper import BooksScraper
from scrapers.http_client import FetchError, HttpClient
from scrapers.quotes_scraper import QuotesScraper


@pytest.fixture()
def site():
    with MockSite() as s:
        yield s


def fast_client(**kw):
    kw.setdefault("delay", 0)
    kw.setdefault("backoff", 0.01)
    return HttpClient(**kw)


def make_cfg(site, tmp_path, **over):
    cfg = {"sources": ["books", "quotes"], "output_dir": str(tmp_path / "out"), "max_pages": None,
           "delay": 0, "timeout": 5, "retries": 3, "backoff": 0.01, "books_details": False,
           "author_details": True, "books_url": site.books_url, "quotes_url": site.quotes_url,
           "ignore_robots": False}
    cfg.update(over)
    return cfg


def test_cli_loads_config_and_cli_values_override(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "sources": ["quotes"],
        "output_dir": "configured-output",
        "delay": 0.8,
        "retries": 5,
    }), encoding="utf-8")

    args = main.parse_args(["--config", str(config_file), "--delay", "0"])

    assert args.sources == ["quotes"]
    assert args.output_dir == "configured-output"
    assert args.delay == 0
    assert args.retries == 5


def test_cli_rejects_unknown_config_setting(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"unexpected": true}', encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main.parse_args(["--config", str(config_file)])

    assert exc_info.value.code == 2


def test_http_client_retries_then_succeeds(site):
    client = fast_client()
    url = site.books_url + "catalogue/category/books/travel_2/page-2.html"
    assert "Scott Pilgrim" in client.get(url)
    assert client.stats["retries"] == 1


def test_http_client_non_retryable_and_exhausted(site):
    client = fast_client(max_retries=2)
    with pytest.raises(FetchError):
        client.get(site.books_url + "missing.html")         # 404 -> fail at once
    assert site.hits["/books/missing.html"] == 1
    with pytest.raises(FetchError):
        client.get(site.books_url + "catalogue/category/books/poetry_23/index.html")  # 500 x2
    assert site.hits["/books/catalogue/category/books/poetry_23/index.html"] == 2


def test_http_client_does_not_crawl_when_robots_is_forbidden(site):
    site.routes["/robots.txt"] = (403, "Forbidden")
    client = fast_client()

    with pytest.raises(FetchError, match="Blocked by robots.txt"):
        client.get(site.books_url)

    assert site.hits.get("/books/", 0) == 0


def test_books_scraper_paginates_and_survives_failed_category(site):
    scraper = BooksScraper(fast_client(), site.books_url)
    raw = scraper.scrape()
    titles = [r["title"] for r in raw]
    assert "Scott Pilgrim" in titles                         # reached page 2 via "next"
    assert len(raw) == 6                                     # 3 travel + 3 mystery, poetry failed
    assert any(u.endswith("poetry_23/index.html") for u in scraper.failed_pages)
    assert raw[0]["category"] == "Travel"
    assert "Â£" in raw[0]["price_raw"] or "£" in raw[0]["price_raw"]
    assert raw[0]["source_url"].endswith("/books/catalogue/himalayas_1/index.html")


def test_books_missing_element_does_not_crash(site):
    raw = BooksScraper(fast_client(), site.books_url).scrape()
    no_price = next(r for r in raw if r["title"] == "No Price Book")
    assert no_price["price_raw"] is None


def test_quotes_scraper_follows_next_links_and_fetches_authors(site):
    scraper = QuotesScraper(fast_client(), site.quotes_url)
    raw = scraper.scrape()
    assert len(raw) == 5 and scraper.pages_fetched == 3 + 4
    einstein = raw[0]
    assert einstein["author"] == "Albert Einstein" and einstein["tags"] == ["change", "deep-thoughts"]
    assert "Bio of Albert-Einstein" in einstein["description"]


def test_max_pages_limits_crawl(site):
    scraper = QuotesScraper(fast_client(), site.quotes_url, max_pages=2, fetch_author_details=False)
    assert len(scraper.scrape()) == 4


def test_full_pipeline_outputs_and_counts(site, tmp_path):
    summary = pipeline.run(make_cfg(site, tmp_path))
    out = tmp_path / "out"

    with open(out / "final_dataset.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys())[:3] == ["source", "source_url", "name_or_title"]
    assert all(r["source"] and r["source_url"].startswith("http") for r in rows)

    books = [r for r in rows if r["source"] == "Books to Scrape"]
    quotes = [r for r in rows if r["source"] == "Quotes to Scrape"]
    assert len(books) == 4       # 6 raw - 1 invalid(no price) - 1 duplicate
    assert len(quotes) == 4      # 5 raw - 1 duplicate
    assert books[0]["price"] == "45.17" and books[0]["currency"] == "GBP" and books[0]["rating"] == "2"
    assert quotes[0]["name_or_title"] == "The world as we have created it"   # curly quotes stripped
    assert quotes[0]["tags"] == "change|deep-thoughts" and quotes[0]["price"] == ""

    t = summary["totals"]
    assert (t["collected"], t["rejected_total"], t["duplicates_removed"], t["final_records"]) == (11, 1, 2, 8)
    b = summary["per_source"]["Books to Scrape"]
    assert b["status"] == "partial" and len(b["failed_pages"]) == 1 and b["rejected_in_validation"] == 1

    saved = json.loads((out / "summary_report.json").read_text(encoding="utf-8"))
    assert saved["totals"]["final_records"] == 8 and saved["execution_time_seconds"] >= 0
    quality = json.loads((out / "data_quality_report.json").read_text(encoding="utf-8"))
    assert quality["overall"]["final_records"] == 8
    assert quality["per_source"]["Quotes to Scrape"]["field_completeness"]["author"]["completeness_pct"] == 100.0
    dups = list(csv.DictReader(open(out / "duplicates_report.csv", newline="", encoding="utf-8")))
    assert len(dups) == 2 and all(d["duplicate_reason"] for d in dups)
    rejected = list(csv.DictReader(open(out / "rejected_records.csv", newline="", encoding="utf-8")))
    assert "book missing price" in rejected[0]["reasons"]


def test_one_source_down_does_not_stop_the_other(site, tmp_path):
    cfg = make_cfg(site, tmp_path, books_url=f"http://127.0.0.1:{site.port}/nowhere/", retries=1)
    summary = pipeline.run(cfg)
    assert summary["per_source"]["Quotes to Scrape"]["final"] == 4
    assert summary["per_source"]["Books to Scrape"]["final"] == 0
