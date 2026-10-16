"""linkrot - find dead links in Markdown documentation.

Concurrent link checker that scans Markdown files for external links,
verifies they are still alive, and reports the dead ones as Markdown or JSON.
Zero third-party dependencies (Python standard library only).
"""

from linkrot.check import check_urls, check_url, LinkResult  # noqa: F401
from linkrot.extract import extract_links_from_file, extract_links_from_text, Link  # noqa: F401

__version__ = "1.0.0"
