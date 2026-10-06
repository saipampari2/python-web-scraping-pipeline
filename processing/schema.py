"""Common output schema shared by every source."""

SOURCE_BOOKS = "Books to Scrape"
SOURCE_QUOTES = "Quotes to Scrape"
KNOWN_SOURCES = {SOURCE_BOOKS, SOURCE_QUOTES}

# Column order of final_dataset.csv.
FIELDS = [
    "source",
    "source_url",
    "name_or_title",
    "category",
    "price",
    "currency",
    "rating",
    "author",
    "tags",
    "description",
    "availability",
    "scraped_at",
]

TAG_SEPARATOR = "|"
RATING_MIN = 1
RATING_MAX = 5
