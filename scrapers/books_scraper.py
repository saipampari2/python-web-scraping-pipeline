"""Scraper for https://books.toscrape.com/ .

Strategy: read the category sidebar, then follow each category's "next" links.
Crawling per category gives every book its category without one request per book.
If the sidebar can't be read, falls back to following "next" links through the
whole catalogue (category left empty rather than invented).

This module only extracts RAW strings; all cleaning lives in processing/cleaning.py.
"""

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from processing.schema import SOURCE_BOOKS
from .http_client import FetchError

log = logging.getLogger(__name__)


class BooksScraper:
    source = SOURCE_BOOKS

    def __init__(self, client, base_url="https://books.toscrape.com/", max_pages=None,
                 fetch_details=False):
        self.client = client
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.max_pages = max_pages          # page budget for the whole source (None = all)
        self.fetch_details = fetch_details  # also fetch each product page for its description
        self.pages_fetched = 0
        self.failed_pages = []
        self.parse_warnings = 0

    # -- public -------------------------------------------------------------
    def scrape(self):
        records = []
        categories = self._discover_categories()
        if categories:
            log.info("Books: found %d categories", len(categories))
            for name, url in categories:
                if self._budget_exhausted():
                    log.info("Books: page budget reached, stopping")
                    break
                records.extend(self._crawl(url, category=name))
        else:
            log.warning("Books: no categories found, crawling whole catalogue without categories")
            records.extend(self._crawl(self.base_url, category=None))

        if self.fetch_details:
            self._add_descriptions(records)
        log.info("Books: scraped %d raw records from %d pages (%d failed pages)",
                 len(records), self.pages_fetched, len(self.failed_pages))
        return records

    # -- crawling -----------------------------------------------------------
    def _budget_exhausted(self):
        return self.max_pages is not None and self.pages_fetched >= self.max_pages

    def _fetch(self, url):
        try:
            html = self.client.get(url)
        except FetchError as exc:
            log.error("Books: page failed: %s", exc)
            self.failed_pages.append(url)
            return None
        self.pages_fetched += 1
        return html

    def _discover_categories(self):
        html = self._fetch(self.base_url)
        if html is None:
            return []
        soup = BeautifulSoup(html, "lxml")
        categories = []
        for link in soup.select("div.side_categories ul li ul li a"):
            name, href = link.get_text(strip=True), link.get("href")
            if name and href:
                categories.append((name, urljoin(self.base_url, href)))
        return categories

    def _crawl(self, start_url, category):
        """Follow 'next' links from start_url; one failed page ends only this crawl."""
        records, url, visited = [], start_url, set()
        while url and url not in visited and not self._budget_exhausted():
            visited.add(url)
            html = self._fetch(url)
            if html is None:
                break
            soup = BeautifulSoup(html, "lxml")
            records.extend(self.parse_listing(soup, url, category))
            next_link = soup.select_one("li.next a")
            url = urljoin(url, next_link["href"]) if next_link and next_link.get("href") else None
        return records

    # -- parsing ------------------------------------------------------------
    def parse_listing(self, soup, page_url, category):
        out = []
        for card in soup.select("article.product_pod"):
            try:
                out.append(self._parse_card(card, page_url, category))
            except Exception:  # one odd card must not kill the page
                self.parse_warnings += 1
                log.exception("Books: could not parse a product card on %s", page_url)
        return out

    def _parse_card(self, card, page_url, category):
        link = card.select_one("h3 a")
        price = card.select_one("p.price_color")
        availability = card.select_one("p.availability")
        rating_tag = card.select_one("p.star-rating")

        title = None
        if link is not None:
            title = link.get("title") or link.get_text(strip=True)  # `title` attr is untruncated
        rating_raw = None
        if rating_tag is not None:
            rating_raw = next((c for c in rating_tag.get("class", []) if c != "star-rating"), None)

        missing = [n for n, v in (("title", title), ("price", price), ("rating", rating_raw)) if not v]
        if missing:
            self.parse_warnings += 1
            log.warning("Books: missing %s on %s", ", ".join(missing), page_url)

        return {
            "source": self.source,
            "source_url": urljoin(page_url, link["href"]) if link is not None and link.get("href") else None,
            "title": title,
            "category": category,
            "price_raw": price.get_text() if price is not None else None,
            "rating_raw": rating_raw,
            "availability_raw": availability.get_text() if availability is not None else None,
            "description": None,
        }

    def _add_descriptions(self, records):
        log.info("Books: fetching product pages for descriptions (%d)", len(records))
        for rec in records:
            if not rec.get("source_url"):
                continue
            html = self._fetch(rec["source_url"])
            if html is None:
                continue
            marker = BeautifulSoup(html, "lxml").select_one("#product_description")
            sibling = marker.find_next_sibling("p") if marker is not None else None
            rec["description"] = sibling.get_text() if sibling is not None else None
