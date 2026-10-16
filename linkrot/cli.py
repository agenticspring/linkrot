"""Command-line interface for linkrot."""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
import time

from linkrot.check import check_urls
from linkrot.extract import extract_links_from_file
from linkrot.report import build_json, build_markdown

DEFAULT_EXCLUDES = (".git/*", "node_modules/*", "vendor/*")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="linkrot",
        description="Find dead links in Markdown files. "
                    "Exit code 0 = no dead links, 1 = dead links found, 2 = error.",
    )
    parser.add_argument("path", nargs="?", default=".",
                        help="directory (or file) to scan (default: current directory)")
    parser.add_argument("--include", action="append", default=["*.md"],
                        help="glob for files to include (may be repeated; default: *.md)")
    parser.add_argument("--exclude", action="append", default=[],
                        help="glob for paths to exclude (may be repeated)")
    parser.add_argument("--exclude-url", action="append", default=[],
                        help="regex for URLs to skip (may be repeated)")
    parser.add_argument("--concurrency", type=int, default=10,
                        help="parallel requests (default: 10)")
    parser.add_argument("--timeout", type=float, default=10,
                        help="seconds per request (default: 10)")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown",
                        help="report format (default: markdown)")
    parser.add_argument("--report", metavar="FILE",
                        help="write report to FILE instead of stdout")
    parser.add_argument("--quiet", action="store_true",
                        help="print only the report, no progress info")
    parser.add_argument("--version", action="version", version="linkrot 1.0.0")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be a positive number of seconds")
    return args


def _matches_any(patterns: list[str], relpath: str, basename: str) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(relpath, pattern) or fnmatch.fnmatch(basename, pattern):
            return True
        # A trailing "/*" should also exclude the directory itself and deeper paths.
        if pattern.endswith("/*") and (
            relpath == pattern[:-2] or relpath.startswith(pattern[:-1])
        ):
            return True
    return False


def collect_files(root: str, includes: list[str], excludes: list[str]) -> list[str]:
    """Recursively collect matching Markdown files under ``root``."""
    excludes = list(DEFAULT_EXCLUDES) + excludes
    if os.path.isfile(root):
        return [root]
    if not os.path.isdir(root):
        raise FileNotFoundError(f"no such file or directory: {root}")

    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories early (cheap win on big trees).
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        dirnames[:] = [
            d for d in dirnames
            if not _matches_any(excludes, f"{rel_dir}/{d}".lstrip("./"), d)
        ]
        for name in filenames:
            relpath = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
            if not _matches_any(includes, relpath, name):
                continue
            if _matches_any(excludes, relpath, name):
                continue
            found.append(os.path.join(dirpath, name))
    return sorted(found)


def _emit(message: str, report_path: str | None) -> None:
    if report_path:
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(message if message.endswith("\n") else message + "\n")
    else:
        print(message, end="" if message.endswith("\n") else "\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        url_exclusions = [re.compile(pattern) for pattern in args.exclude_url]
        start = time.time()
        files = collect_files(args.path, args.include, args.exclude)
        if not args.quiet:
            print(f"linkrot: scanning {len(files)} file(s)...", file=sys.stderr)

        # Extract links: {url: [(file, line, text)]}
        occurrences: dict[str, list[tuple[str, int, str]]] = {}
        display_root = (os.path.abspath(args.path)
                        if os.path.isdir(args.path) else os.path.dirname(os.path.abspath(args.path)))
        for path in files:
            abs_path = os.path.abspath(path)
            relpath = os.path.relpath(abs_path, display_root).replace(os.sep, "/")
            for link in extract_links_from_file(path):
                if any(pattern.search(link.url) for pattern in url_exclusions):
                    continue
                occurrences.setdefault(link.url, []).append((relpath, link.line, link.text))

        if not args.quiet:
            print(f"linkrot: checking {len(occurrences)} unique link(s)...", file=sys.stderr)
        results = check_urls(list(occurrences), concurrency=args.concurrency,
                             timeout=args.timeout)
        elapsed = time.time() - start

        dead: list[dict] = []
        for url, result in results.items():
            if result.ok:
                continue
            for relpath, line, text in occurrences[url]:
                dead.append({
                    "file": relpath,
                    "line": line,
                    "url": url,
                    "text": text,
                    "status": result.status,
                    "final_url": result.final_url,
                    "detail": result.detail,
                })
        dead.sort(key=lambda e: (e["file"], e["line"]))

        if args.format == "json":
            report = build_json(dead, len(files), len(occurrences), elapsed)
        else:
            report = build_markdown(dead, len(files), len(occurrences), elapsed)
        _emit(report, args.report)

        return 1 if dead else 0
    except (FileNotFoundError, re.error, OSError) as exc:
        print(f"linkrot: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("linkrot: interrupted", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
