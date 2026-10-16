"""Link extraction from Markdown text.

Supports three Markdown link forms (http/https only):

- Inline:        ``[text](https://example.com)``
- Reference:     ``[text][ref]`` together with a definition ``[ref]: https://example.com``
- Bare URL:      ``https://example.com`` written directly in the text

Fenced code blocks (``` ... ```) and inline code (`...`) are ignored, so
URLs in code samples are not treated as documentation links.
"""

from __future__ import annotations

import re
from collections import namedtuple

Link = namedtuple("Link", ["url", "text", "line", "kind"])

# Fenced code blocks (``` or ~~~, optionally with a language tag).
_FENCED_CODE_RE = re.compile(r"(?ms)^(```|~~~)[^\S\n]*.*?\n\1[^\S\n]*$")
# Inline code spans: `code` or ``code``.
_INLINE_CODE_RE = re.compile(r"`+[^`\n]+`+")
# Reference-style definitions: [ref]: https://example.com (multiline mode).
_REFERENCE_DEF_RE = re.compile(
    r"(?m)^[ \t]{0,3}\[([^\]]+)\]:[ \t]*<?(https?://[^\s>]+)>?(?:[ \t]+.*)?$"
)
# Inline links: [text](url "optional title"). Matched in two steps below.
_INLINE_LINK_START_RE = re.compile(r"\[[^\]]*\]\(\s*")
# Bare URLs, not part of a link construct (checked against matched spans).
_BARE_URL_RE = re.compile(r"https?://[^\s<>\[\]()\"']+")
# Reference-style usage: [text][ref] or shortcut [ref].
_REFERENCE_USE_RE = re.compile(r"\[([^\]]*)\]\[([^\]]*)\]")
_SHORTCUT_USE_RE = re.compile(r"(?<![\]:\w])\[([^\]]+)\](?![\]:\(])")

_ONLY_HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)


def _line_number(text: str, offset: int) -> int:
    """Return the 1-based line number of ``offset`` in ``text``."""
    return text.count("\n", 0, offset) + 1


def _strip_code(text: str) -> str:
    """Replace code blocks/spans with whitespace so spans stay aligned."""
    def _blank(match: re.Match) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    text = _FENCED_CODE_RE.sub(_blank, text)
    return _INLINE_CODE_RE.sub(_blank, text)


def _balanced_url_paren(text: str, start: int) -> tuple[str | None, int]:
    """Read a URL starting at ``start`` up to the closing paren.

    Handles one level of nested parentheses (e.g. Wikipedia URLs) and
    skips a trailing ``"title"``. Returns (url, end_offset_of_closing_paren).
    """
    depth = 0
    end = start
    while end < len(text):
        ch = text[end]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
        elif ch in " \t\n\"'" and depth == 0:
            break
        end += 1
    raw = text[start:end].strip()
    if not raw:
        return None, start
    # Split off an optional "title".
    raw = raw.split(None, 1)[0]
    url = raw.strip("<>")
    return (url or None), end


def extract_links_from_text(text: str) -> list[Link]:
    """Extract all external http/https links from Markdown ``text``."""
    clean = _strip_code(text)
    links: list[Link] = []
    used_spans: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(s < end and start < e for s, e in used_spans)

    def _add(url: str, link_text: str, offset: int, kind: str, span: tuple[int, int]) -> None:
        if not _ONLY_HTTP_RE.match(url):
            return
        # Drop trailing punctuation that is almost never part of a URL.
        url = url.rstrip(".,;:!?")
        links.append(Link(url=url, text=link_text, line=_line_number(text, offset), kind=kind))
        used_spans.append(span)

    # 1) Reference definitions: [ref]: https://...
    definitions: dict[str, tuple[str, int]] = {}
    for match in _REFERENCE_DEF_RE.finditer(clean):
        ref = match.group(1).strip()
        definitions[ref.lower()] = (match.group(2), match.start(2))
        # Mark the definition's URL span as used: the bare-URL pass must not
        # report definition URLs as separate "bare" links.
        used_spans.append((match.start(2), match.end(2)))

    # 2) Inline links: [text](url)
    for match in _INLINE_LINK_START_RE.finditer(clean):
        url_start = match.end()
        url, closing = _balanced_url_paren(clean, url_start)
        if url and closing < len(clean) and clean[closing] == ")":
            if not _overlaps(match.start(), closing + 1):
                link_text = match.group(0)[1 : match.group(0).index("]")]
                _add(url, link_text, match.start(), "inline", (match.start(), closing + 1))

    # 3) Reference-style usage: [text][ref]
    for match in _REFERENCE_USE_RE.finditer(clean):
        ref = (match.group(2) or match.group(1)).strip().lower()
        if ref in definitions:
            url, _ = definitions[ref]
            if not _overlaps(match.start(), match.end()):
                _add(url, match.group(1), match.start(), "reference",
                     (match.start(), match.end()))

    # 4) Shortcut reference: [ref]
    for match in _SHORTCUT_USE_RE.finditer(clean):
        ref = match.group(1).strip().lower()
        if ref in definitions:
            url, _ = definitions[ref]
            if not _overlaps(match.start(), match.end()):
                _add(url, ref, match.start(), "shortcut", (match.start(), match.end()))

    # 5) Bare URLs in plain text.
    for match in _BARE_URL_RE.finditer(clean):
        if _overlaps(match.start(), match.end()):
            continue
        _add(match.group(0), "", match.start(), "bare", (match.start(), match.end()))

    return links


def extract_links_from_file(path: str) -> list[Link]:
    """Read ``path`` as UTF-8 and extract links (returns [] on read errors)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return extract_links_from_text(handle.read())
    except (OSError, UnicodeDecodeError):
        return []
