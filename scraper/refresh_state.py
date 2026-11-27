"""Versioned publication sidecars, tied to the exact CSV/SQLite generation."""
import copy
from collections import defaultdict
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from .publication import digest, write_json

STATE = 'event-refresh-state.json'
SOURCES = 'fighter-source-times.json'
SIDECARS = (STATE, SOURCES)


def generation(hashes):
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def stamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Source/state timestamp requires timezone')
    return result


def load(root, rows):
    state = json.loads((root / STATE).read_text(encoding='utf-8'))
    sources = json.loads((root / SOURCES).read_text(encoding='utf-8'))
    hashes = {name: digest(root / name) for name in ('output.csv','ufc_fighters.db')}
    expected = generation(hashes)
    if any(d.get('schema_version') != 1 or d.get('generation') != expected for d in (state,sources)):
        raise ValueError('Refresh state/dataset generation mismatch; explicit full reconciliation required')
    if state.get('dataset_hashes') != hashes or set(sources.get('fighters',{})) != set(rows):
        raise ValueError('State dataset hashes or source roster mismatch')
    stamp(state['tracking_since'])
    if state.get('discovered_through'):
        stamp(state['discovered_through'])
    if not isinstance(state.get('events'), dict):
        raise ValueError('Invalid event state')
    for fid, item in sources['fighters'].items():
        profile = item.get('profile')
        if profile:
            if profile['url'] != rows[fid].url:
                raise ValueError('Per-fighter source identity mismatch')
            stamp(profile['fetched_at'])
    for eid, event in state['events'].items():
        if event['id'] != eid:
            raise ValueError('Event state identity mismatch')
        checks = event.get('checks',{})
        if set(checks) - {'initial','24h','48h'} or ('48h' in checks and '24h' not in checks) or ('24h' in checks and 'initial' not in checks):
            raise ValueError('Invalid follow-up sequence')
        for check in checks.values():
            stamp(check['checked_at'])
    return state, sources


def source_item(row, provenance):
    # Redirects can change the requested slug; select the final canonical URL.
    items = [(u,v) for u,v in provenance.items() if urlsplit(u).path == urlsplit(row.url).path]
    primary = next((dict(url=u, fetched_at=v['fetched_at']) for u,v in items if not urlsplit(u).query), None)
    return {'profile': primary, 'history': [dict(url=u, fetched_at=v['fetched_at']) for u,v in sorted(items) if urlsplit(u).query],
            'history_status': row.history_status}


def full_sidecars(root, stage, rows, report):
    if (root / STATE).exists() or (root / SOURCES).exists():
        from validate_export import validate
        old = validate(root/'output.csv',root/'ufc_fighters.db')
        state, _ = load(root,old)
        state = copy.deepcopy(state)
    else:
        state = {'schema_version':1, 'tracking_since':(stamp(report['started'])-timedelta(days=30)).isoformat(),
                 'discovered_through':None,'events':{}}
    by_path = defaultdict(dict)
    for url,item in report.get('fetch_provenance',{}).items():
        by_path[urlsplit(url).path][url] = item
    sources = {'schema_version':1, 'fighters':{fid:source_item(row,by_path[urlsplit(row.url).path]) for fid,row in rows.items()}}
    save(stage, rows, state, sources, report)


def save(stage, rows, state, sources, report):
    hashes = {name:digest(stage/name) for name in ('output.csv','ufc_fighters.db')}
    gen = generation(hashes)
    state.update(generation=gen,dataset_hashes=hashes)
    sources['generation'] = gen
    if set(sources['fighters']) != set(rows):
        raise ValueError('Missing fighter provenance entries')
    write_json(stage/STATE,state)
    write_json(stage/SOURCES,sources)
    report['sidecar_hashes'] = {name:digest(stage/name) for name in SIDECARS}
    report['generation'] = gen


def due(event, now):
    if event.get('status') != 'complete':
        return None
    checks = event.get('checks',{})
    if not checks.get('initial'):
        return 'initial'
    initial = stamp(checks['initial']['checked_at'])
    for label,hours in [('24h',24),('48h',48)]:
        if label not in checks:
            return label if now >= initial+timedelta(hours=hours) else None
    return None
