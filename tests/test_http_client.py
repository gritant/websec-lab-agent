"""Offline redirect regressions using Requests' real session/redirect handling."""

from email.message import Message
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

import requests
from requests.adapters import BaseAdapter

from tools.http_client import SafeHTTP, SafetyViolation


class QueueAdapter(BaseAdapter):
    """In-memory HTTP transport: never opens a socket or resolves a hostname."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def send(self, request, **kwargs):
        self.sent.append(request)
        if not self.responses:
            raise AssertionError("Unexpected HTTP request")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, headers, body = item
        response = requests.Response()
        response.status_code = status
        response.reason = "test response"
        response.headers.update(headers)
        response._content = body.encode("utf-8")
        response._content_consumed = True
        response.encoding = "utf-8"
        response.url = request.url
        response.request = request
        # Requests extracts cookies from the original HTTP response headers.
        message = Message()
        for key, value in headers.items():
            message[key] = value
        response.raw = SimpleNamespace(_original_response=SimpleNamespace(msg=message))
        return response

    def close(self):
        pass


def redirect(location, status=302, **headers):
    return status, {"Location": location, **headers}, "redirecting"


OK = (200, {"Content-Type": "text/plain"}, "done")


class SafeHTTPRedirectTests(unittest.TestCase):
    def client(self, responses, **kwargs):
        http = SafeHTTP("https://lab.example.test", ["example.test"],
                        interval=kwargs.pop("interval", 0), **kwargs)
        # Ignore any workstation proxy/netrc settings while retaining Session logic.
        http.session.trust_env = False
        adapter = QueueAdapter(responses)
        http.session.mount("http://", adapter)
        http.session.mount("https://", adapter)
        self.addCleanup(http.session.close)
        return http, adapter

    def test_initial_unlisted_host_never_reaches_transport(self):
        http, adapter = self.client([OK])
        with self.assertRaises(SafetyViolation):
            http.request("GET", "https://blocked.test/")
        self.assertEqual(adapter.sent, [])
        self.assertEqual(http._count, 0)
        self.assertEqual(http.traffic, [])

    def test_external_redirects_are_blocked_before_sending(self):
        for location in ("https://blocked.test/", "//blocked.test/",
                         "https://example.test.blocked.test/"):
            with self.subTest(location=location):
                http, adapter = self.client([redirect(location), OK])
                with self.assertRaises(SafetyViolation):
                    http.request("GET", "/start")
                self.assertEqual([r.url for r in adapter.sent],
                                 ["https://lab.example.test/start"])
                self.assertEqual(http._count, 1)
                self.assertEqual([t["status"] for t in http.traffic], [302])

    def test_non_http_redirects_are_blocked(self):
        for location in ("ftp://lab.example.test/file", "file:///tmp/test"):
            with self.subTest(location=location):
                http, adapter = self.client([redirect(location)])
                with self.assertRaises(SafetyViolation):
                    http.request("GET", "/start")
                self.assertEqual(len(adapter.sent), 1)

    def test_relative_redirect_chain_counts_and_records_every_hop(self):
        http, adapter = self.client([redirect("next"), redirect("/done"), OK])
        result = http.request("GET", "/folder/start")
        urls = ["https://lab.example.test/folder/start",
                "https://lab.example.test/folder/next", "https://lab.example.test/done"]
        self.assertEqual([r.url for r in adapter.sent], urls)
        self.assertEqual([t["url"] for t in http.traffic], urls)
        self.assertEqual([t["status"] for t in http.traffic], [302, 302, 200])
        self.assertEqual(http._count, 3)
        self.assertEqual(result, {"status": 200, "headers": OK[1], "body": "done"})

    def test_request_budget_stops_chain_before_extra_send(self):
        http, adapter = self.client([redirect("/two"), redirect("/three"), OK],
                                    max_requests=2)
        with self.assertRaises(SafetyViolation):
            http.request("GET", "/one")
        self.assertEqual(len(adapter.sent), 2)
        self.assertEqual(http._count, 2)
        self.assertEqual(len(http.traffic), 2)
        with self.assertRaises(SafetyViolation):
            http.request("GET", "/later")
        self.assertEqual(len(adapter.sent), 2)

    def test_each_redirect_observes_rate_limit(self):
        http, _ = self.client([redirect("/two"), redirect("/three"), OK], interval=0.5)
        with patch("tools.http_client.time.time", return_value=100), \
                patch("tools.http_client.time.sleep") as sleep:
            http.request("GET", "/one")
        self.assertEqual(sleep.call_args_list, [call(0.5), call(0.5)])

    def test_302_and_303_turn_post_into_bodyless_get(self):
        for status in (302, 303):
            with self.subTest(status=status):
                http, adapter = self.client([redirect("/done", status), OK])
                http.request("POST", "/login", data="field=value")
                self.assertEqual([r.method for r in adapter.sent], ["POST", "GET"])
                self.assertIsNone(adapter.sent[1].body)
                self.assertNotIn("Content-Length", adapter.sent[1].headers)
                self.assertNotIn("field=value", http.traffic[1]["request"])
                self.assertEqual([t["method"] for t in http.traffic], ["POST", "GET"])

    def test_307_and_308_preserve_post_body(self):
        for status in (307, 308):
            with self.subTest(status=status):
                http, adapter = self.client([redirect("/done", status), OK])
                http.request("POST", "/login", data="field=value")
                self.assertEqual([r.method for r in adapter.sent], ["POST", "POST"])
                self.assertEqual(adapter.sent[1].body, "field=value")
                self.assertIn("field=value", http.traffic[1]["request"])

    def test_redirect_cookie_is_carried_to_next_request(self):
        http, adapter = self.client([
            redirect("/done", **{"Set-Cookie": "session=fictional; Path=/"}), OK])
        http.request("GET", "/login")
        self.assertEqual(adapter.sent[1].headers.get("Cookie"), "session=fictional")

    def test_cross_host_redirect_strips_authorization(self):
        http, adapter = self.client([redirect("https://other.example.test/done"), OK])
        http.request("GET", "/start", headers={"Authorization": "Bearer fictional"})
        self.assertEqual(adapter.sent[0].headers["Authorization"], "Bearer fictional")
        self.assertNotIn("Authorization", adapter.sent[1].headers)

    def test_redirect_loop_respects_session_limit(self):
        http, adapter = self.client([redirect("/loop")] * 4)
        http.session.max_redirects = 2
        with self.assertRaises(requests.TooManyRedirects):
            http.request("GET", "/loop")
        self.assertEqual(len(adapter.sent), 3)
        self.assertEqual(http._count, 3)
        self.assertEqual(len(http.traffic), 3)

    def test_connection_failure_after_redirect_is_counted_and_recorded(self):
        http, adapter = self.client([redirect("/failed"), requests.ConnectionError("offline")])
        with self.assertRaises(requests.ConnectionError):
            http.request("GET", "/start")
        self.assertEqual(len(adapter.sent), 2)
        self.assertEqual(http._count, 2)
        self.assertEqual([t["status"] for t in http.traffic], [302, 0])
        self.assertEqual(http.traffic[-1]["url"], "https://lab.example.test/failed")
        self.assertIn("offline", http.traffic[-1]["response"])


if __name__ == "__main__":
    unittest.main()
