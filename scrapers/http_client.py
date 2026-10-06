"""Polite HTTP client: timeouts, retries with exponential backoff, rate limiting, robots.txt."""

import logging
import time
from urllib import robotparser
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}
USER_AGENT = "interview-assignment-scraper/1.0 (educational; practice sites only)"


class FetchError(Exception):
    """Raised when a page could not be fetched after all retries."""


class HttpClient:
    def __init__(self, timeout=15.0, max_retries=3, backoff=1.0, delay=0.3,
                 respect_robots=True, trust_env=True):
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.backoff = backoff
        self.delay = delay
        self.respect_robots = respect_robots
        self.session = requests.Session()
        self.session.trust_env = trust_env
        self.session.headers["User-Agent"] = USER_AGENT
        self._last_request = 0.0
        self._robots = {}
        self.stats = {"requests": 0, "retries": 0, "failures": 0}

    # -- robots.txt ---------------------------------------------------------
    def _robots_for(self, url):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        parser = robotparser.RobotFileParser()
        try:
            self._throttle()
            resp = self.session.get(f"{origin}/robots.txt", timeout=self.timeout)
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            elif resp.status_code == 404:
                parser.parse([])
            else:
                log.error("Could not read robots.txt for %s (HTTP %d); disallowing crawl",
                          origin, resp.status_code)
                parser.disallow_all = True
        except requests.RequestException as exc:
            log.error("Could not read robots.txt for %s (%s); disallowing crawl", origin, exc)
            parser.disallow_all = True
        self._robots[origin] = parser
        return parser

    def allowed(self, url):
        if not self.respect_robots:
            return True
        return self._robots_for(url).can_fetch(USER_AGENT, url)

    # -- fetching -----------------------------------------------------------
    def _throttle(self):
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def get(self, url):
        """Return the page HTML, or raise FetchError."""
        if not self.allowed(url):
            self.stats["failures"] += 1
            raise FetchError(f"Blocked by robots.txt: {url}")

        last_problem = "unknown error"
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            self.stats["requests"] += 1
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
            except requests.RequestException as exc:  # invalid URL etc. - not retryable
                self.stats["failures"] += 1
                raise FetchError(f"{url}: {type(exc).__name__}: {exc}") from exc
            else:
                if resp.status_code == 200:
                    resp.encoding = "utf-8"  # books.toscrape.com omits the charset (£ -> Â£)
                    return resp.text
                last_problem = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRY_STATUSES:
                    self.stats["failures"] += 1
                    raise FetchError(f"{url}: {last_problem} (not retryable)")

            if attempt < self.max_retries:
                sleep_for = self.backoff * 2 ** (attempt - 1)
                self.stats["retries"] += 1
                log.warning("Attempt %d/%d failed for %s (%s); retrying in %.1fs",
                            attempt, self.max_retries, url, last_problem, sleep_for)
                time.sleep(sleep_for)

        self.stats["failures"] += 1
        raise FetchError(f"{url}: gave up after {self.max_retries} attempts ({last_problem})")
