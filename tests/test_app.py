"""End-to-end and unit tests. Standard library only:

    python -m unittest discover -s tests -v
"""
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["APP_MODE"] = "local"
os.environ["LLM_BACKEND"] = "mock"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import bots, chat, config, crawl, handler, knowledge, services  # noqa: E402
from app.store import MemoryStore  # noqa: E402

HOME = """<!doctype html><html><head><title>Bright Smile Dental | Family dentist in Austin</title>
<meta name="description" content="Family and cosmetic dentistry in Austin, Texas.">
<meta name="theme-color" content="#0E7490">
<script type="application/ld+json">{"@type":"Dentist","name":"Bright Smile Dental","telephone":"+1 512 555 0100",
"address":{"streetAddress":"12 Oak St","addressLocality":"Austin"}}</script>
<style>.x{color:red}</style></head><body>
<nav><a href="/pricing">Pricing</a><a href="/about-us">About</a><a href="/login">Login</a>
<a href="https://other.example.org/">Partner</a><a href="/files/brochure.pdf">Brochure</a></nav>
<h1>Gentle dental care for the whole family</h1>
<p>We offer checkups, whitening and Invisalign. New patients are welcome.</p>
<ul><li>Open Monday to Friday, 8am to 6pm</li><li>Emergency appointments available</li></ul>
<script>var secret = "do not index";</script>
<footer>Call us or email <a href="mailto:hello@brightsmile.example?subject=Hi">hello@brightsmile.example</a></footer>
</body></html>"""

PRICING = """<html><head><title>Pricing | Bright Smile Dental</title></head><body>
<nav><a href="/">Home</a></nav><h1>Pricing</h1>
<p>A new patient exam and cleaning costs $99. Teeth whitening costs $350.</p>
<footer>Call us or email hello@brightsmile.example</footer></body></html>"""

ABOUT = """<html><head><title>About | Bright Smile Dental</title></head><body>
<h2>Our story</h2><p>Dr. Maria Lopez founded the practice in 2011. We speak English and Spanish.</p>
<footer>Call us or email hello@brightsmile.example</footer></body></html>"""


class _Site(BaseHTTPRequestHandler):
    pages = {"/": HOME, "/pricing": PRICING, "/about-us": ABOUT}

    def do_GET(self):
        if self.path == "/robots.txt":
            body, status = b"User-agent: *\nDisallow: /private\n", 200
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/pricing")
            self.end_headers()
            return
        elif self.path in self.pages:
            body, status = self.pages[self.path].encode(), 200
        else:
            body, status = b"missing", 404
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def call(method, path, body=None, key=None, ip="203.0.113.9", headers=None):
    event = {
        "rawPath": path,
        "headers": {"x-admin-key": key or "", **(headers or {})},
        "requestContext": {"http": {"method": method, "sourceIp": ip}},
        "body": json.dumps(body) if body is not None else "",
    }
    result = handler.handler(event)
    return result["statusCode"], (json.loads(result["body"]) if result["body"] else {})


class ExtractTests(unittest.TestCase):
    def test_text_links_and_contacts(self):
        page = crawl.extract(HOME, "https://brightsmile.example/")
        text = "\n".join(page["lines"])
        self.assertEqual(page["title"], "Bright Smile Dental | Family dentist in Austin")
        self.assertIn("## Gentle dental care for the whole family", text)
        self.assertIn("- Open Monday to Friday, 8am to 6pm", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("color:red", text)
        self.assertNotIn("Login", text)  # navigation is not content
        self.assertIn(("/pricing", "Pricing"), page["links"])  # but its links are kept
        self.assertEqual(page["emails"], ["hello@brightsmile.example"])
        self.assertEqual(page["theme_color"], "#0E7490")
        self.assertIn("telephone: +1 512 555 0100", page["facts"])
        self.assertIn("address: 12 Oak St, Austin", page["facts"])

    def test_pick_links_prefers_informative_same_site_pages(self):
        page = crawl.extract(HOME, "https://brightsmile.example/")
        links = crawl.pick_links(page, 5)
        self.assertEqual(links, ["https://brightsmile.example/pricing", "https://brightsmile.example/about-us"])


class SsrfTests(unittest.TestCase):
    def setUp(self):
        config.ALLOW_PRIVATE_FETCH = False

    def test_rejects_malformed_and_non_http(self):
        for bad in ("", "ftp://example.com", "file:///etc/passwd", "https://user:pw@example.com", "https://example.com:22", "localhost"):
            with self.assertRaises(crawl.FetchError, msg=bad):
                crawl.normalize_url(bad)

    def test_normalizes(self):
        self.assertEqual(crawl.normalize_url("Example.com"), "https://example.com/")
        self.assertEqual(crawl.normalize_url("http://example.com/a?b=1#frag"), "http://example.com/a?b=1")

    def test_refuses_non_public_addresses(self):
        for host in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "::1", "0.0.0.0"):
            with self.assertRaises(crawl.FetchError, msg=host):
                crawl._resolve_public(host, 80)

    def test_fetch_refuses_loopback(self):
        with self.assertRaises(crawl.FetchError):
            crawl.fetch("http://127.0.0.1:8080/")


