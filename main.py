"""CLI entry point:  python main.py [options]   (see --help)"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pipeline


def _load_config(config_path):
    with open(config_path, encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("configuration must be a JSON object")

    allowed = {
        "sources", "output_dir", "log_dir", "max_pages", "delay", "timeout", "retries",
        "backoff", "books_details", "author_details", "books_url", "quotes_url",
    }
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"unknown configuration setting(s): {', '.join(sorted(unknown))}")

    if "sources" in config and (
        not isinstance(config["sources"], list)
        or not config["sources"]
        or any(not isinstance(source, str) or source not in {"books", "quotes"}
               for source in config["sources"])
    ):
        raise ValueError("'sources' must be a non-empty list containing only 'books' and/or 'quotes'")
    for key in ("output_dir", "log_dir", "books_url", "quotes_url"):
        if key in config and (not isinstance(config[key], str) or not config[key].strip()):
            raise ValueError(f"'{key}' must be a non-empty string")
    for key in ("books_details", "author_details"):
        if key in config and not isinstance(config[key], bool):
            raise ValueError(f"'{key}' must be true or false")
    if "max_pages" in config and config["max_pages"] is not None and (
        type(config["max_pages"]) is not int or config["max_pages"] < 1
    ):
        raise ValueError("'max_pages' must be a positive integer or null")
    for key in ("delay", "timeout", "retries", "backoff"):
        if key not in config:
            continue
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"'{key}' must be a number")
        if (key in {"timeout", "retries"} and value < 1) or (
            key in {"delay", "backoff"} and value < 0
        ):
            bound = "at least 1" if key in {"timeout", "retries"} else "non-negative"
            raise ValueError(f"'{key}' must be {bound}")
        if key == "retries" and type(value) is not int:
            raise ValueError("'retries' must be an integer")
    return config


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Scrape Books/Quotes to Scrape into one cleaned dataset.")
    default_config = Path(__file__).resolve().parent / "config" / "config.json"
    p.add_argument("--config", default=str(default_config), help="JSON settings file")
    p.add_argument("--sources", nargs="+", choices=["books", "quotes"])
    p.add_argument("--output-dir")
    p.add_argument("--log-dir")
    p.add_argument("--max-pages", type=int,
                   help="page budget PER SOURCE (default: scrape everything)")
    p.add_argument("--delay", type=float, help="minimum seconds between requests")
    p.add_argument("--timeout", type=float)
    p.add_argument("--retries", type=int, help="attempts per URL")
    p.add_argument("--backoff", type=float, help="base seconds for exponential backoff")
    p.add_argument("--books-details", action="store_true", default=None,
                   help="also fetch every book page for its description (~1000 extra requests)")
    p.add_argument("--no-author-details", dest="author_details", action="store_false", default=None,
                   help="skip fetching author pages (quote description stays empty)")
    p.add_argument("--books-url")
    p.add_argument("--quotes-url")
    p.add_argument("--ignore-robots", action="store_true", help="(testing only) skip robots.txt check")
    p.add_argument("--verbose", action="store_true")

    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument("--config", default=str(default_config))
    config_path = preliminary.parse_known_args(argv)[0].config
    try:
        config = _load_config(config_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        p.error(f"cannot load config {config_path}: {exc}")
    defaults = {
        "sources": ["books", "quotes"], "output_dir": "output", "log_dir": "logs",
        "max_pages": None, "delay": 0.3, "timeout": 15.0, "retries": 3,
        "backoff": 1.0, "books_details": False, "author_details": True,
        "books_url": "https://books.toscrape.com/",
        "quotes_url": "https://quotes.toscrape.com/",
    }
    defaults.update(config)
    p.set_defaults(**defaults)
    return p.parse_args(argv)


def setup_logging(log_dir, verbose):
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in (logging.FileHandler(Path(log_dir) / "scrape.log", mode="w", encoding="utf-8"),
                    logging.StreamHandler()):
        handler.setFormatter(fmt)
        root.addHandler(handler)


def main(argv=None):
    args = parse_args(argv)
    setup_logging(args.log_dir, args.verbose)
    summary = pipeline.run(vars(args))
    t = summary["totals"]
    print(f"\nFinal records: {t['final_records']} (collected {t['collected']}, rejected "
          f"{t['rejected_total']}, duplicates removed {t['duplicates_removed']})")
    print(f"Output written to: {args.output_dir}/")
    # Non-zero exit only if nothing at all could be produced.
    return 0 if t["final_records"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
