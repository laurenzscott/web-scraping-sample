"""Scrapes the book catalogue of https://books.toscrape.com and writes:

  data/books.csv     one row per book: title, price, currency, availability, rating, url, scraped_at
  data/notes.txt     what was collected, what was removed, what was left empty
  data/facts.json    the same numbers in machine-readable form

books.toscrape.com is a sandbox site built for scraping practice.
The scraper follows the "next" link from page to page (the page count is not
hardcoded), sends one request at a time with a pause between requests, and
identifies itself with an honest User-Agent.

Exit code 0 = rows collected; 1 = no rows or a page could not be fetched
(site changed or blocked). In that case notes.txt says what happened.
"""
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

START_URL = "https://books.toscrape.com/catalogue/page-1.html"
USER_AGENT = "web-scraping-sample/1.0 (portfolio project)"
DELAY_SECONDS = 1.0      # pause between two requests
TIMEOUT_SECONDS = 30
RETRIES = 3              # extra attempts after a network error or a 5xx answer; 4xx is never retried
MAX_PAGES = 200          # safety stop in case the site ever links pages in a circle

DATA = Path(__file__).resolve().parent / "data"
COLUMNS = ["title", "price", "currency", "availability", "rating", "url", "scraped_at"]
RATINGS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
POUND = "\u00a3"  # the pound sign, written as an escape so this file stays plain ASCII


class FetchError(Exception):
    pass


# ------------------------------------------------------------------ parsing

def parse_price(text):
    """'\u00a351.77' -> '51.77'. Returns None when there is no number in the text."""
    if not text:
        return None
    m = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not m:
        return None
    try:
        return f"{Decimal(m.group(0)):.2f}"
    except InvalidOperation:
        return None


def parse_currency(text):
    """Currency as stated next to the price; empty when the page states none."""
    return "GBP" if text and (POUND in text or "GBP" in text) else ""


def parse_rating(classes):
    """['star-rating', 'Three'] -> 3. Returns None when no rating word is present."""
    for c in classes or []:
        if c.lower() in RATINGS:
            return RATINGS[c.lower()]
    return None


def clean_text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def parse_page(html, page_url):
    """Parse one listing page. Returns (books, next_url); next_url is None on the last page."""
    soup = BeautifulSoup(html, "html.parser")
    books = []
    for pod in soup.select("article.product_pod"):
        link = pod.select_one("h3 a")
        title = (link.get("title") or link.get_text()).strip() if link else ""
        href = (link.get("href") or "").strip() if link else ""
        price_text = clean_text(pod.select_one("p.price_color"))
        price = parse_price(price_text)
        stars = pod.select_one("p.star-rating")
        books.append({
            "title": title,
            "price": price,
            "currency": parse_currency(price_text) if price is not None else "",
            "availability": clean_text(pod.select_one("p.instock.availability")),
            "rating": parse_rating(stars.get("class")) if stars else None,
            "url": urljoin(page_url, href) if href else "",
        })
    nxt = soup.select_one("li.next a[href]")
    next_url = urljoin(page_url, nxt["href"]) if nxt else None
    return books, next_url


# ------------------------------------------------------------------ fetching

def fetch(session, url, sleep=time.sleep):
    """GET one page. Retries network errors and 5xx answers, never 4xx."""
    problem = ""
    for attempt in range(RETRIES + 1):
        if attempt:
            sleep(DELAY_SECONDS * 2 ** attempt)          # 2 s, 4 s, 8 s
        try:
            resp = session.get(url, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as e:
            problem = f"network error ({type(e).__name__})"
            continue
        if resp.status_code < 400:
            return resp.content
        if resp.status_code < 500:
            raise FetchError(f"HTTP {resp.status_code} for {url} (not retried)")
        problem = f"HTTP {resp.status_code}"
    raise FetchError(f"{problem} for {url}, gave up after {RETRIES + 1} attempts")


# ------------------------------------------------------------------ run

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    DATA.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    started = utc_now()
    url, visited, pages, listings_read = START_URL, set(), 0, 0
    rows, seen_urls, duplicates, error = [], set(), 0, None

    while url and pages < MAX_PAGES and url not in visited:
        visited.add(url)
        if pages:
            time.sleep(DELAY_SECONDS)
        try:
            html = fetch(session, url)
        except FetchError as e:
            error = str(e)
            break
        scraped_at = utc_now()
        books, url = parse_page(html, url)
        pages += 1
        listings_read += len(books)
        print(f"page {pages}: {len(books)} books")
        for b in books:
            if b["url"] and b["url"] in seen_urls:
                duplicates += 1
                continue
            seen_urls.add(b["url"])
            rows.append({**b, "scraped_at": scraped_at})

    if error is None and url:
        error = f"stopped with a next page still pending ({url}) - page limit reached or circular link"
    if error is None and not rows:
        error = "0 rows found - the page structure may have changed or access was blocked"

    missing_price = sum(1 for r in rows if r["price"] is None)
    missing_rating = sum(1 for r in rows if r["rating"] is None)

    with open(DATA / "books.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r[k] is None else r[k]) for k in COLUMNS})

    facts = {"source": START_URL, "started_utc": started, "finished_utc": utc_now(),
             "ok": error is None, "error": error,
             "pages_read": pages, "listings_read": listings_read,
             "duplicates_removed": duplicates, "rows_collected": len(rows),
             "missing_price": missing_price, "missing_rating": missing_rating,
             "columns": COLUMNS}
    (DATA / "facts.json").write_text(json.dumps(facts, indent=1) + "\n", encoding="utf-8")

    notes = ["SCRAPE NOTES - books.toscrape.com", "",
             f"  started (UTC) ........ {facts['started_utc']}",
             f"  finished (UTC) ....... {facts['finished_utc']}",
             f"  pages read ........... {pages}",
             f"  listings read ........ {listings_read}",
             f"  duplicates removed ... {duplicates}  (rule: same url)",
             f"  rows collected ....... {len(rows)}",
             f"  missing price ........ {missing_price}  (left empty, not guessed)",
             f"  missing rating ....... {missing_rating}  (left empty, not guessed)",
             "",
             "  price is a number, currency in its own column",
             "  availability copied as the page states it",
             "  every row carries its full link, so any line can be checked",
             ""]
    notes.append("RESULT: OK" if error is None else f"RESULT: FAILED - {error}")
    (DATA / "notes.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    print("\n".join(notes))
    return 0 if error is None else 1


if __name__ == "__main__":
    sys.exit(main())
