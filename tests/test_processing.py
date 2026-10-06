import pytest

from processing import cleaning as c
from processing.deduplication import deduplicate
from processing.schema import SOURCE_BOOKS, SOURCE_QUOTES
from processing.validation import validate_record


# ---- cleaning ---------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("£51.77", 51.77), ("Â£51.77", 51.77), (" 1,234.50 ", 1234.5),
    ("free", None), ("", None), (None, None),
])
def test_parse_price(raw, expected):
    assert c.parse_price(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Three", 3), ("five", 5), ("4", 4), ("2.0", 2), ("7", 7), ("", None), ("lots", None),
])
def test_parse_rating(raw, expected):
    assert c.parse_rating(raw) == expected


def test_whitespace_and_missing():
    assert c.clean_whitespace("  a \n  b\t") == "a b"
    assert c.clean_whitespace("   ") is None
    assert c.normalize_missing("N/A") is None
    assert c.normalize_missing(" null ") is None
    assert c.normalize_missing("ok") == "ok"


def test_normalize_text_makes_variants_equal():
    variants = ["Example Book Title", " Example Book Title ", "EXAMPLE BOOK TITLE", "Example  Book\nTitle!"]
    assert len({c.normalize_text(v) for v in variants}) == 1
    assert c.normalize_text("Don’t stop") == c.normalize_text("don't STOP")


def test_normalize_url():
    assert c.normalize_url("/a/b#frag", base="HTTP://Example.COM/x/") == "http://example.com/a/b"
    assert c.normalize_url("../z.html", base="https://e.com/a/b/c.html") == "https://e.com/a/z.html"
    assert c.normalize_url("javascript:alert(1)") is None
    assert c.normalize_url("not a url") is None
    assert c.normalize_url(None) is None


def test_clean_tags_dedupes_and_lowercases():
    assert c.clean_tags([" Love ", "love", "", "N/A", "Life"]) == ["love", "life"]


def test_clean_record_book_and_quote():
    book = c.clean_record({"source": SOURCE_BOOKS, "source_url": "http://x.com/b", "title": " A  Book ",
                           "price_raw": "Â£12.50", "rating_raw": "Four",
                           "availability_raw": "\n In stock \n", "category": "Travel"}, "T")
    assert (book["name_or_title"], book["price"], book["currency"], book["rating"]) == ("A Book", 12.5, "GBP", 4)
    assert book["availability"] == "In stock" and book["author"] is None and book["tags"] == []

    quote = c.clean_record({"source": SOURCE_QUOTES, "source_url": "http://x.com/", "title": "“Hi there”",
                            "author": " Bob ", "tags": ["A", "a"]}, "T")
    assert quote["name_or_title"] == "Hi there" and quote["price"] is None and quote["rating"] is None
    assert quote["tags"] == ["a"]


def test_missing_fields_are_none_not_invented():
    rec = c.clean_record({"source": SOURCE_BOOKS, "title": None}, "T")
    assert rec["name_or_title"] is None and rec["price"] is None and rec["source_url"] is None


# ---- validation -------------------------------------------------------------
def good_book(**kw):
    rec = {"source": SOURCE_BOOKS, "source_url": "http://x.com/b", "name_or_title": "T", "price": 1.0,
           "rating": 3, "author": None}
    rec.update(kw)
    return rec


def test_valid_book_passes():
    assert validate_record(good_book()) == []


@pytest.mark.parametrize("change,fragment", [
    ({"source": "Other"}, "source"), ({"name_or_title": None}, "name_or_title"),
    ({"source_url": None}, "source_url"), ({"price": None}, "price"), ({"price": -1}, "negative"),
    ({"price": "12"}, "numeric"), ({"rating": 9}, "outside"), ({"rating": None}, "rating"),
])
def test_invalid_book_reasons(change, fragment):
    assert any(fragment in p for p in validate_record(good_book(**change)))


def test_quote_requires_author_but_not_price():
    q = {"source": SOURCE_QUOTES, "source_url": "http://x.com/", "name_or_title": "t", "author": "A"}
    assert validate_record(q) == []
    q["author"] = None
    assert any("author" in p for p in validate_record(q))


# ---- data-quality report ----------------------------------------------------
def test_quality_report_completeness_and_rates():
    from processing.quality import build_quality_report
    books = [good_book(source_url="http://x/1", category="A", tags=[]),
             good_book(source_url="http://x/2", category=None, tags=[], price=3.0, rating=5)]
    report = build_quality_report(books, rejected=[{}], duplicates=[{}])
    src = report["per_source"][SOURCE_BOOKS]
    assert src["records"] == 2 and src["distinct_source_urls"] == 2
    assert src["field_completeness"]["category"] == {"filled": 1, "missing": 1, "completeness_pct": 50.0}
    assert src["field_completeness"]["author"]["filled"] == 0
    assert src["price"] == {"min": 1.0, "max": 3.0, "mean": 2.0}
    assert src["rating_distribution"] == {"3": 1, "5": 1}
    assert report["overall"]["rejection_rate_pct"] == 25.0 and report["overall"]["duplicate_rate_pct"] == 25.0


# ---- deduplication ----------------------------------------------------------
def rec(title, price=1.0, url="http://x.com/1", source=SOURCE_BOOKS, author=None):
    return {"source": source, "name_or_title": title, "price": price, "source_url": url, "author": author}


def test_dedup_catches_case_and_whitespace_variants():
    rows = [rec("Example Book Title", url="http://x/1"), rec(" Example Book Title ", url="http://x/2"),
            rec("EXAMPLE BOOK TITLE", url="http://x/3"), rec("Different", url="http://x/4")]
    unique, dups = deduplicate(rows)
    assert [r["name_or_title"] for r in unique] == ["Example Book Title", "Different"]
    assert len(dups) == 2 and dups[0]["duplicate_of_url"] == "http://x/1"


def test_same_title_different_price_is_kept():
    unique, dups = deduplicate([rec("Same", 1.0, "http://x/1"), rec("Same", 2.0, "http://x/2")])
    assert len(unique) == 2 and not dups


def test_same_url_is_duplicate_for_books_only():
    unique, dups = deduplicate([rec("A", url="http://x/1"), rec("B", url="http://x/1")])
    assert len(unique) == 1 and dups[0]["duplicate_reason"] == "same source_url"
    q = [rec("A", source=SOURCE_QUOTES, url="http://x/", author="Z"),
         rec("B", source=SOURCE_QUOTES, url="http://x/", author="Z")]
    unique, dups = deduplicate(q)
    assert len(unique) == 2 and not dups


def test_same_text_different_author_is_kept_and_sources_never_merge():
    rows = [rec("Hi", source=SOURCE_QUOTES, author="A", url="u"), rec("Hi", source=SOURCE_QUOTES, author="B", url="u"),
            rec("Hi", source=SOURCE_BOOKS)]
    unique, dups = deduplicate(rows)
    assert len(unique) == 3 and not dups
