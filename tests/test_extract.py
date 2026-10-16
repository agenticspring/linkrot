"""Tests for link extraction (no network needed)."""

import unittest

from linkrot.extract import extract_links_from_file, extract_links_from_text


class ExtractTest(unittest.TestCase):
    def test_inline_link(self):
        links = extract_links_from_text("[Docs](https://example.com/docs)")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].url, "https://example.com/docs")
        self.assertEqual(links[0].kind, "inline")
        self.assertEqual(links[0].line, 1)

    def test_inline_link_with_title(self):
        links = extract_links_from_text('[Docs](https://example.com "the docs")')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].url, "https://example.com")

    def test_inline_link_with_parens_in_url(self):
        links = extract_links_from_text(
            "[Wiki](https://en.wikipedia.org/wiki/Python_(programming_language))"
        )
        self.assertEqual(len(links), 1)
        self.assertTrue(links[0].url.endswith("Python_(programming_language)"))

    def test_reference_style(self):
        text = "[Docs][ref]\n\n[ref]: https://example.com/docs\n"
        links = extract_links_from_text(text)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].url, "https://example.com/docs")
        self.assertEqual(links[0].kind, "reference")

    def test_reference_style_implicit_text(self):
        text = "[Home][home]\n\n[home]: https://example.com\n"
        links = extract_links_from_text(text)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].url, "https://example.com")

    def test_bare_url(self):
        links = extract_links_from_text("Visit https://example.com now.")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].url, "https://example.com")
        self.assertEqual(links[0].kind, "bare")

    def test_bare_url_no_double_count(self):
        # Bare-URL pass must not re-report URLs already found in link syntax.
        links = extract_links_from_text("[Docs](https://example.com/docs)")
        bare = [link for link in links if link.kind == "bare"]
        self.assertEqual(bare, [])

    def test_ignores_fenced_code_block(self):
        text = "```\n[Docs](https://code.example.com)\n```\n[Real](https://real.example.com)\n"
        links = extract_links_from_text(text)
        self.assertEqual([link.url for link in links], ["https://real.example.com"])

    def test_ignores_inline_code(self):
        text = "Run `[Docs](https://code.example.com)` now, or see https://real.example.com\n"
        links = extract_links_from_text(text)
        self.assertEqual([link.url for link in links], ["https://real.example.com"])

    def test_non_http_ignored(self):
        links = extract_links_from_text("[Mail](mailto:a@example.com)\n[file](./local.md)\n")
        self.assertEqual(links, [])

    def test_line_numbers(self):
        text = "first\n\n[Docs](https://example.com)\n"
        links = extract_links_from_text(text)
        self.assertEqual(links[0].line, 3)

    def test_multiple_links_and_dedup_spans(self):
        text = ("See [a](https://a.example.com), [b][b], https://c.example.com.\n\n"
                "[b]: https://b.example.com\n")
        urls = sorted(link.url for link in extract_links_from_text(text))
        self.assertEqual(urls, ["https://a.example.com", "https://b.example.com",
                                "https://c.example.com"])


class ExtractFileTest(unittest.TestCase):
    def test_reads_file(self):
        import os, tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write("[Docs](https://example.com)\n")
            name = fh.name
        try:
            links = extract_links_from_file(name)
            self.assertEqual(len(links), 1)
        finally:
            os.unlink(name)

    def test_missing_file_returns_empty(self):
        self.assertEqual(extract_links_from_file("/nonexistent/file.md"), [])


if __name__ == "__main__":
    unittest.main()
