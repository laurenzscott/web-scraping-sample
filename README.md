# web-scraping-sample

A small, polite scraper that turns an online book catalogue into a clean CSV,
with delivery notes that say exactly what was collected and what was left empty.

This is a portfolio sample, not a client project.

## What it does

`scrape.py` reads the catalogue of [books.toscrape.com](https://books.toscrape.com),
page by page, following the "next" link until there is none (the number of pages
is not hardcoded). For every book it collects title, price, availability, star
rating and link, removes duplicates and writes three files:

- `data/books.csv` - one row per book
- `data/notes.txt` - delivery notes: pages read, rows collected, duplicates
  removed, rows with a missing price or rating
- `data/facts.json` - the same numbers, machine-readable

## Why books.toscrape.com

It is a sandbox site built explicitly for scraping practice: fictional books with
made-up prices and ratings, published so that people can practise on it. It exists
to be scraped, so there is no terms-of-service issue and no real shop is put under load.

## Columns

| Column | Example | Notes |
|---|---|---|
| `title` | A Light in the Attic | full title (the listing shortens long titles; the full one is read from the link) |
| `price` | 51.77 | a plain number, ready to sum or sort |
| `currency` | GBP | in its own column instead of a `£` inside the price |
| `availability` | In stock | as the page states it |
| `rating` | 3 | star rating as a number from 1 to 5 |
| `url` | https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html | full link, so any row can be checked |
| `scraped_at` | YYYY-MM-DDThh:mm:ssZ | when the page was read (UTC) |

Nothing is guessed: a price or rating that cannot be read is left empty and
counted in `data/notes.txt`.

## Last run

Last run: see [data/notes.txt](data/notes.txt) (written by the scheduled GitHub
Action; the numbers there come from the run itself, not from this README).

## How it behaves

- one request at a time, with a 1-second pause between pages
- an honest User-Agent: `web-scraping-sample/1.0 (portfolio project)`
- 30-second timeout per request
- network errors and server errors (5xx) are retried up to 3 times with a
  growing pause; client errors (4xx, e.g. blocked or not found) are never retried
- if no rows are found or a page cannot be fetched (site changed or blocked), the
  script says so in `data/notes.txt` and exits with an error, so the GitHub Action
  fails visibly and the last good data stays in place
- runs once a week (Monday 06:17 UTC) - enough for a sample, and it keeps the
  load on the site low

## Run it locally

Python 3.12:

```
pip install -r requirements.txt
python tests/test_parse.py
python scrape.py
```

The tests use a saved test page (`tests/fixtures/page.html`) and fake network
answers, so they run without internet access. They check price parsing, the
rating mapping (including a book without a rating that must stay empty), full
links, the next-page link, duplicate removal and the retry rules.

## Run it on GitHub

Actions -> "Scrape the catalogue" -> Run workflow. The workflow installs the two
dependencies, runs the tests (and stops if one fails), scrapes the site and
commits the updated `data/` folder.

## What a client gets in a real job

- the data as CSV, Excel or Google Sheets, with the columns agreed beforehand
- the same columns in the same order on every run, so imports and formulas keep working
- delivery notes like `data/notes.txt`: what was collected, what was removed, what
  was left empty and why
- optionally the script itself and a scheduled run, like the one in this repository
