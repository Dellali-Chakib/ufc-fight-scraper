"""Pure parsers for official UFC listings and finalized fight cards.

A date or membership in the past tab is not completion evidence. Every active
bout must have two linked athletes and a consistent explicit result pair.
"""
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .fighter_stats import is_ufc_event
from .source import SourceError, approved, checked_page, profile_url

LISTING = 'https://www.ufc.com/events'
RESULTS = {'win': 'win', 'loss': 'loss', 'draw': 'draw', 'nc': 'no contest',
           'no contest': 'no contest', 'no-contest': 'no contest'}


def event_url(url, base=LISTING):
    p = urlsplit(approved(url, base))
    if not re.fullmatch(r'/event/[A-Za-z0-9_-]+', p.path) or p.query:
        raise SourceError(f'Invalid event URL: {url}')
    return 'https://www.ufc.com' + p.path


def page(html, url):
    # Runtime already provides a parsed DOM; standalone parsers also reject challenges.
    return checked_page(html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, 'html.parser'), url)


def parse_listing(html, url=LISTING):
    p = page(html, url)
    view = p.select_one('.view-id-events_upcoming_past.view-display-id-past')
    if view is None:
        raise SourceError('Missing official past-event listing structure')
    events = {}
    for card in view.select('article.c-card-event--result'):
        a = card.select_one('.c-card-event--result__headline a[href]')
        stamp = card.select_one('[data-main-card-timestamp]')
        if a is None or stamp is None:
            raise SourceError('Incomplete event listing card')
        target = event_url(a['href'], url)
        if not is_ufc_event(urlsplit(target).path):
            # Only explicitly identified other competitions may be excluded.
            if re.match(r'/event/(?:road-(?:to-)?ufc-|dana-whites-contender-series-|dwcs-|ufc-bjj-|power-slap-|pride-|strikeforce-|wec-)', urlsplit(target).path, re.IGNORECASE):
                continue
            raise SourceError(f'Unclassified official event type: {target}')
        try:
            start = datetime.fromtimestamp(int(stamp['data-main-card-timestamp']), UTC)
        except (ValueError, OverflowError, OSError) as exc:
            raise SourceError('Invalid event listing timestamp') from exc
        item = {'id': target, 'url': target, 'starts_at': start.isoformat(),
                'title': a.get_text(' ', strip=True)}
        if target in events and events[target] != item:
            raise SourceError('Conflicting duplicate listed event')
        events[target] = item
    if not events:
        raise SourceError('Empty or unrecognized past-event listing')
    times = [e['starts_at'] for e in events.values()]
    if times != sorted(times, reverse=True):
        raise SourceError('Official past-event listing is not chronological')
    following = {approved(a['href'], url) for a in view.select('.pager a[rel~=next][href]')}
    if len(following) > 1:
        raise SourceError('Ambiguous event listing pagination')
    nxt = next(iter(following), None)
    if nxt:
        pnext = urlsplit(nxt)
        if pnext.path != '/events' or not re.fullmatch(r'page=\d+', pnext.query):
            raise SourceError('Unexpected event listing pagination URL')
    return sorted(events.values(), key=lambda e: (e['starts_at'], e['id']), reverse=True), nxt


