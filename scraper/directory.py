from urllib.parse import urlsplit
import time

from .source import DIRECTORY, SourceError, approved, checked_page, profile_url


def next_page(view, url):
    def belongs_to_view(tag):
        owner = tag.find_parent(class_=lambda c: c and c.startswith("view-id-"))
        return owner is view

    links = [a for a in view.select("a[rel~=next]") if belongs_to_view(a)]
    if len(links) > 1 or (
        not links
        and any(
            belongs_to_view(pager)
            for pager in view.select("[data-drupal-views-infinite-scroll-pager]")
        )
    ):
        raise SourceError(f"Unrecognized pager at {url}")
    if links:
        target = approved(links[0]["href"], url)
        if urlsplit(target).path.rstrip("/") != urlsplit(url).path.rstrip("/"):
            raise SourceError(f"Pager changed resource at {url}: {target}")
        return target


def parse_directory(html, url):
    if urlsplit(approved(url)).path.rstrip("/") != "/athletes/all":
        raise SourceError(f"Unexpected directory destination {url}")
    page = checked_page(html, url)
    view = page.select_one(".view-id-all_athletes")
    cards = view.select(".node--view-mode-all-athletes-result") if view else []
    if not cards:
        raise SourceError(f"Missing directory result cards at {url}")
    urls = set()
    for card in cards:
        profiles = {
            profile_url(a["href"], url)
            for a in card.select(".c-listing-athlete-flipcard__action a[href]")
            if "/athlete/" in a["href"]
        }
        if len(profiles) != 1:
            raise SourceError(f"Missing or conflicting card identity at {url}")
        urls.update(profiles)
    return urls, next_page(view, url)


def discover(client, report, limit=1000):
    if hasattr(client, "begin_profile"):
        client.begin_profile(DIRECTORY)
    url = DIRECTORY
    pages, signatures, roster = set(), set(), set()
    while url:
        if url in pages or len(signatures) >= limit:
            raise SourceError(f"Directory loop or limit at {url}")
        html, final = client.get(url)
        try:
            parsing = time.perf_counter()
            links, following = parse_directory(html, final)
        except ValueError as exc:
            raise SourceError(
                f"Invalid directory response (HTTP 200) at {final}: {exc}"
            ) from exc
        finally:
            if hasattr(client, "metrics"):
                client.metrics.add("directory_parse_seconds", time.perf_counter() - parsing)
        signature = frozenset(links)
        if signature in signatures or final in pages:
            raise SourceError(f"Repeated directory page at {final}")
        pages.update((url, final))
        signatures.add(signature)
        roster.update(links)
        report.update(directory_pages=len(signatures), discovered=len(roster))
        if len(signatures) == 1 or len(signatures) % 25 == 0 or not following:
            print(
            f"Directory page {len(signatures)}: {len(roster)} unique profiles",
            flush=True,
            )
        url = following
    if hasattr(client, "mixed_history_cohort") and client.mixed_history_cohort():
        raise SourceError("Directory spans interrupted fetch cohorts; refresh /athletes/all explicitly")
    report["directory_complete"] = True
    return sorted(roster)
