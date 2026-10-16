"""Tests for the link checker against a local HTTP server (no public internet)."""

import http.server
import socketserver
import threading
import unittest

from linkrot.check import check_url, check_urls


class _Handler(http.server.BaseHTTPRequestHandler):
    def _respond(self, status, body=b""):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command == "GET":
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/ok":
            self._respond(200, b"ok")
        elif self.path == "/missing":
            self._respond(404, b"nope")
        elif self.path == "/head-rejected":
            self._respond(200, b"get works")
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        else:
            self._respond(404)

    def do_HEAD(self):
        if self.path == "/ok":
            self._respond(200)
        elif self.path == "/missing":
            self._respond(404)
        elif self.path == "/head-rejected":
            self._respond(405)  # HEAD rejected -> client must fall back to GET
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        else:
            self._respond(404)

    def log_message(self, *args):  # silence test output
        pass


class CheckerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def test_ok(self):
        result = check_url(self.base() + "/ok", timeout=5)
        self.assertTrue(result.ok)
        self.assertEqual(result.status, 200)

    def test_dead_404(self):
        result = check_url(self.base() + "/missing", timeout=5)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, 404)

    def test_head_fallback_to_get(self):
        # 405 on HEAD must not classify a live page as dead.
        result = check_url(self.base() + "/head-rejected", timeout=5)
        self.assertTrue(result.ok)
        self.assertEqual(result.status, 200)

    def test_redirect_followed(self):
        result = check_url(self.base() + "/redirect", timeout=5)
        self.assertTrue(result.ok)
        self.assertTrue(result.final_url.endswith("/ok"))

    def test_connection_refused_is_dead(self):
        # Port 1 is (practically) never open: ECONNREFUSED expected.
        result = check_url("http://127.0.0.1:1/", timeout=3)
        self.assertFalse(result.ok)
        self.assertIn("connection", result.detail.lower())

    def test_dns_error_is_dead(self):
        # .invalid is reserved by RFC 2606 and must not resolve.
        # The URL must be classified dead; the exact failure mode (DNS error
        # vs proxy-level rejection) depends on the machine's egress setup.
        result = check_url("https://nonexistent.invalid/", timeout=5)
        self.assertFalse(result.ok)
        self.assertIsNone(result.status)
        detail = result.detail.lower()
        self.assertTrue(
            any(word in detail for word in ("dns", "connection", "network", "proxy")),
            f"unexpected detail: {result.detail}",
        )

    def test_check_urls_concurrent(self):
        urls = [self.base() + p for p in ("/ok", "/missing", "/head-rejected")]
        results = check_urls(urls, concurrency=3, timeout=5)
        self.assertEqual(set(results), set(urls))
        self.assertTrue(results[urls[0]].ok)
        self.assertFalse(results[urls[1]].ok)
        self.assertTrue(results[urls[2]].ok)


if __name__ == "__main__":
    unittest.main()
