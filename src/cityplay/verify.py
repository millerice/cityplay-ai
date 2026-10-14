"""Read-only website checks. Name corroboration is not live operational proof."""
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
import ssl
import urllib.parse


def normalized(value):
    return " ".join(re.findall(r"[^\W_]+", value.lower().replace("'", "").replace("’", "")))


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def public_https_target(url, resolver=socket.getaddrinfo):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Unsafe website URL")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Unsafe website port")
    host = parsed.hostname.rstrip(".")
    if host == "localhost" or host.endswith((".local", ".localhost", ".internal")):
        raise ValueError("Private website host")
    answers = resolver(host, 443, type=socket.SOCK_STREAM)
    addresses = {item[4][0] for item in answers}
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("Non-public website address")
    path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    return host, sorted(addresses)[0], path


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout=5):
        super().__init__(host, timeout=timeout)
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def website_text(url):
    # Pin the validated public IP. DNS rebinding cannot change the connection target.
    for _ in range(3):
        host, address, path = public_https_target(url)
        connection = PinnedHTTPS(host, address)
        try:
            connection.request("GET", path, headers={"User-Agent": "CityPlayAI/0.2 (website identity check)", "Accept": "text/html"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Redirect without location")
                url = urllib.parse.urljoin("https://" + host + path, location)
                continue
            if response.status != 200 or "text/html" not in response.getheader("Content-Type", ""):
                raise ValueError("Website is not accessible HTML")
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Website exceeds size budget")
            parser = TextOnly()
            parser.feed(raw.decode("utf-8", errors="replace"))
            return "https://" + host + path, " ".join(parser.parts)
        finally:
            connection.close()
    raise ValueError("Website redirect limit")


@dataclass
class Verification:
    identity: str = "unverified"
    website: str | None = None
    hours: str = "unverified"
    budget: str = "unverified"
    visit_duration: str = "unverified"
    public_access: str = "unverified"

    def to_dict(self):
        return asdict(self)


class WebsiteVerifier:
    def __init__(self, fetch=website_text, max_checks=6):
        self.fetch, self.max_checks, self.calls = fetch, max_checks, 0
        self.cache = {}

    def check(self, entity):
        url = entity.get("properties", {}).get("website")
        evidence = Verification()
        if not isinstance(url, str) or not url:
            return evidence
        if url not in self.cache:
            if self.calls >= self.max_checks:
                return evidence
            self.calls += 1
            try:
                self.cache[url] = self.fetch(url)
            except (ValueError, OSError, http.client.HTTPException):
                self.cache[url] = None
        page = self.cache[url]
        if page is None:
            evidence.identity = "website_unavailable"
            return evidence
        final_url, content = page
        evidence.website = final_url
        # Full name, optionally excluding the geographic suffix. No fuzzy LLM verification.
        name = re.sub(r"\s+NYC$", "", entity.get("name", ""), flags=re.I)
        needle, haystack = normalized(name), normalized(content)
        evidence.identity = "website_name_corroborated" if len(needle) >= 4 and needle in haystack else "website_name_not_matched"
        # Even a name match does not verify this branch, prices, access, hours or events.
        return evidence
