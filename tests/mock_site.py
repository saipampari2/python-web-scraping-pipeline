"""A tiny local web server that mimics the markup of both practice sites.

Lets the whole pipeline be tested offline, including failure cases:
  * Books category "Poetry" always returns HTTP 500        (page failure must not stop the run)
  * Books page /catalogue/category/books/travel_2/page-2.html fails once with 503 (retry works)
  * One book card lacks a price                            (validation rejects it)
  * Duplicate book / quote with different case + whitespace (dedup catches it)
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STAR = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}


def book_card(title, price, rating, slug, with_price=True):
    price_html = f'<p class="price_color">{price}</p>' if with_price else ""
    return (f'<article class="product_pod"><p class="star-rating {STAR[rating]}"></p>'
            f'<h3><a href="../../../{slug}/index.html" title="{title}">{title[:20]}...</a></h3>'
            f'<div class="product_price">{price_html}'
            f'<p class="instock availability"><i></i>\n   In stock\n</p></div></article>')


def books_page(cards, next_href=None, categories=()):
    side = "".join(f'<li><a href="{u}">\n {n} \n</a></li>' for n, u in categories)
    nxt = f'<li class="next"><a href="{next_href}">next</a></li>' if next_href else ""
    return (f'<html><body><div class="side_categories"><ul><li><a href="x">Books</a><ul>{side}</ul></li></ul></div>'
            f'{"".join(cards)}<ul class="pager">{nxt}</ul></body></html>')


def quote_card(text, author, tags):
    tag_html = "".join(f'<a class="tag" href="/tag/{t}/page/1/">{t}</a>' for t in tags)
    return (f'<div class="quote"><span class="text">“{text}”</span>'
            f'<span>by <small class="author">{author}</small>'
            f'<a href="/author/{"-".join(author.split())}">(about)</a></span>'
            f'<div class="tags">{tag_html}</div></div>')


def quotes_page(cards, next_href=None):
    nxt = f'<li class="next"><a href="{next_href}">Next</a></li>' if next_href else ""
    return f'<html><body>{"".join(cards)}<ul class="pager">{nxt}</ul></body></html>'


def build_routes():
    cats = [("Travel", "catalogue/category/books/travel_2/index.html"),
            ("Mystery", "catalogue/category/books/mystery_3/index.html"),
            ("Poetry", "catalogue/category/books/poetry_23/index.html")]
    r = {}
    r["/books/"] = (200, books_page([], categories=cats))
    base = "/books/catalogue/category/books"
    r[f"{base}/travel_2/index.html"] = (200, books_page(
        [book_card("It's Only the Himalayas", "Â£45.17", 2, "himalayas_1"),
         book_card("Full Moon over Noah's Ark", "Â£49.43", 4, "noah_2")],
        next_href="page-2.html"))
    r[f"{base}/travel_2/page-2.html"] = (200, books_page(
        [book_card("Scott Pilgrim", "Â£52.29", 5, "scott_3")]))
    r[f"{base}/mystery_3/index.html"] = (200, books_page(
        [book_card("Sharp Objects", "Â£47.82", 4, "sharp_4"),
         book_card("  SHARP   objects ", "Â£47.82", 4, "sharp_dup_5"),   # duplicate
         book_card("No Price Book", "", 3, "noprice_6", with_price=False)]))       # invalid
    r[f"{base}/poetry_23/index.html"] = (500, "boom")

    r["/quotes/"] = (200, quotes_page(
        [quote_card("The world as we have created it", "Albert Einstein", ["change", "deep-thoughts"]),
         quote_card("It is our choices", "J.K. Rowling", ["abilities", "choices"])],
        next_href="/quotes/page/2/"))
    r["/quotes/page/2/"] = (200, quotes_page(
        [quote_card("The  world as we have CREATED it", "Albert  Einstein", ["Change"]),  # duplicate
         quote_card("Life is what happens", "John Lennon", ["life"])],
        next_href="/quotes/page/3/"))
    r["/quotes/page/3/"] = (200, quotes_page([quote_card("Imperfection is beauty", "Marilyn Monroe", ["beauty"])]))
    for name in ("Albert-Einstein", "J.K.-Rowling", "John-Lennon", "Marilyn-Monroe"):
        r[f"/author/{name}"] = (200, f'<div class="author-details"><div class="author-description">'
                                      f' Bio of {name}. </div></div>')
    return r


class MockSite:
    def __init__(self):
        self.routes = build_routes()
        self.hits = {}
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path
                site.hits[path] = site.hits.get(path, 0) + 1
                if path == "/books/catalogue/category/books/travel_2/page-2.html" and site.hits[path] == 1:
                    status, body = 503, "try again"  # flaky once
                else:
                    status, body = site.routes.get(path, (404, "not found"))
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html")  # deliberately no charset
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def books_url(self):
        return f"http://127.0.0.1:{self.port}/books/"

    @property
    def quotes_url(self):
        return f"http://127.0.0.1:{self.port}/quotes/"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
