"""Serial, paced public HTTPS access. Parsers never perform IO."""

import math
import hashlib
import json
import gzip
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, SoupStrainer

DIRECTORY = "https://www.ufc.com/athletes/all"
AGENT = (
    "CS571-FighterExplorer/2.0 (+https://github.com/Dellali-Chakib/ufc-fight-scraper)"
)


class SourceError(ValueError):
    pass


def approved(url, base=DIRECTORY):
    parts = urlsplit(urljoin(base, url))
    if parts.scheme != "https" or parts.netloc.lower() not in {
        "ufc.com",
        "www.ufc.com",
    }:
        raise SourceError(f"Unapproved UFC URL {url!r} on {base}")
    return urlunsplit(("https", parts.netloc.lower(), parts.path, parts.query, ""))


def profile_url(url, base=DIRECTORY):
    parts = urlsplit(approved(url, base))
    path = unquote(parts.path.rstrip("/"))
    if not re.fullmatch(r"/athlete/[\w.-]+", path) or path.rsplit("/", 1)[-1] in {
        ".",
        "..",
    }:
        raise SourceError(f"Invalid athlete URL {url}")
    return "https://www.ufc.com" + parts.path.rstrip("/")


class SourceElements(SoupStrainer):
    """Build the source components we read, without site navigation DOMs.

    Keep heading exclusion ancestors and complete component subtrees so pager
    ownership, SVG percentages, and challenge detection retain their meaning.
    """

    def allow_tag_creation(self, nsprefix, name, attrs):
        attrs = attrs or {}
        classes = attrs.get("class") or ""
        classes = classes.split() if isinstance(classes, str) else classes
        rel = attrs.get("rel") or ""
        rel = rel.split() if isinstance(rel, str) else rel
        return (
            name in {"title", "h1", "footer", "aside", "svg"}
            or name == "link" and "canonical" in rel
            or name == "script" and (
                attrs.get("type") == "application/ld+json"
                or attrs.get("data-drupal-selector") == "drupal-settings-json"
            )
            or attrs.get("id") == "athlete-record"
            or any(c.startswith(("hero-profile", "c-bio", "c-stat-compare",
                                  "overlap-athlete-content", "view-id-all_athletes",
                                  "view-id-events_upcoming_past", "c-listing-fight", "c-hero"))
                   for c in classes)
        )


def checked_page(html, url):
    page = html if isinstance(html, BeautifulSoup) else BeautifulSoup(
        html, "html.parser", parse_only=SourceElements()
    )
    heading = " ".join(
        t.get_text(" ", strip=True)
        for t in page.select("title,h1")
        if not t.find_parent(["footer", "svg", "aside"])
    )
    if re.search(
        r"access denied|just a moment|checking your browser|verify you are human|captcha|403 forbidden|page not found",
        heading,
        re.IGNORECASE,
    ):
        raise SourceError(f"Challenge/error HTML at {url}: {heading[:160]}")
    return page


class Client:
    def __init__(self, pace=0.5, budget=18000, attempts=3):
        if (
            not math.isfinite(pace)
            or not math.isfinite(budget)
            or pace < 0
            or budget <= 0
            or attempts < 1
        ):
            raise ValueError("Invalid request limits")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = AGENT
        self.pace, self.deadline, self.attempts = (
            pace,
            time.monotonic() + budget,
            attempts,
        )
        self.next_request = 0
        self.last_response = None
        self.last_body = None
        self.evidence_dir = None
        self.runtime = None

    def save_failure(self, folder):
        """Preserve the last response bytes, without re-requesting a failed page."""
        if self.last_response is None:
            return None
        folder.mkdir(exist_ok=True)
        metadata = dict(self.last_response)
        if self.last_body is not None:
            body = folder / "response.html"
            body.write_bytes(self.last_body)
            metadata.update(body=body.name, sha256=hashlib.sha256(self.last_body).hexdigest())
        (folder / "response.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        return str(folder / "response.json")

    def pause(self, delay, url):
        if time.monotonic() + delay >= self.deadline:
            raise SourceError(f"Request budget exceeded at {url}")
        time.sleep(max(0, delay))

    def get(self, url):
        seen = set()
        url = approved(url)
        for _ in range(6):
            if url in seen:
                raise SourceError(f"Redirect loop at {url}")
            seen.add(url)
            for attempt in range(self.attempts):
                if self.runtime is None:
                    self.pause(max(0, self.next_request - time.monotonic()), url)
                    self.next_request = time.monotonic() + self.pace
                else:
                    self.runtime.check()
                delay = 2**attempt
                remaining = max(0.01, self.deadline - time.monotonic())
                try:
                    timeout = (min(5, remaining), min(20, remaining))
                    response = self.session.get(url, allow_redirects=False, timeout=timeout) if self.runtime is None else self.runtime.response(self, url, timeout)
                    with response as r:
                        self.last_body = r.content
                        self.last_response = {
                            "url": url, "status": r.status_code,
                            "content_type": r.headers.get("Content-Type"),
                            "encoding": r.encoding, "user_agent": AGENT,
                            "retrieved": getattr(r, "fetched_at", datetime.now(UTC).isoformat()),
                        }
                        if self.evidence_dir is not None:
                            self.evidence_dir.mkdir(exist_ok=True)
                            key = hashlib.sha256(url.encode()).hexdigest()
                            body = self.evidence_dir / (key + ".html.gz")
                            body.write_bytes(gzip.compress(r.content))
                            metadata = dict(self.last_response, body=body.name,
                                            sha256=hashlib.sha256(r.content).hexdigest())
                            (self.evidence_dir / (key + ".json")).write_text(
                                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
                            )
                        if r.status_code in {301, 302, 303, 307, 308} and r.headers.get(
                            "Location"
                        ):
                            url = approved(r.headers["Location"], url)
                            break
                        if (
                            r.status_code == 200
                            and "text/html" in r.headers.get("Content-Type", "").lower()
                        ):
                            return (r.parsed_page if self.runtime is not None else r.text), url
                        reason = (
                            f"HTTP {r.status_code} {r.headers.get('Content-Type', '')}"
                        )
                        if r.status_code not in {408, 429, 500, 502, 503, 504}:
                            if self.runtime is not None and r.status_code in {401, 403}:
                                self.runtime.cancel(f"Access denied: HTTP {r.status_code} at {url}")
                            raise SourceError(f"{url}: {reason}")
                        retry = r.headers.get("Retry-After", "")
                        if retry.isdigit():
                            delay = int(retry)
                        elif retry:
                            delay = max(
                                0,
                                (
                                    parsedate_to_datetime(retry) - datetime.now(UTC)
                                ).total_seconds(),
                            )
                except requests.exceptions.SSLError as exc:
                    self.last_body = None
                    self.last_response = {
                        "url": url, "transport_error": type(exc).__name__, "detail": str(exc)
                    }
                    raise SourceError(f"TLS error at {url}") from exc
                except (requests.Timeout, requests.ConnectionError) as exc:
                    self.last_body = None
                    self.last_response = {
                        "url": url, "transport_error": type(exc).__name__, "detail": str(exc)
                    }
                    reason = type(exc).__name__
                if attempt + 1 == self.attempts:
                    raise SourceError(f"{url}: {reason}")
                if self.runtime is None:
                    self.pause(delay, url)
                else:
                    self.runtime.limiter.defer(delay)
        raise SourceError(f"Redirect limit at {url}")
