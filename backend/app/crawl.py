"""Fetch a business's public website and turn it into clean text.

Two jobs live here:

* `fetch` makes outbound HTTP requests to addresses that users supply. It
  resolves the host itself, refuses anything that is not a public address, and
  connects to the exact IP it checked, so a hostname cannot point at the Lambda
  runtime API, a metadata endpoint or a private network (SSRF), and cannot swap
  its DNS answer between the check and the connection.
* `crawl_site` reads the home page and the handful of linked pages most likely
  to describe the business, and returns their readable text.
"""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import urljoin, urlsplit, urlunsplit

from . import config

USER_AGENT = "GreetwellBot/1.0 (+website assistant builder; reads a site once at its owner's request)"
ALLOWED_PORTS = {80, 443, 8080, 8443}
_SSL = ssl.create_default_context()


class FetchError(Exception):
    """A failure whose message is safe and useful to show to the user."""


class Response:
    def __init__(self, url, status, headers, body):
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body

    def text(self):
        charset = "utf-8"
        match = re.search(r"charset=([\w\-]+)", self.headers.get("content-type", ""), re.I)
        if match:
            charset = match.group(1)
        else:
            meta = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", self.body[:4096], re.I)
            if meta:
                charset = meta.group(1).decode("ascii", "replace")
        try:
            return self.body.decode(charset, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout, context=_SSL)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = _SSL.wrap_socket(sock, server_hostname=self.host)


def normalize_url(raw):
    """Validate a user-supplied URL and return it in canonical form."""
    raw = (raw or "").strip()
    if not raw:
        raise FetchError("Enter your website address.")
    if len(raw) > 500:
        raise FetchError("That address is too long.")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", raw):
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise FetchError("Only http and https addresses are supported.")
    if not parts.hostname or "@" in parts.netloc:
        raise FetchError("That doesn't look like a website address.")
    try:
        port = parts.port
    except ValueError:
        raise FetchError("That doesn't look like a website address.")
    if port is not None and port not in ALLOWED_PORTS and not config.ALLOW_PRIVATE_FETCH:
        raise FetchError("That port isn't supported.")
    try:
        host = parts.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise FetchError("That doesn't look like a website address.")
    if "." not in host and not config.ALLOW_PRIVATE_FETCH:
        raise FetchError("That doesn't look like a website address.")
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def _resolve_public(host, port):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise FetchError("We couldn't find that website. Check the address and try again.")
    addresses = []
    for info in infos:
        ip = info[4][0].split("%")[0]
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        raise FetchError("We couldn't find that website. Check the address and try again.")
    if not config.ALLOW_PRIVATE_FETCH:
        for ip in addresses:
            if not ipaddress.ip_address(ip).is_global:
                raise FetchError("That address isn't on the public internet.")
    # Lambda has no IPv6 route by default, so prefer IPv4 when there is one.
    for ip in addresses:
        if ":" not in ip:
            return ip
    return addresses[0]


def _read_body(resp, max_bytes, deadline):
    chunks, size = [], 0
    while size <= max_bytes:
        if time.monotonic() > deadline:
            raise FetchError("That website took too long to respond.")
        chunk = resp.read(65536)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    data = b"".join(chunks)[:max_bytes]
    encoding = (resp.getheader("Content-Encoding") or "").lower()
    if encoding in ("gzip", "deflate"):
        wbits = 16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS
        try:
            data = zlib.decompressobj(wbits).decompress(data, max_bytes)
        except zlib.error:
            if encoding == "deflate":
                try:
                    data = zlib.decompressobj(-zlib.MAX_WBITS).decompress(data, max_bytes)
                except zlib.error:
                    raise FetchError("That website sent a response we couldn't read.")
            else:
                raise FetchError("That website sent a response we couldn't read.")
    return data


def fetch(url, *, method="GET", body=None, headers=None, max_bytes=1_500_000, timeout=8, max_redirects=4):
    """Make one guarded HTTP request, following redirects for GETs."""
    deadline = time.monotonic() + timeout * 2
    current = normalize_url(url)
    for _ in range(max_redirects + 1):
        parts = urlsplit(current)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        ip = _resolve_public(parts.hostname, port)
        cls = _PinnedHTTPSConnection if parts.scheme == "https" else _PinnedHTTPConnection
        conn = cls(parts.hostname, port, ip, timeout)
        request_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.5",
            "Accept-Encoding": "gzip",
            "Accept-Language": "en;q=0.9,*;q=0.5",
        }
        request_headers.update(headers or {})
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        try:
            conn.request(method, target, body=body, headers=request_headers)
            resp = conn.getresponse()
            location = resp.getheader("Location")
            if resp.status in (301, 302, 303, 307, 308) and location and method == "GET":
                current = normalize_url(urljoin(current, location))
                continue
            data = _read_body(resp, max_bytes, deadline)
            response_headers = {k.lower(): v for k, v in resp.getheaders()}
            return Response(current, resp.status, response_headers, data)
        except FetchError:
            raise
        except ssl.SSLError:
            raise FetchError("That website's security certificate couldn't be verified.")
        except (socket.timeout, TimeoutError):
            raise FetchError("That website took too long to respond.")
        except (OSError, http.client.HTTPException):
            raise FetchError("We couldn't connect to that website.")
        finally:
            conn.close()
    raise FetchError("That website redirected too many times.")


