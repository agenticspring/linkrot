"""Tests for CLI-level behavior: arg validation and path matching (no network)."""

import os
import tempfile
import unittest

from linkrot.cli import _matches_any, collect_files, main, parse_args


class MatchesAnyTest(unittest.TestCase):
    def test_trailing_star_excludes_directory_itself(self):
        # "dir/*" must exclude the directory itself, not just deeper paths.
        self.assertTrue(_matches_any([".git/*"], ".git", ".git"))

    def test_trailing_star_excludes_deeper_paths(self):
        self.assertTrue(_matches_any([".git/*"], ".git/objects/x", "x"))

    def test_trailing_star_does_not_match_sibling(self):
        self.assertFalse(_matches_any([".git/*"], ".github/workflows", "workflows"))
        self.assertFalse(_matches_any([".git/*"], "src/.gitignore", ".gitignore"))

    def test_excluded_dir_is_pruned_not_walked(self):
        tmpd = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmpd, ".git", "objects"))
        with open(os.path.join(tmpd, ".git", "evil.md"), "w") as fh:
            fh.write("[x](https://example.com/)\n")
        with open(os.path.join(tmpd, "keep.md"), "w") as fh:
            fh.write("[y](https://example.com/)\n")
        found = collect_files(tmpd, ["*.md"], [])
        self.assertEqual([os.path.basename(p) for p in found], ["keep.md"])


class ArgValidationTest(unittest.TestCase):
    def test_invalid_exclude_url_regex_is_exit_2(self):
        tmpd = tempfile.mkdtemp()
        rc = main([tmpd, "--quiet", "--exclude-url", "([invalid"])
        self.assertEqual(rc, 2)

    def test_non_positive_timeout_is_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            parse_args(["--timeout", "0"])
        self.assertEqual(ctx.exception.code, 2)
        with self.assertRaises(SystemExit) as ctx:
            parse_args(["--timeout", "-5"])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_path_is_exit_2(self):
        rc = main([os.path.join(tempfile.mkdtemp(), "no-such-dir"), "--quiet"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
