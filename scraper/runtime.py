"""Response-archive resume and shared, bounded Requests execution.

No parsed rows are cached. Every reused body goes through today's parsers.
Only source-fetch timestamps, never cache-read timestamps, describe freshness.
"""

import gzip
import hashlib
import json
import math
import os
import tempfile
import threading
import time
import zlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .source import AGENT, SourceError, approved, checked_page, profile_url


class Cancelled(SourceError):
    pass


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.perf_counter()
        self.values = Counter()
        self.urls = Counter()
        self.latencies = []

    def add(self, key, value=1):
        with self.lock:
            self.values[key] += value

    def request(self, url):
        kind = "event" if urlsplit(url).path.startswith(("/events", "/event/")) else "directory" if urlsplit(url).path == "/athletes/all" else "history" if urlsplit(url).query else "profile"
        with self.lock:
            self.values["live_requests"] += 1
            self.values[kind + "_requests"] += 1
            self.urls[url] += 1
            self.values["inflight"] += 1
            self.values["peak_inflight"] = max(self.values["peak_inflight"], self.values["inflight"])

    def response(self, elapsed, status):
        with self.lock:
            self.values["inflight"] -= 1
            self.values["network_seconds"] += elapsed
            self.values["http_" + str(status)] += 1
            self.latencies.append(elapsed)

    def snapshot(self):
        with self.lock:
            result = dict(self.values)
            samples = sorted(self.latencies)
            result.update(
                elapsed_seconds=time.perf_counter() - self.started,
                duplicate_network_urls={u: n for u, n in self.urls.items() if n > 1},
                response_latency={
                    "count": len(samples),
                    "mean_seconds": sum(samples) / len(samples) if samples else None,
                    "p50_seconds": samples[len(samples) // 2] if samples else None,
                    "p95_seconds": samples[min(len(samples) - 1, int(len(samples) * .95))] if samples else None,
                },
            )
            return result


class Limiter:
    def __init__(self, pace, budget, metrics, cancel_file=None):
        if not math.isfinite(pace) or pace < 0 or budget <= 0:
            raise ValueError("Invalid request limits")
        self.pace, self.deadline = pace, time.monotonic() + budget
        self.metrics, self.cancel_file = metrics, cancel_file
        self.event = threading.Event()
        self.condition = threading.Condition()
        self.next_start = self.blocked_until = 0
        self.reason = "Cancelled"
        self.throttles = []

    def cancel(self, reason="Cancelled"):
        with self.condition:
            if not self.event.is_set():
                self.reason = reason
            self.event.set()
            self.condition.notify_all()

    def check(self):
        if self.cancel_file is not None and self.cancel_file.exists():
            self.cancel("Controlled cancellation requested")
        if self.event.is_set():
            raise Cancelled(self.reason)
        if time.monotonic() >= self.deadline:
            raise SourceError("Request budget exceeded")

    def acquire(self):
        started = time.perf_counter()
        try:
            with self.condition:
                while True:
                    self.check()
                    now = time.monotonic()
                    delay = max(self.next_start, self.blocked_until) - now
                    if now + max(0, delay) >= self.deadline:
                        raise SourceError("Request/backoff exceeds remaining budget")
                    if delay <= 0:
                        self.next_start = now + self.pace
                        return
                    self.condition.wait(min(delay, .1))
        finally:
            self.metrics.add("pacing_backoff_wait_seconds", time.perf_counter() - started)

    def defer(self, seconds):
        with self.condition:
            self.blocked_until = max(self.blocked_until, time.monotonic() + seconds)
            self.condition.notify_all()

    def throttled(self):
        with self.condition:
            now = time.monotonic()
            self.throttles = [t for t in self.throttles if t > now - 60] + [now]
            if len(self.throttles) >= 3:
                self.cancel("Sustained throttling: three HTTP 429 responses in 60 seconds")


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        name = stream.name
        stream.write(data)
    try:
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Archive:
    def __init__(self, output, resume=None, max_age_hours=24, refresh=False, refresh_urls=()):
        if not math.isfinite(max_age_hours) or max_age_hours <= 0:
            raise ValueError("Cache age must be positive hours")
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.roots = [self.output]
        self.max_age = max_age_hours * 3600
        self.refresh = refresh
        self.refresh_paths = {urlsplit(approved(u)).path for u in refresh_urls}
        if resume is not None:
            resume = Path(resume).resolve()
            root = resume if resume.name == "responses" else resume / "responses"
            if not root.is_dir():
                raise ValueError(f"No response archive at {root}")
            self.roots.append(root)
            manifest = root.parent / "resume-sources.json"
            if manifest.exists():
                obj = json.loads(manifest.read_text(encoding="utf-8"))
                self.roots.extend(Path(p) for p in obj["archives"])
        self.roots = list(dict.fromkeys(p.resolve() for p in self.roots))
        atomic_bytes(self.output.parent / "resume-sources.json", json.dumps(
            {"archives": [str(p) for p in self.roots], "max_age_hours": max_age_hours}, indent=2
        ).encode())

    def load(self, url, seen, metrics, not_before=None):
        start = time.perf_counter()
        key = hashlib.sha256(url.encode()).hexdigest()
        try:
            for root in self.roots:
                if url not in seen and (self.refresh or urlsplit(url).path in self.refresh_paths):
                    continue
                path = root / (key + ".json")
                if not path.exists():
                    continue
                try:
                    m = json.loads(path.read_text(encoding="utf-8-sig"))
                    if m["url"] != url or approved(m["url"]) != url:
                        raise ValueError("URL mismatch")
                    # Prior redirects/failures never establish a successful cache entry.
                    if m["status"] != 200 and not (root == self.output.resolve() and url in seen and m["status"] in {301,302,303,307,308}):
                        raise ValueError("Unsuccessful cached status")
                    fetched = datetime.fromisoformat(m["retrieved"])
                    if fetched.tzinfo is None:
                        raise ValueError("Missing source timezone")
                    age = (datetime.now(UTC) - fetched).total_seconds()
                    if age < -300 or age > self.max_age:
                        raise ValueError("Expired or future cache timestamp")
                    if not_before is not None and fetched < not_before:
                        raise ValueError("History predates the refreshed first page")
                    body = root / m["body"]
                    if body.resolve().parent != root.resolve():
                        raise ValueError("Invalid archive body path")
                    raw = gzip.decompress(body.read_bytes())
                    if hashlib.sha256(raw).hexdigest() != m["sha256"]:
                        raise ValueError("Body checksum mismatch")
                    if m["status"] == 200 and "text/html" not in (m.get("content_type") or "").lower():
                        raise ValueError("Unexpected cached MIME type")
                    headers = requests.structures.CaseInsensitiveDict(m.get("headers") or {})
                    if headers.get("Content-Type", m.get("content_type")) != m.get("content_type"):
                        raise ValueError("Inconsistent cached response headers")
                    raw.decode(m.get("encoding") or "utf-8")
                    return raw, m, str(path)
                except (OSError, ValueError, KeyError, TypeError, LookupError, EOFError, zlib.error):
                    metrics.add("cache_rejected")
            return None
        finally:
            metrics.add("cache_read_seconds", time.perf_counter() - start)

    def put(self, url, raw, metadata):
        key = hashlib.sha256(url.encode()).hexdigest()
        checksum = hashlib.sha256(raw).hexdigest()
        # Keep different versions of the same response; metadata points to latest.
        body = key + "-" + checksum[:16] + ".html.gz"
        atomic_bytes(self.output / body, gzip.compress(raw, compresslevel=1))
        metadata = dict(metadata, body=body, sha256=checksum)
        path = self.output / (key + ".json")
        atomic_bytes(path, (json.dumps(metadata, indent=2) + "\n").encode())
        return str(path)


class Runtime:
    def __init__(self, factory, stage, *, pace=1, budget=21600, workers=4,
                 resume=None, cache_age=24, refresh=False, refresh_urls=(), cancel_file=None):
        if not 1 <= workers <= 16:
            raise ValueError("Workers must be between 1 and 16")
        self.metrics = Metrics()
        self.stage = Path(stage)
        self.limiter = Limiter(pace, budget, self.metrics, cancel_file or self.stage / "cancel.request")
        self.archive = Archive(self.stage / "responses", resume, cache_age, refresh, refresh_urls)
        self.factory, self.pace, self.budget = factory, pace, budget
        self.workers = workers
        self.local = threading.local()
        self.mutex = threading.Lock()
        self.gates = defaultdict(threading.Lock)
        self.seen, self.clients, self.provenance = set(), [], {}
        self.failure = None
        self.inflight = threading.BoundedSemaphore(workers)

    def check(self):
        self.limiter.check()

    def begin_profile(self, url):
        self.local.profile_path = urlsplit(url).path
        self.local.resource_kind = "directory" if self.local.profile_path.rstrip("/") == "/athletes/all" else "profile"
        self.local.profile_fetches = []

    def mixed_history_cohort(self):
        fetches = getattr(self.local, "profile_fetches", [])
        if len(fetches) < 2 or not any(cached for _, cached in fetches):
            return None
        dates = [datetime.fromisoformat(stamp) for stamp, _ in fetches]
        if any(abs((b-a).total_seconds()) > 300 for a,b in zip(dates,dates[1:])):
            return {"oldest": min(dates).isoformat(), "newest": max(dates).isoformat()}

    def cancel(self, reason="Cancelled"):
        self.limiter.cancel(reason)

    def get(self, url):
        self.check()
        if not hasattr(self.local, "client"):
            client = self.factory(self.pace, self.budget)
            client.runtime, client.deadline = self, self.limiter.deadline
            self.local.client = client
            with self.mutex:
                self.clients.append(client)
        return self.local.client.get(url)

    def scope(self, raw, metadata):
        started = time.perf_counter()
        try:
            page = checked_page(raw.decode(metadata.get("encoding") or "utf-8", errors="replace"), metadata["url"])
            path = urlsplit(metadata["url"]).path
            if path == "/events":
                from .events import parse_listing
                parse_listing(page, metadata["url"])
            elif path.startswith("/event/"):
                from .events import parse_event
                parse_event(page, metadata["url"], datetime.now(UTC))
            elif path == "/athletes/all":
                if not page.select_one(".view-id-all_athletes .node--view-mode-all-athletes-result"):
                    raise SourceError("Missing cached directory structure")
            else:
                canonical = {profile_url(a["href"], metadata["url"]) for a in page.select("link[rel~=canonical][href]")}
                names = {tag.get_text(" ", strip=True) for tag in page.select(".hero-profile__name")}
                if canonical != {profile_url(metadata["url"])} or len(names) != 1 or not next(iter(names)) or not page.select_one(".c-bio__field,.hero-profile__division-body"):
                    raise SourceError("Missing cached profile identity/structure")
            return page
        finally:
            self.metrics.add("html_parse_seconds", time.perf_counter() - started)

    def response(self, client, url, timeout):
        self.check()
        with self.mutex:
            gate = self.gates[url]
        with gate:
            self.check()
            fetches = getattr(self.local, "profile_fetches", [])
            not_before = datetime.fromisoformat(fetches[0][0]) if fetches else None
            cached = self.archive.load(url, self.seen, self.metrics, not_before)
            if cached:
                raw, metadata, origin = cached
                try:
                    page = self.scope(raw, metadata) if metadata["status"] == 200 else None
                except SourceError:
                    self.metrics.add("cache_rejected_structure")
                else:
                    self.metrics.add("cache_hits")
                    if url in self.seen:
                        self.metrics.add("deduplicated_requests")
                    return self.prepared(raw, metadata, origin, page, True)
            with self.inflight:
                self.limiter.acquire()
                remaining = max(.01, self.limiter.deadline - time.monotonic())
                timeout = (min(timeout[0], remaining), min(timeout[1], remaining))
                self.metrics.request(url)
                start = time.perf_counter()
                status = "transport_error"
                try:
                    self.local.latest = {"url": url, "transport_error": "pending request"}
                    r = client.session.get(url, allow_redirects=False, timeout=timeout)
                    status = r.status_code
                    with r:
                        raw = r.content
                        metadata = {
                            "url": url, "status": status, "content_type": r.headers.get("Content-Type"),
                            "headers": dict(r.headers), "encoding": r.encoding or "utf-8",
                            "retrieved": datetime.now(UTC).isoformat(), "user_agent": AGENT,
                        }
                    if status in {408,429,500,502,503,504}:
                        retry = metadata["headers"].get("Retry-After", "")
                        try:
                            delay = float(retry) if retry.isdigit() else max(0, (parsedate_to_datetime(retry) - datetime.now(UTC)).total_seconds()) if retry else 1
                        except (ValueError, TypeError, OverflowError):
                            delay = 1
                        self.limiter.defer(delay)
                except requests.RequestException as exc:
                    self.local.latest = {"url": url, "transport_error": type(exc).__name__, "detail": str(exc)}
                    raise
                finally:
                    network_elapsed = time.perf_counter() - start
                    self.metrics.response(network_elapsed, status)
            metadata["request_elapsed_seconds"] = network_elapsed
            started = time.perf_counter()
            origin = self.archive.put(url, raw, metadata)
            self.metrics.add("evidence_write_seconds", time.perf_counter() - started)
            self.local.latest = dict(metadata, archive=origin)
            if status == 429:
                self.limiter.throttled()
            if status in {200,301,302,303,307,308}:
                with self.mutex:
                    self.seen.add(url)
            page = self.scope(raw, metadata) if status == 200 and "text/html" in (metadata["content_type"] or "").lower() else None
            return self.prepared(raw, metadata, origin, page, False)

    def prepared(self, raw, metadata, origin, page, cached):
        r = requests.Response()
        r._content, r._content_consumed = raw, True
        r.status_code, r.encoding = metadata["status"], metadata.get("encoding") or "utf-8"
        r.headers.update(metadata.get("headers") or {"Content-Type": metadata.get("content_type") or ""})
        r.fetched_at, r.parsed_page = metadata["retrieved"], page
        self.local.latest = dict(metadata, archive=origin)
        kind = getattr(self.local, "resource_kind", None)
        path = urlsplit(metadata["url"]).path
        same_resource = kind == "directory" and path.rstrip("/") == "/athletes/all" or kind == "profile" and path.startswith("/athlete/")
        if metadata["status"] == 200 and same_resource:
            self.local.profile_fetches.append((metadata["retrieved"], cached))
        with self.mutex:
            self.seen.add(metadata["url"])
            self.provenance[metadata["url"]] = {
                "fetched_at": metadata["retrieved"], "cached": cached, "archive": origin,
            }
        return r

    def fail(self, exc):
        with self.mutex:
            if self.failure is None and not isinstance(exc, Cancelled):
                self.failure = {"reason": str(exc), "response": getattr(self.local, "latest", None)}
        self.cancel(str(exc))

    def save_failure(self, folder):
        if self.failure is None:
            return None
        path = folder / "failure.json"
        atomic_bytes(path, json.dumps(self.failure, indent=2).encode())
        return str(path)

    def close(self):
        for client in self.clients:
            client.session.close()

    def source_dates(self):
        with self.mutex:
            dates = [p["fetched_at"] for p in self.provenance.values()]
        return {"oldest": min(dates, key=datetime.fromisoformat) if dates else None,
                "newest": max(dates, key=datetime.fromisoformat) if dates else None}

    def provenance_snapshot(self):
        with self.mutex:
            return dict(self.provenance)
