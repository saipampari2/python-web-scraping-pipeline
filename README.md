# Multi-Source Web Scraping & Data Consolidation

A Python pipeline that scrapes **Books to Scrape** and **Quotes to Scrape**, converts both into one
common schema, cleans, validates and de-duplicates the records, and writes a consolidated CSV plus a
JSON summary.

```
Books ──┐
        ├─> Scrape (raw) ─> Clean ─> Validate ─> Deduplicate ─> Consolidate ─> CSV + summary
Quotes ─┘
```

## Python version
Tested on **Python 3.13**. Other Python versions have not been verified.

## Setup
```bash
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Dependencies
| Package | Why |
|---|---|
| `requests` | HTTP with sessions, timeouts |
| `beautifulsoup4` + `lxml` | HTML parsing (both sites are static HTML, so no browser automation is needed) |
| `pytest` (dev only) | tests |

**Why Requests + BeautifulSoup?** Both sites are server-rendered static HTML. A headless browser
(Playwright/Selenium) would be slower and add nothing; Scrapy would be more framework than this size needs.

## Running
```bash
python main.py                      # full scrape of both sites (~1 min with the default 0.3 s delay)
python main.py --max-pages 3        # cap listing-page crawls; optional detail pages can add requests
python main.py --sources quotes     # one source only
python main.py --books-details      # also fetch each book page for its description (+~1000 requests)
python main.py --help               # all options
```
Key options: `--output-dir`, `--log-dir`, `--max-pages`, `--delay`, `--timeout`, `--retries`, `--backoff`,
`--no-author-details`, `--config`, `--verbose`.

Outputs (in `output/`) and the log (`logs/scrape.log`) are overwritten on every run.

## Configuration
Defaults are stored in `config/config.json`. Edit it to configure sources, output/log directories, request
timeouts, retries, rate limiting, page limits, optional detail fetching, and source URLs. Pass another JSON file
with `--config path/to/settings.json`. Command-line options override the corresponding JSON values, for example:

```bash
python main.py --config config/config.json --sources quotes --delay 0
```

Unknown settings and invalid value types are reported as configuration errors rather than silently ignored.

## Docker
Docker is optional; the scraper can also be run directly with Python as described above.

```bash
docker build -t multi-source-scraper .
docker run --rm -v scraper-output:/app/output -v scraper-logs:/app/logs multi-source-scraper --max-pages 3
```

The image runs as a non-root user. The named Docker volumes preserve generated files between container runs.
Pass normal CLI arguments after the image name to override the settings in the bundled configuration file.
The Docker image build has not been verified because the Docker Desktop Linux engine was unavailable; Docker
is optional, and the Python workflow and tests were verified independently.

## Tests
```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```
The tests need **no internet**: `tests/mock_site.py` starts a local server that mimics both sites' markup,
including a permanently failing category (HTTP 500), a page that fails once (503, tests retry), a book card
with no price, and duplicate records written with different case/whitespace.

## Step 1 – Source observations
| | Books to Scrape | Quotes to Scrape |
|---|---|---|
| Record | `article.product_pod` | `div.quote` |
| Fields on listing | title (`h3 a[title]`, untruncated), price (`p.price_color`), rating (class `star-rating Three`), availability, product link | text (`span.text`), author (`small.author`), tags (`a.tag`), author link |
| Pagination | `li.next a` (relative link), 20 books/page | `li.next a`, 10 quotes/page |
| Category | not on the card; the sidebar lists categories, each paginated | none |
| Other quirks | rating is a CSS class, not text; page has no charset header so `£` can appear as `Â£` | quotes have no page of their own; wrapped in curly quotes |

## Pagination
Never hard-coded. Each scraper fetches a page, parses it, then follows the `li.next a` link (resolved with
`urljoin`) until there is none. A visited-set prevents loops, and `--max-pages` caps pages per source.
For Books, the page budget includes the catalogue page used to discover categories and category listing pages;
for Quotes, it limits quote listing pages. Optional product/author detail fetching happens afterward and can
make additional requests beyond the limit.
Books are crawled **per category** (sidebar → each category's pages), which gives every book its category
without one request per book; if the sidebar can't be read, it falls back to following `next` through the
whole catalogue and leaves `category` empty.

## Data model (`final_dataset.csv`)
| Column | Books | Quotes |
|---|---|---|
| `source` | `Books to Scrape` | `Quotes to Scrape` |
| `source_url` | product page URL | listing page the quote appeared on (quotes have no URL of their own) |
| `name_or_title` | book title | quote text (outer curly quotes removed) |
| `category` | category | empty |
| `price`, `currency` | numeric price, `GBP` | empty |
| `rating` | 1–5 integer | empty |
| `author` | empty | author name |
| `tags` | empty | tags joined with `|` |
| `description` | empty unless `--books-details` | author biography |
| `availability` | e.g. `In stock` | empty |
| `scraped_at` | ISO-8601 UTC timestamp | same |

One wide table with nullable columns was chosen over two tables so the result is a single, directly
comparable dataset; fields that don't apply stay empty and nothing is invented.

## Cleaning approach (`processing/cleaning.py`)
Scrapers return **raw, source-shaped values** (mostly strings, with tags as lists); cleaning is separate and
reusable: whitespace collapse (incl. NBSP), placeholder → `None` (`""`, `N/A`, `null`, …), price → float
(handles `£`, `Â£`, thousands commas) with currency detected from the symbol, rating words (`Three`) → int,
URL → absolute http(s) with lower-cased host and no fragment, tags lower-cased and de-duplicated.

## Validation approach (`processing/validation.py`)
A record is **rejected** (written to `rejected_records.csv` with reasons) if: source unrecognised; title or
`source_url` missing/invalid; price present but non-numeric/negative; rating outside 1–5; a book lacks price
or rating; a quote lacks an author. Rejection counts and reasons appear in the summary.

## Deduplication approach (`processing/deduplication.py`)
Comparison uses a **normalised** key (NFKC, case-folded, curly quotes/dashes flattened, punctuation stripped,
whitespace collapsed), so `"Example Book Title"`, `" Example Book Title "` and `"EXAMPLE BOOK TITLE"` match.
Records are duplicates only **within the same source**, when either:
- content keys match — books: *title + price*; quotes: *quote text + author*; or
- (books only) the normalised product URL matches. Quotes are excluded from the URL rule because many quotes share a listing-page URL.

Price is part of the book key so two different editions with the same title are kept. The first occurrence is
kept and later ones are **removed from the final dataset but not discarded silently**: they are written to
`duplicates_report.csv` with the reason and the record they duplicate, so the decision is auditable.

## Error handling & logging
- `HttpClient` has timeouts, up to `--retries` attempts with **exponential backoff** for connection errors,
  timeouts and HTTP 408/425/429/500/502/503/504; other HTTP statuses fail immediately without retry. A minimum
  delay between requests is enforced. A robots.txt 404 is treated as no published policy; other robots.txt
  fetch failures or non-200 responses stop the crawl rather than being treated as permission.
- A failed page is logged and recorded; the crawl moves on (a failed *category* doesn't stop other categories;
  a failed quotes page ends quotes pagination because its `next` link is unreachable, but partial results are kept).
- Missing HTML elements give `None` values and a warning, never a crash; a card that raises is skipped and logged.
- A whole scraper crashing is caught so the other source still runs. Source status is `ok` / `partial` / `crashed` in the summary.
- Logs go to the console and `logs/scrape.log`.

## Output description
```
output/final_dataset.csv        consolidated, standardised, de-duplicated records
output/summary_report.json      per-source and total metrics, failed pages, HTTP stats, run time
output/rejected_records.csv     records dropped by validation/cleaning, with reasons
output/duplicates_report.csv    records removed as duplicates, with what they duplicate
output/data_quality_report.json (bonus) per-source field completeness, price/rating stats, category spread,
                                URL uniqueness, rejection and duplicate rates