def parse_event(html, url, now):
    p = page(html, url)
    canonical = {event_url(a['href'], url) for a in p.select('link[rel~=canonical][href]')}
    if len(canonical) != 1 or not p.select_one('.c-hero h1'):
        raise SourceError('Missing event canonical identity/hero')
    identity = next(iter(canonical))
    if identity != event_url(url) or not is_ufc_event(urlsplit(identity).path):
        raise SourceError('Unexpected event identity/type')
    stamps = {n['data-timestamp'] for n in p.select('.c-hero__headline-suffix[data-timestamp]')}
    if len(stamps) != 1:
        raise SourceError('Missing/ambiguous event start time')
    try:
        start = datetime.fromtimestamp(int(next(iter(stamps))), UTC)
    except (ValueError, OverflowError, OSError) as exc:
        raise SourceError('Invalid event start time') from exc
    cards = p.select('.c-listing-fight[data-fmid]')
    if not cards:
        raise SourceError('Missing event fight card structure')
    bouts, participants = {}, set()
    for card in cards:
        bid = card['data-fmid']
        if not bid.isdigit():
            raise SourceError('Invalid bout identity')
        status = (card.get('data-status') or '').casefold().strip()
        canceled = status in {'cancelled', 'canceled'} or bool(card.select_one(
            '.c-listing-fight__cancelled,.c-listing-fight__canceled'))
        athletes, outcomes = [], []
        for color in ('red', 'blue'):
            corner = card.select_one('.c-listing-fight__corner--' + color)
            links = {profile_url(a['href'], identity) for a in corner.select('a[href*="/athlete/"]')} if corner else set()
            if not canceled and len(links) != 1:
                raise SourceError(f'Missing/ambiguous athlete link in bout {bid}')
            athletes.append(next(iter(links)) if len(links) == 1 else None)
            labels = {RESULTS.get(n.get_text(' ', strip=True).casefold())
                      for n in corner.select('[class*=c-listing-fight__outcome--]')} if corner else set()
            labels.discard(None)
            if len(labels) > 1:
                raise SourceError(f'Conflicting results in bout {bid}')
            outcomes.append(next(iter(labels), None))
        pair = tuple(outcomes)
        completed = pair in {('win','loss'), ('loss','win'), ('draw','draw'), ('no contest','no contest')}
        if status and status not in {'cancelled','canceled','completed','final','upcoming','scheduled','live'}:
            raise SourceError(f'Unknown bout status {status!r}')
        if not canceled and len(set(athletes)) != 2:
            raise SourceError(f'Duplicate athlete in bout {bid}')
        bout = {'id': bid, 'status': 'canceled' if canceled else 'complete' if completed else 'pending',
                'athletes': athletes, 'outcomes': outcomes}
        if bid in bouts and bouts[bid] != bout:
            raise SourceError('Conflicting duplicate bout')
        bouts[bid] = bout
        if completed and not canceled:
            participants.update(athletes)
    complete = bool(participants) and all(b['status'] in {'complete','canceled'} for b in bouts.values())
    if complete and start > now:
        raise SourceError('Future event has contradictory finalized results')
    return {'id': identity, 'url': identity, 'starts_at': start.isoformat(),
            'title': p.select_one('.c-hero h1').get_text(' ', strip=True),
            'status': 'complete' if complete else 'pending', 'bouts': list(bouts.values()),
            'participants': sorted(participants)}


def discover_events(client, since, now, limit=100):
    """Walk all listing pages covering the durable outage boundary, or fail.

    A seven-day overlap is selected by the caller. Pending events are separately
    retried even after they disappear from the listing overlap.
    """
    url, seen, signatures, events = LISTING, set(), set(), {}
    previous_oldest = None
    for _ in range(limit):
        if url in seen:
            raise SourceError('Event listing pagination loop')
        seen.add(url)
        html, final = client.get(url)
        items, following = parse_listing(html, final)
        signature = tuple(i['id'] for i in items)
        if signature in signatures:
            raise SourceError('Repeated event listing page')
        signatures.add(signature)
        oldest = min(datetime.fromisoformat(e['starts_at']) for e in items)
        newest = max(datetime.fromisoformat(e['starts_at']) for e in items)
        if previous_oldest and newest > previous_oldest:
            raise SourceError('Event listing order changed; catch-up boundary unproven')
        previous_oldest = oldest
        for e in items:
            if datetime.fromisoformat(e['starts_at']) >= since:
                if e['id'] in events and events[e['id']] != e:
                    raise SourceError('Conflicting event across listing pages')
                events[e['id']] = e
        if not following or oldest < since:
            return events
        url = following
    raise SourceError('Event listing limit reached before catch-up boundary')