# --------------------------------------------------------------------------
# HTML to text

_SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "canvas", "select", "nav", "button"}
_BLOCK = {
    "p", "div", "section", "article", "main", "header", "footer", "aside", "br", "hr",
    "li", "ul", "ol", "dl", "dt", "dd", "table", "tr", "td", "th", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "form", "figure", "figcaption", "address", "pre",
}
_HEADINGS = {"h1", "h2", "h3"}
_VOID = {"br", "hr", "img", "input", "meta", "link", "source", "area", "base", "col", "embed", "track", "wbr"}
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta = {}
        self.links = []
        self.emails = []
        self.phones = []
        self.jsonld = []
        self._lines = []
        self._buf = []
        self._skip = 0
        self._in_title = False
        self._in_jsonld = False
        self._prefix = ""
        self._link = None

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._buf = []
        if text:
            self._lines.append(self._prefix + text)
        self._prefix = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and "ld+json" in (attrs.get("type") or ""):
            self._in_jsonld = True
        # Links are collected even inside skipped regions: the navigation menu
        # is dropped from the text but is the best map of the site.
        if tag == "a" and attrs.get("href"):
            href = attrs["href"].strip()
            if href.lower().startswith("mailto:"):
                self.emails.append(href[7:].split("?")[0].strip())
            elif href.lower().startswith("tel:"):
                self.phones.append(href[4:].strip())
            else:
                self._link = [href, []]
        if tag in _SKIP:
            self._skip += 1
            return
        # Only the document's own <title>; inline SVGs carry <title> elements too.
        if tag == "title" and not self._skip and not self.title:
            self._in_title = True
        elif tag == "meta":
            key = (attrs.get("name") or attrs.get("property") or "").lower()
            if key and attrs.get("content"):
                self.meta.setdefault(key, attrs["content"].strip())
        if self._skip:
            return
        if tag in _BLOCK:
            self._flush()
            if tag in _HEADINGS:
                self._prefix = "## "
            elif tag == "li":
                self._prefix = "- "

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_jsonld = False
        if tag == "a" and self._link:
            href, words = self._link
            self.links.append((href, re.sub(r"\s+", " ", "".join(words)).strip()))
            self._link = None
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "title":
            self._in_title = False
        if not self._skip and tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._in_jsonld:
            self.jsonld.append(data)
            return
        if self._in_title:
            self.title += data
            return
        if self._link:
            self._link[1].append(data)
        if self._skip:
            return
        self._buf.append(data)

    def lines(self):
        self._flush()
        out = []
        for line in self._lines:
            if not out or out[-1] != line:
                out.append(line)
        return out


def _jsonld_facts(blocks):
    """Pull the plain facts a business usually publishes as schema.org data."""
    facts = []

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        for key in ("name", "description", "telephone", "email", "priceRange", "openingHours"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                facts.append(f"{key}: {value.strip()}")
        address = node.get("address")
        if isinstance(address, dict):
            joined = ", ".join(
                str(address[k]) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")
                if isinstance(address.get(k), str)
            )
            if joined:
                facts.append(f"address: {joined}")
        for key in ("@graph", "mainEntity"):
            if key in node:
                visit(node[key])

    for raw in blocks:
        try:
            visit(json.loads(raw))
        except ValueError:
            continue
    seen, unique = set(), []
    for fact in facts:
        if fact not in seen:
            seen.add(fact)
            unique.append(fact)
    return unique[:12]


def extract(html, url=""):
    """Reduce an HTML document to its readable text, links and contact details."""
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # html.parser is tolerant, but whatever it managed to read is still useful.
        pass
    lines = parser.lines()
    description = parser.meta.get("description") or parser.meta.get("og:description") or ""
    facts = _jsonld_facts(parser.jsonld)
    text_emails = _EMAIL.findall("\n".join(lines))
    return {
        "url": url,
        "title": re.sub(r"\s+", " ", parser.title).strip() or parser.meta.get("og:title", ""),
        "description": description,
        "site_name": parser.meta.get("og:site_name", ""),
        "theme_color": parser.meta.get("theme-color", ""),
        "lines": lines,
        "facts": facts,
        "links": parser.links,
        # Addresses in running text are often examples, so trust mailto: links first.
        "emails": list(dict.fromkeys(parser.emails or text_emails))[:5],
        "phones": list(dict.fromkeys(parser.phones))[:5],
    }


# --------------------------------------------------------------------------
# Choosing which pages to read

_LINK_SCORES = [
    (5, ("pricing", "price", "plans", "rates", "fees", "cost")),
    (4, ("service", "product", "solution", "feature", "what-we-do", "offer", "menu", "treatments", "courses")),
    (4, ("about", "who-we-are", "our-story", "company", "team")),
    (4, ("faq", "help", "questions", "how-it-works")),
    (3, ("contact", "location", "hours", "book", "appointment", "quote", "demo")),
]
_SKIP_PATH = re.compile(
    r"(login|signin|sign-in|signup|sign-up|register|cart|checkout|account|wp-admin|wp-login|"
    r"privacy|terms|cookie|legal|sitemap|feed|rss|tag/|category/|author/)", re.I
)
_SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|svg|zip|mp4|mp3|docx?|xlsx?|pptx?|css|js|xml|ico)$", re.I)