logs/scrape.log                 execution log
```
The summary reports: collected per source, after cleaning, rejected (with reason counts), duplicates
detected/removed, final count, execution time.

## Bonus features implemented
Retry with exponential backoff, JSON-configurable settings and CLI arguments (`python main.py --help`), request
rate limiting (`--delay`), unit and end-to-end tests, a data-quality report
(`output/data_quality_report.json`), and an optional non-root Docker image.

## Project structure
```
main.py            CLI + logging setup
pipeline.py        orchestration and output writing
config/            default JSON runtime settings
scrapers/          http_client.py, books_scraper.py, quotes_scraper.py (site-specific selectors live only here)
processing/        schema.py, cleaning.py, validation.py, deduplication.py, quality.py
tests/             unit tests + local mock site + end-to-end tests
Dockerfile         optional container image
```

## Assumptions
- `source_url` for a quote is the listing page it appeared on.
- A book without a parseable price or rating is invalid (every book on the site has both).
- Prices are in GBP as shown on the site; no currency conversion.
- Quote descriptions are the author's bio, fetched once per author.

## Known limitations
- Verified live on 2026-10-06: a full run collected 1000 books (81 pages) and 100 quotes (60 pages incl. 50 author
  pages) with 0 failed pages, 0 rejected, 0 duplicates and 1100 final records in 64.9 s. The practice sites contain no
  duplicates, so duplicate detection is exercised by the unit/mock tests rather than by the live data.
- Sequential, single-threaded (deliberate, to stay polite); a full run takes about a minute.
- No checkpoint/resume or incremental scraping; every run starts from scratch.
- Dedup is exact-after-normalisation, not fuzzy (e.g. typos or subtitle differences are not matched).
- Book descriptions are off by default because they cost one extra request per book.

## AI usage summary
See `AI_USAGE.md`.
