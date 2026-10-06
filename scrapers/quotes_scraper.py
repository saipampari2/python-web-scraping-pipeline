"""Scraper for https://quotes.toscrape.com/ .

Follows the "Next" link until it disappears. Optionally fetches each distinct
author's /author/... page once (cached) and stores the bio as `description`.
Quotes have no URL of their own, so `source_url` is the listing page they were found on.
"""

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from processing.schema import SOURCE_QUOTES
from .http_client import FetchError

log = logging.getLogger(__name__)


class QuotesScraper:
    source = SOURCE_QUOTES

    def __init__(self, client, base_url="https://quotes.toscrape.com/", max_pages=None,
                 fetch_author_details=True):
        self.client = client
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.max_pages = max_pages
        self.fetch_author_details = fetch_author_details
        self.pages_fetched = 0
        self.failed_pages = []
        self.parse_warnings = 0
        self._bio_cache = {}

    def scrape(self):
        records, url, visited = [], self.base_url, set()
        while url and url not in visited:
            if self.max_pages is not None and self.pages_fetched >= self.max_pages:
                log.info("Quotes: page limit reached, stopping")
                break
            visited.add(url)
            try:
                html = self.client.get(url)
            except FetchError as exc:
                # The next link lives on the failed page, so pagination cannot continue.
                log.error("Quotes: page failed, stopping pagination: %s", exc)
                self.failed_pages.append(url)
                break
            self.pages_fetched += 1
            soup = BeautifulSoup(html, "lxml")
            records.extend(self.parse_listing(soup, url))
            next_link = soup.select_one("li.next a")
            url = urljoin(url, next_link["href"]) if next_link and next_link.get("href") else None

        if self.fetch_author_details:
            self._add_author_bios(records)
        log.info("Quotes: scraped %d raw records from %d pages (%d failed pages)",
                 len(records), self.pages_fetched, len(self.failed_pages))
        return records

    def parse_listing(self, soup, page_url):
        out = []
        for card in soup.select("div.quote"):
            try:
                out.append(self._parse_card(card, page_url))
            except Exception:
                self.parse_warnings += 1
                log.exception("Quotes: could not parse a quote on %s", page_url)
        return out

    def _parse_card(self, card, page_url):
        text = card.select_one("span.text")
        author = card.select_one("small.author")
        about = card.select_one('a[href^="/author/"]')
        tags = [t.get_text() for t in card.select("div.tags a.tag")]

        missing = [n for n, v in (("text", text), ("author", author)) if v is None]
        if missing:
            self.parse_warnings += 1
            log.warning("Quotes: missing %s on %s", ", ".join(missing), page_url)

        return {
            "source": self.source,
            "source_url": page_url,
            "title": text.get_text() if text is not None else None,
            "author": author.get_text() if author is not None else None,
            "tags": tags,
            "category": None,
            "description": None,
            "_author_url": urljoin(page_url, about["href"]) if about is not None else None,
        }

    def _add_author_bios(self, records):
        urls = {r["_author_url"] for r in records if r.get("_author_url")}
        log.info("Quotes: fetching %d author pages", len(urls))
        for url in sorted(urls):
            try:
                soup = BeautifulSoup(self.client.get(url), "lxml")
            except FetchError as exc:
                log.error("Quotes: author page failed: %s", exc)
                self.failed_pages.append(url)
                continue
            self.pages_fetched += 1
            bio = soup.select_one("div.author-description")
            self._bio_cache[url] = bio.get_text() if bio is not None else None
        for rec in records:
            rec["description"] = self._bio_cache.get(rec.get("_author_url"))
            rec.pop("_author_url", None)