def _same_site(host, other):
    return host.removeprefix("www.") == other.removeprefix("www.")


def pick_links(page, limit):
    """Rank a page's same-site links by how likely they are to describe the business."""
    base = urlsplit(page["url"])
    scored = {}
    for href, label in page["links"]:
        if href.startswith(("#", "javascript:", "data:")):
            continue
        absolute = urljoin(page["url"], href)
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            continue
        if not _same_site(base.hostname, parts.hostname):
            continue
        path = parts.path or "/"
        if path.rstrip("/") == base.path.rstrip("/"):
            continue
        if _SKIP_PATH.search(path) or _SKIP_EXT.search(path):
            continue
        clean = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
        haystack = (path + " " + label).lower()
        score = 1
        for points, words in _LINK_SCORES:
            if any(word in haystack for word in words):
                score = max(score, points)
        score -= 0.3 * max(0, path.strip("/").count("/"))
        if clean not in scored or scored[clean] < score:
            scored[clean] = score
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], len(kv[0])))
    return [url for url, _ in ranked[:limit]]


def _read_page(url):
    response = fetch(url)
    if response.status >= 400:
        raise FetchError(f"That website returned an error ({response.status}).")
    content_type = response.headers.get("content-type", "text/html").lower()
    if not any(kind in content_type for kind in ("html", "text/plain", "xml")):
        raise FetchError("That address isn't a web page.")
    return extract(response.text(), response.url)


def _robots(home_url):
    parts = urlsplit(home_url)
    rules = robotparser.RobotFileParser()
    try:
        response = fetch(urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", "")), timeout=5, max_bytes=200_000)
        if response.status == 200:
            rules.parse(response.text().splitlines())
            return rules
    except FetchError:
        pass
    return None


def crawl_site(url, max_pages=None, seconds=None):
    """Read a site's home page and its most informative linked pages."""
    max_pages = max_pages or config.CRAWL_MAX_PAGES
    deadline = time.monotonic() + (seconds or config.CRAWL_SECONDS)
    home_url = normalize_url(url)

    rules = _robots(home_url)
    allowed = (lambda u: rules.can_fetch(USER_AGENT, u)) if rules else (lambda u: True)
    if not allowed(home_url):
        raise FetchError(
            "That site's robots.txt asks automated readers to stay out. "
            "Describe your business in the text box instead."
        )

    home = _read_page(home_url)
    pages = [home]
    targets = [u for u in pick_links(home, max_pages * 2) if allowed(u)][: max_pages - 1]
    if targets:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_read_page, target) for target in targets]
            for future in futures:
                remaining = deadline - time.monotonic()
                try:
                    pages.append(future.result(timeout=max(0.1, remaining)))
                except Exception:
                    continue

    # Lines repeated on most pages are navigation and footer boilerplate. Keep
    # them once, on the first page where they appear.
    seen_urls, unique_pages = set(), []
    for page in pages:
        if page["url"] not in seen_urls:
            seen_urls.add(page["url"])
            unique_pages.append(page)
    counts = {}
    for page in unique_pages:
        for line in set(page["lines"]):
            counts[line] = counts.get(line, 0) + 1
    threshold = max(2, (len(unique_pages) + 1) // 2) if len(unique_pages) >= 3 else 99
    emitted, result = set(), []
    for page in unique_pages:
        kept = []
        for line in page["lines"]:
            if counts[line] >= threshold:
                if line in emitted:
                    continue
                emitted.add(line)
            kept.append(line)
        body = "\n".join(kept)
        if page["facts"]:
            body = "\n".join(page["facts"]) + "\n" + body
        if page["description"]:
            body = page["description"] + "\n" + body
        body = body[: config.CRAWL_PAGE_CHARS].strip()
        if len(body) >= 40:
            result.append({"url": page["url"], "title": page["title"][:160], "text": body})

    if sum(len(p["text"]) for p in result) < 200:
        raise FetchError(
            "We couldn't read enough text from that site. It may build its pages with "
            "JavaScript. Describe your business in the text box instead."
        )

    emails, phones = [], []
    for page in unique_pages:
        emails += page["emails"]
        phones += page["phones"]
    return {
        "pages": result,
        "site_name": home["site_name"] or "",
        "title": home["title"],
        "description": home["description"],
        "theme_color": home["theme_color"],
        "emails": list(dict.fromkeys(emails))[:3],
        "phones": list(dict.fromkeys(phones))[:3],
    }
