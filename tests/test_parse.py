"""Checks parsing and fetching against a saved test page, without touching the network.

Run with plain Python from the repository root:  python tests/test_parse.py
(after: pip install -r requirements.txt). Exits non-zero if any check fails.
"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scrape  # noqa: E402

PAGE_URL = "https://books.toscrape.com/catalogue/page-1.html"
FIXTURE = (HERE / "fixtures" / "page.html").read_bytes()
LAST_PAGE = FIXTURE.replace(b'<li class="next"><a href="page-2.html">next</a></li>', b"")
POUND = "\u00a3"


class FakeResponse:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


class FakeSession:
    """Answers GET requests from a list of prepared responses (or exceptions)."""
    def __init__(self, answers):
        self.answers, self.calls, self.headers = dict(answers), [], {}

    def get(self, url, timeout):
        self.calls.append(url)
        answer = self.answers[url]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Parsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.books, cls.next_url = scrape.parse_page(FIXTURE, PAGE_URL)

    def test_finds_all_books(self):
        self.assertEqual(len(self.books), 3)

    def test_full_title_from_title_attribute(self):
        self.assertEqual(self.books[0]["title"], "A Light in the Attic")   # link text is cut off

    def test_price_and_currency(self):
        self.assertEqual([b["price"] for b in self.books], ["51.77", "53.74", "50.10"])
        self.assertEqual({b["currency"] for b in self.books}, {"GBP"})

    def test_rating_mapping_and_missing_rating_stays_empty(self):
        self.assertEqual([b["rating"] for b in self.books], [3, 1, None])

    def test_availability(self):
        self.assertEqual(self.books[0]["availability"], "In stock")

    def test_absolute_urls(self):
        self.assertEqual(self.books[0]["url"],
                         "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html")
        self.assertTrue(all(b["url"].startswith("https://books.toscrape.com/catalogue/") for b in self.books))

    def test_next_link(self):
        self.assertEqual(self.next_url, "https://books.toscrape.com/catalogue/page-2.html")
        self.assertIsNone(scrape.parse_page(LAST_PAGE, PAGE_URL)[1])

    def test_price_parser_edge_cases(self):
        self.assertEqual(scrape.parse_price(POUND + "51.77"), "51.77")
        self.assertEqual(scrape.parse_price("\u00c2" + POUND + "51.77"), "51.77")   # badly decoded page
        self.assertEqual(scrape.parse_price(POUND + "1,234.5"), "1234.50")
        self.assertIsNone(scrape.parse_price(""))
        self.assertIsNone(scrape.parse_price("Price on request"))

    def test_rating_parser(self):
        self.assertEqual(scrape.parse_rating(["star-rating", "Five"]), 5)
        self.assertIsNone(scrape.parse_rating(["star-rating"]))


class Fetching(unittest.TestCase):
    def test_retries_5xx_then_succeeds(self):
        s = FakeSession({PAGE_URL: [FakeResponse(503), FakeResponse(200, b"ok")]})
        self.assertEqual(scrape.fetch(s, PAGE_URL, sleep=lambda _: None), b"ok")
        self.assertEqual(len(s.calls), 2)

    def test_retries_network_errors_at_most_3_times(self):
        s = FakeSession({PAGE_URL: [scrape.requests.ConnectionError()] * 10})
        with self.assertRaises(scrape.FetchError):
            scrape.fetch(s, PAGE_URL, sleep=lambda _: None)
        self.assertEqual(len(s.calls), 4)          # 1 try + 3 retries

    def test_never_retries_4xx(self):
        s = FakeSession({PAGE_URL: [FakeResponse(404), FakeResponse(200, b"ok")]})
        with self.assertRaises(scrape.FetchError):
            scrape.fetch(s, PAGE_URL, sleep=lambda _: None)
        self.assertEqual(len(s.calls), 1)


class WholeRun(unittest.TestCase):
    """Runs main() against two fake pages: page 2 repeats the three books of page 1."""

    def run_main(self, answers):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        session = FakeSession(answers)
        with mock.patch.object(scrape, "DATA", Path(tmp.name)), \
             mock.patch.object(scrape.requests, "Session", lambda: session), \
             mock.patch.object(scrape.time, "sleep", lambda _: None), \
             mock.patch("builtins.print"):
            code = scrape.main()
        return code, Path(tmp.name), session

    def test_follows_next_link_removes_duplicates_and_writes_files(self):
        page2 = "https://books.toscrape.com/catalogue/page-2.html"
        code, out, session = self.run_main({PAGE_URL: FakeResponse(200, FIXTURE),
                                            page2: FakeResponse(200, LAST_PAGE)})
        self.assertEqual(code, 0)
        self.assertEqual(session.calls, [PAGE_URL, page2])
        facts = json.loads((out / "facts.json").read_text(encoding="utf-8"))
        self.assertEqual((facts["pages_read"], facts["listings_read"], facts["duplicates_removed"],
                          facts["rows_collected"], facts["missing_rating"], facts["missing_price"]),
                         (2, 6, 3, 3, 1, 0))
        with open(out / "books.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(list(rows[0].keys()), scrape.COLUMNS)
        self.assertEqual(rows[2]["rating"], "")
        self.assertTrue(rows[0]["scraped_at"].endswith("Z"))
        self.assertIn("RESULT: OK", (out / "notes.txt").read_text(encoding="utf-8"))

    def test_zero_rows_fails_and_says_so(self):
        code, out, _ = self.run_main({PAGE_URL: FakeResponse(200, b"<html><body>changed</body></html>")})
        self.assertEqual(code, 1)
        self.assertIn("RESULT: FAILED - 0 rows found", (out / "notes.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
