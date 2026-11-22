"""Bounded public-page retrieval. A successful HTTP response is not proof of data."""
import re
import time
import requests
from bs4 import BeautifulSoup

PROFILE = re.compile(r'https?://(?:www\.)?ufcstats\.com/fighter-details/([0-9a-f]{16})/?$', re.I)
TIMEOUT = (5, 20)

class SourceError(ValueError):
    pass


def profile_id(url):
    match = PROFILE.fullmatch(url)
    if not match:
        raise SourceError(f'Invalid UFCStats profile URL: {url}')
    return match[1].lower()


def fetch_html(url):
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            if 'text/html' not in response.headers.get('Content-Type', '').lower():
                raise SourceError(f'Expected HTML: {url}')
            if response.url != url:
                raise SourceError(f'Unexpected redirect: {url} -> {response.url}')
            checked_page(response.text, url)
            return response.text
        except requests.RequestException as error:
            status = error.response.status_code if error.response is not None else None
            transient = isinstance(error, (requests.Timeout, requests.ConnectionError)) or status in {429, 500, 502, 503, 504}
            if isinstance(error, requests.exceptions.SSLError):
                transient = False
            if attempt == 2 or not transient:
                raise SourceError(f'HTTP fetch failed for {url}: {error}') from error
            time.sleep(attempt + 1)


def checked_page(html, url):
    page = BeautifulSoup(html, 'html.parser')
    text = page.get_text(' ', strip=True).lower()
    if any(marker in text for marker in ('checking your browser', 'verify you are human', 'access denied', 'just a moment', 'captcha')):
        raise SourceError(f'Challenge/error page instead of UFCStats data: {url}')
    return page


def parse_index(html, url):
    page = checked_page(html, url)
    table = page.select_one('table.b-statistics__table')
    headers = {h.get_text(strip=True).lower() for h in page.select('th')}
    title = page.select_one('h2.b-content__title')
    if not table or not title or title.get_text(strip=True) != 'Fighters' or not {'first', 'last', 'w', 'l', 'd'}.issubset(headers):
        raise SourceError(f'Missing fighter index structure: {url}')
    urls = set()
    for row in table.select('tbody tr'):
        links = row.select('a[href*="fighter-details"]')
        if not links:
            # UFCStats includes blank spacer rows; populated unrecognized rows are errors.
            if row.get_text(strip=True) and row.get_text(' ', strip=True).lower() not in {'no fighters found', 'no fighters found.'}:
                raise SourceError(f'Unrecognized index row: {url}')
            continue
        for link in links:
            identity = profile_id(link['href'])
            urls.add(f'http://ufcstats.com/fighter-details/{identity}')
    # An authentic empty letter table is valid; aggregate empty discovery is not.
    return sorted(urls)
