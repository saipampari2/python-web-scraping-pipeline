# AI Usage

> **Candidate: review and edit this file before submitting.** It records what actually happened in the
> session that produced this project. You are expected to understand and be able to explain all the code,
> so read it, run it, and add your own notes under "My review".

## Tools used
| Tool | Used for |
|---|---|
| Claude (Sonnet 5.5, in Claude Code-style agent session) | Planning, generating essentially all of the code, tests and documentation; debugging |
| Copilot SDK in VS Code | Reviewing the project against the supplied roadmap; adding JSON configuration support, Docker files, tests and related documentation |

Additional tool: Copilot SDK in VS Code was used to add the JSON config (`config/config.json`, `--config` option)
and the optional Dockerfile. A Docker image build was attempted but could not be completed because the Docker
Desktop Linux engine was not running.

## Representative prompts
1. *(attached the assignment PDF)* "build app"
   — the full pipeline, tests and docs were generated from the PDF requirements alone, with no further guidance.

(Add your own follow-up prompts here if you continue the work with an AI tool.)
2. "Make the project from the supplied assignment roadmap."
   — reviewed the existing implementation, added JSON settings with CLI overrides and optional Docker support,
   and documented and tested those additions.

## Which parts were AI-assisted
The original implementation: `scrapers/*`, `processing/*`, `pipeline.py`, `main.py`, `tests/*`, `README.md`,
and this file's first draft. The follow-up also added JSON configuration loading in `main.py`, its tests,
`config/config.json`, the `Dockerfile`, `.dockerignore`, and corresponding README guidance.

## Design decisions made by the AI (be ready to explain or change these)
- Requests + BeautifulSoup/lxml rather than Scrapy/Playwright (static HTML).
- Books crawled category-by-category to get categories cheaply; book descriptions optional.
- Raw scrapers vs. cleaning separated: scrapers extract source-shaped values, `cleaning.py` standardises them.
- Duplicates are removed from the final CSV but logged to `duplicates_report.csv`.
- Dedup key: books = title + price (+ URL); quotes = text + author; never across sources.

## Issues found with AI output during the session
- The first test run had **3 failing tests**, all caused by bugs in the AI-written *mock site* (wrong route
  path for the books index, wrong number of `../` in book links, author URLs built from a double-spaced name),
  not in the pipeline. Fixed, and the suite then passed.
- A page-structure lookup of the live site returned only a partial description (it could not show the star-rating
  markup), so the rating selector (`p.star-rating` with a word class like `Three`) relies on knowledge of the
  site, not on that lookup.
- The `£` → `Â£` encoding issue was handled pre-emptively (forcing UTF-8 and parsing numbers with a regex) and
  is covered by unit tests, but has **not** been observed on the live site.
- A later code review found that non-200 or unreachable `robots.txt` responses were treated as permission to
  crawl. The HTTP client was changed to stop crawling in those cases; an explicit `robots.txt` 404 remains
  allowed, and a regression test covers a 403 response.

## How it was tested and verified
- 45 pytest tests (cleaning, validation, dedup, scrapers, retry/backoff, robots handling, failed pages, end-to-end
  pipeline, and CLI config) all pass,
  using a local mock server — no internet.
- The CLI (`python main.py`) was run against the mock site and produced the expected CSV, JSON summary and log.
- The AI's own sandbox could not reach the live sites, so the live run was done by the candidate on their machine
  (Windows, Python 3.13): `python main.py` collected 1000 books (81 pages, 50 categories) and 100 quotes
  (60 pages incl. 50 author pages), 0 failed pages, 0 rejected, 0 duplicates, and 1100 final records. Recorded
  full-run times ranged from 57 to 64.9 seconds. This confirmed the selectors work on the real sites.

## My review
I ran the full scrape on my own machine (Windows, Python 3.13): 1100 records collected
(1000 books from 50 categories, 100 quotes), 0 failed pages, 0 rejected, 0 duplicates, in about one minute.
I also ran the test suite locally and all 45 tests passed. I opened final_dataset.csv in Excel
to check the output. The practice sites contain no duplicates, so duplicate detection was
verified through the unit tests rather than live data. I reviewed the pagination, cleaning,
validation and deduplication logic and can explain how each part works.