class KnowledgeTests(unittest.TestCase):
    def test_chunks_and_retrieval(self):
        pages = [
            {"url": "u1", "title": "Home", "text": "We are a dental clinic.\n" + "filler line about nothing\n" * 80},
            {"url": "u2", "title": "Pricing", "text": "Teeth whitening costs $350.\n" + "other words here\n" * 80},
        ]
        chunks = knowledge.chunk_pages(pages, size=300)
        self.assertGreater(len(chunks), 6)
        self.assertTrue(all(len(c["text"]) <= 320 for c in chunks))
        picked = knowledge.select(chunks, "how much is whitening", budget=700)
        texts = " ".join(c["text"] for c in picked)
        self.assertIn("whitening costs $350", texts)
        self.assertIn("dental clinic", texts)  # the first chunk is always included
        self.assertLessEqual(knowledge.total_chars(picked), 700)

    def test_small_site_goes_in_whole(self):
        chunks = knowledge.chunk_pages([{"url": "", "title": "About", "text": "Short."}])
        self.assertTrue(knowledge.fits_whole(chunks))
        system = chat.build_system({"id": "b", "name": "Acme"}, chunks, "q", None)
        self.assertIn("<reference_material>", system[0]["text"])
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("<reference_material>", system[1]["text"])


class LeadTests(unittest.TestCase):
    def test_scoring(self):
        hot = chat.score_lead({"email": "a@b.co", "need": "x", "intent": "high"})
        warm = chat.score_lead({"email": "a@b.co", "need": "x", "intent": "medium"})
        cold = chat.score_lead({"email": "a@b.co", "need": "x", "intent": "low"})
        self.assertEqual((hot[1], warm[1], cold[1]), ("hot", "warm", "cold"))
        self.assertLessEqual(chat.score_lead({
            "email": "a@b.co", "phone": "5125550100", "name": "A", "company": "C", "need": "x",
            "intent": "high", "timeline": "now", "budget": "$1k",
        })[0], 100)

    def test_save_requires_valid_contact_and_merges(self):
        store = MemoryStore()
        bot = bots.new_bot("botA", "")
        store.put(bot)
        ok, note, _ = chat.save_lead(store, bot, "s" * 20, {"need": "quote", "intent": "high", "email": "not-an-email", "phone": "12"})
        self.assertFalse(ok)
        self.assertIn("email address or phone", note)
        ok, _, created = chat.save_lead(store, bot, "s" * 20, {"need": "quote", "intent": "medium", "email": "jo@example.com"})
        self.assertTrue(ok and created)
        ok, _, created = chat.save_lead(store, bot, "s" * 20, {"need": "quote for 3 sites", "intent": "high", "name": "Jo"})
        self.assertTrue(ok and not created)
        lead = store.get("BOT#botA", "LEAD#" + "s" * 20)
        self.assertEqual((lead["email"], lead["name"], lead["intent"], lead["label"]), ("jo@example.com", "Jo", "high", "hot"))
        self.assertEqual(bots.get(store, "botA")["leads"], 1)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.site = f"http://127.0.0.1:{cls.server.server_address[1]}/"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        config.ALLOW_PRIVATE_FETCH = True
        config.ORIGIN_SECRET = ""
        services._store = MemoryStore()

    def _create(self, **body):
        status, data = call("POST", "/api/bots", body)
        self.assertEqual(status, 202, data)
        for _ in range(100):
            status, bot = call("GET", f"/api/bots/{data['botId']}", key=data["adminKey"])
            if bot["status"] != "building":
                return data["botId"], data["adminKey"], bot
            time.sleep(0.05)
        self.fail("build did not finish")

    def test_full_flow(self):
        bot_id, key, bot = self._create(url=self.site)
        self.assertEqual(bot["status"], "ready", bot)
        self.assertEqual(bot["name"], "Bright Smile Dental")
        self.assertEqual(bot["color"], "#0e7490")
        self.assertEqual(len(bot["pages"]), 3)
        self.assertNotIn("keyHash", bot)

        status, public = call("GET", f"/api/bots/{bot_id}/public")
        self.assertEqual((status, public["status"]), (200, "ready"))
        self.assertNotIn("profile", public)

        session = "sess_" + "a" * 20
        status, answer = call("POST", "/api/chat", {"botId": bot_id, "sessionId": session, "message": "How much does teeth whitening cost?"})
        self.assertEqual(status, 200, answer)
        self.assertIn("$350", answer["reply"])
        self.assertFalse(answer["leadCaptured"])

        status, answer = call("POST", "/api/chat", {"botId": bot_id, "sessionId": session, "message": "Book me in, I'm jo@example.com"})
        self.assertTrue(answer["leadCaptured"], answer)

        status, leads = call("GET", f"/api/bots/{bot_id}/leads", key=key)
        self.assertEqual(len(leads["leads"]), 1)
        lead = leads["leads"][0]
        self.assertEqual((lead["email"], lead["label"], lead["status"]), ("jo@example.com", "hot", "new"))

        status, updated = call("PATCH", f"/api/bots/{bot_id}/leads/{lead['id']}", {"status": "contacted"}, key=key)
        self.assertEqual(updated["status"], "contacted")
        status, _ = call("PATCH", f"/api/bots/{bot_id}/leads/{lead['id']}", {"status": "nope"}, key=key)
        self.assertEqual(status, 400)

        status, sessions = call("GET", f"/api/bots/{bot_id}/sessions", key=key)
        self.assertEqual((sessions["sessions"][0]["count"], sessions["sessions"][0]["hasLead"]), (2, True))
        status, transcript = call("GET", f"/api/bots/{bot_id}/sessions/{session}", key=key)
        self.assertEqual(len(transcript["messages"]), 4)

        status, bot = call("GET", f"/api/bots/{bot_id}", key=key)
        self.assertEqual((bot["conversations"], bot["messages"], bot["leads"]), (1, 2, 1))

    def test_owner_endpoints_need_the_key(self):
        bot_id, key, _ = self._create(url=self.site)
        for method, path in [
            ("GET", f"/api/bots/{bot_id}"), ("PATCH", f"/api/bots/{bot_id}"), ("DELETE", f"/api/bots/{bot_id}"),
            ("GET", f"/api/bots/{bot_id}/leads"), ("GET", f"/api/bots/{bot_id}/sessions"),
            ("POST", f"/api/bots/{bot_id}/rebuild"),
        ]:
            self.assertEqual(call(method, path, {}, key="wrong")[0], 403, path)
            self.assertEqual(call(method, path, {})[0], 403, path)
        self.assertEqual(call("GET", "/api/bots/nonexistent1")[0], 404)

    def test_settings_survive_a_rebuild(self):
        bot_id, key, _ = self._create(url=self.site)
        status, bot = call("PATCH", f"/api/bots/{bot_id}", {"name": "Smile Bot", "color": "#112233", "notes": "Closed on 25 December."}, key=key)
        self.assertEqual((status, bot["name"], bot["customized"]), (200, "Smile Bot", ["color", "name", "notes"]))
        self.assertEqual(call("PATCH", f"/api/bots/{bot_id}", {"color": "red"}, key=key)[0], 400)
        self.assertEqual(call("PATCH", f"/api/bots/{bot_id}", {"webhookUrl": "http://example.com/hook"}, key=key)[0], 400)

        self.assertEqual(call("POST", f"/api/bots/{bot_id}/rebuild", key=key)[0], 202)
        for _ in range(100):
            _, bot = call("GET", f"/api/bots/{bot_id}", key=key)
            if not bot.get("rebuilding"):
                break
            time.sleep(0.05)
        self.assertEqual((bot["name"], bot["color"], bot["status"]), ("Smile Bot", "#112233", "ready"))
        self.assertEqual(bot["greeting"], "Hi! I'm the Bright Smile Dental assistant. How can I help?")

    def test_build_from_text_and_delete(self):
        text = "Acme Plumbing fixes leaks and installs water heaters across Denver. Call-outs cost $120. " * 2
        bot_id, key, bot = self._create(text=text)
        self.assertEqual(bot["status"], "ready")
        self.assertEqual(call("POST", f"/api/bots/{bot_id}/rebuild", key=key)[0], 400)
        self.assertEqual(call("DELETE", f"/api/bots/{bot_id}", key=key)[0], 200)
        self.assertEqual(call("GET", f"/api/bots/{bot_id}/public")[0], 404)
        self.assertIsNone(services.get_store().blob_get(f"kb/{bot_id}.json"))

    def test_unreachable_site_fails_cleanly(self):
        config.ALLOW_PRIVATE_FETCH = False
        _, _, bot = self._create(url="http://127.0.0.1:8080/")  # loopback is refused by the SSRF guard
        self.assertEqual(bot["status"], "failed")
        self.assertIn("public internet", bot["error"])
        status, answer = call("POST", "/api/chat", {"botId": bot["id"], "sessionId": "s" * 20, "message": "hi"})
        self.assertEqual(status, 409)

    def test_validation_and_limits(self):
        self.assertEqual(call("POST", "/api/bots", {"text": "too short"})[0], 400)
        self.assertEqual(call("POST", "/api/bots", {"url": "ftp://x.example"})[0], 400)
        self.assertEqual(call("POST", "/api/chat", {"botId": "abcd", "sessionId": "short", "message": "hi"})[0], 400)
        self.assertEqual(call("GET", "/api/nope")[0], 404)
        self.assertEqual(call("PUT", "/api/health")[0], 405)
        result = handler.handler({"rawPath": "/api/chat", "requestContext": {"http": {"method": "OPTIONS"}}})
        self.assertEqual(result["statusCode"], 204)

        for _ in range(config.BOTS_PER_IP_PER_DAY):
            self.assertEqual(call("POST", "/api/bots", {"url": self.site}, ip="198.51.100.7")[0], 202)
        self.assertEqual(call("POST", "/api/bots", {"url": self.site}, ip="198.51.100.7")[0], 429)
        self.assertEqual(call("POST", "/api/bots", {"url": self.site}, ip="198.51.100.8")[0], 202)

    def test_session_and_message_caps(self):
        bot_id, _, _ = self._create(url=self.site)
        body = {"botId": bot_id, "sessionId": "c" * 20, "message": "x" * (config.MAX_MESSAGE_CHARS + 1)}
        self.assertEqual(call("POST", "/api/chat", body)[0], 400)
        original = config.MSGS_PER_SESSION
        config.MSGS_PER_SESSION = 2
        try:
            body["message"] = "hello"
            self.assertEqual([call("POST", "/api/chat", body)[0] for _ in range(3)], [200, 200, 429])
        finally:
            config.MSGS_PER_SESSION = original

    def test_direct_calls_that_bypass_cloudfront_are_rejected(self):
        config.ORIGIN_SECRET = "s3cret"
        self.assertEqual(call("GET", "/api/health")[0], 403)
        self.assertEqual(call("GET", "/api/health", headers={"x-origin-verify": "s3cret"})[0], 200)

    def test_client_ip_comes_from_cloudfront(self):
        req = handler.Request({"headers": {"CloudFront-Viewer-Address": "198.51.100.20:4711"}, "requestContext": {"http": {"sourceIp": "10.1.1.1"}}})
        self.assertEqual(req.ip, "198.51.100.20")
        req = handler.Request({"headers": {"cloudfront-viewer-address": "[2001:db8::1]:4711"}, "requestContext": {"http": {}}})
        self.assertEqual(req.ip, "2001:db8::1")


class CrawlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.site = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        config.ALLOW_PRIVATE_FETCH = True

    def test_crawl_reads_linked_pages_and_drops_boilerplate(self):
        site = crawl.crawl_site(self.site + "/")
        self.assertEqual([p["url"].rsplit("/", 1)[1] for p in site["pages"]], ["", "pricing", "about-us"])
        footers = sum(p["text"].count("Call us or email") for p in site["pages"])
        self.assertEqual(footers, 1)  # repeated on every page, kept once
        self.assertIn("$350", site["pages"][1]["text"])
        self.assertEqual(site["emails"], ["hello@brightsmile.example"])

    def test_follows_redirects(self):
        response = crawl.fetch(self.site + "/redirect")
        self.assertTrue(response.url.endswith("/pricing"))
        self.assertIn("$99", response.text())


if __name__ == "__main__":
    unittest.main()
