"""Fresh participant checks merged into an immutable, complete roster candidate."""
import copy
import csv
import json
import tempfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from validate_export import changes, coverage, guard, validate
from .contract import Fighter, HEADERS, VERSION
from .database import build, reader
from .events import discover_events, parse_event
from .identity import previous_registry, reconcile
from .publication import FILES, baseline, digest, locked, recover, replace, write_json
from .refresh_state import (SIDECARS, STATE, SOURCES, due, load, save, source_item, stamp)
from .runtime import Runtime
from .source import Client, SourceError
from .stat_scraper import ALIASES, collect_profiles, initial, now


def validate_merge(old, new, target_ids):
    if set(old) - set(new):
        raise ValueError('Event refresh would drop existing fighters')
    if set(new)-set(old)-set(target_ids):
        raise ValueError('Unverified newcomer outside target set')
    for fid in set(old)-set(target_ids):
        if old[fid] != new[fid]:
            raise ValueError(f'Nonparticipant changed: {fid}')
    guard(old, new)


def validate_routes(root, stage):
    with closing(reader(root/'ufc_fighters.db')) as db:
        before = dict(db.execute('SELECT fighter_id,id FROM fighters'))
    with closing(reader(stage/'ufc_fighters.db')) as db:
        after = dict(db.execute('SELECT fighter_id,id FROM fighters'))
    if any(after.get(fid) != numeric_id for fid,numeric_id in before.items()):
        raise ValueError('Existing numeric API identity changed')


def evidence(client, url):
    item = client.provenance_snapshot().get(url)
    if not item or item['cached']:
        raise SourceError(f'Missing fresh source evidence: {url}')
    metadata = json.loads(Path(item['archive']).read_text(encoding='utf-8'))
    return {'url':url,'fetched_at':item['fetched_at'],'sha256':metadata['sha256'],
            'status':metadata['status']}


def candidate(root, stage, client, report, current, max_events=3, listing_limit=100):
    old = validate(root/'output.csv',root/'ufc_fighters.db')
    state,sources = load(root,old)
    state,sources = copy.deepcopy(state),copy.deepcopy(sources)
    if any(not p.get('profile') for p in sources['fighters'].values()):
        raise ValueError('Baseline lacks per-fighter fetch times; rebuild explicitly')
    original_events = copy.deepcopy(state['events'])
    floor = max(stamp(state['tracking_since']),
                stamp(state['discovered_through'])-timedelta(days=7) if state.get('discovered_through') else stamp(state['tracking_since']))
    if floor > current:
        raise ValueError('Discovery state is in the future')
    listed = discover_events(client,floor,current,listing_limit)
    # Retry previously pending events even after they leave the listing window.
    urls = set(listed) | {eid for eid,e in state['events'].items() if e['status']!='complete' or due(e,current)}
    for url in sorted(urls):
        prior = state['events'].get(url)
        if prior and prior['status']=='complete' and not due(prior,current):
            continue
        html,final = client.get(url)
        event = parse_event(html,final,current)
        canonical_prior = state['events'].get(event['id'])
        if canonical_prior is not None and prior is not None and canonical_prior != prior:
            raise SourceError('Conflicting canonical event aliases in durable state')
        prior = canonical_prior or prior
        if url != event['id']:
            state['events'].pop(url, None)
        event['checks'] = copy.deepcopy(prior.get('checks',{})) if prior else {}
        if prior and prior.get('bouts') != event['bouts']:
            # Corrected participants/results invalidate prior checks, not athlete identity.
            event['checks'] = {}
            event['previous_results'] = {'bouts':prior['bouts'],'checks':prior.get('checks',{})}
        if not prior or event['status'] != prior['status'] or event['bouts'] != prior['bouts'] or due(event,current):
            event['results_evidence'] = evidence(client,final)
        else:
            event['results_evidence'] = prior['results_evidence']
        state['events'][event['id']] = event
    work = sorted(((eid,due(e,current)) for eid,e in state['events'].items() if due(e,current)),
                  key=lambda t:(state['events'][t[0]]['starts_at'],t[0]))[:max_events]
    urls = sorted({u for eid,_ in work for u in state['events'][eid]['participants']})
    report.update(discovered=len(urls),directory_complete=True,directory_pages=0)
    profiles = collect_profiles(client,urls,current.date(),stage,report) if urls else []
    registry = previous_registry(root)
    # Never match a same-name replacement without corroborating identity evidence.
    mapping = {}
    reconcile(profiles,registry,json.loads(ALIASES.read_text(encoding='utf-8')),mapping)
    if mapping['ambiguous']:
        raise ValueError(f'Ambiguous event participant mapping: {mapping["ambiguous"]}')
    new = dict(old)
    targets = []
    provenance = client.provenance_snapshot()
    for raw in profiles:
        row = Fighter.model_validate(raw)
        src = source_item(row,provenance)
        if not src['profile'] or stamp(src['profile']['fetched_at']) < stamp(report['started']):
            raise SourceError(f'Participant was not freshly checked: {row.url}')
        targets.append(row.fighter_id)
        new[row.fighter_id] = row
        sources['fighters'][row.fighter_id] = src
    fetched_by_url = {r['requested_url']:new[next(p['fighter_id'] for p in profiles if p['url']==r['url'])]
                      for r in json.loads((stage/'collected-profiles.json').read_text(encoding='utf-8'))} if urls else {}
    # Requested event links may redirect. Every requested participant must resolve;
    # two links resolving to one source identity is an error, never a silent skip.
    if len(set(targets)) != len(urls) or set(fetched_by_url) != set(urls):
        raise SourceError('Missing or duplicate event participant resolution')
    for eid,label in work:
        event = state['events'][eid]
        event['participant_identities'] = {u:{'fighter_id':fetched_by_url[u].fighter_id,'source_id':fetched_by_url[u].source_id,
                                             'canonical_url':fetched_by_url[u].url} for u in event['participants']}
        event['checks'][label] = {'checked_at':now(),
            'profiles':{u:sources['fighters'][fetched_by_url[u].fighter_id]['profile'] for u in event['participants']},
            'unchanged_fighters':sorted(fetched_by_url[u].fighter_id for u in event['participants']
                                       if old.get(fetched_by_url[u].fighter_id)==fetched_by_url[u]),
            'upstream_incorporation':'unverified; a fresh response or unchanged statistics does not prove event incorporation',
            'results_evidence':event['results_evidence']}
    validate_merge(old,new,targets)
    report.update(target_ids=sorted(targets),work=[{'event':eid,'check':label} for eid,label in work],migration=mapping,
                  pending={eid:('awaiting finalized results' if e['status']!='complete' else
                                [s for s in ('initial','24h','48h') if s not in e['checks']])
                           for eid,e in state['events'].items() if e['status']!='complete' or len(e['checks'])<3})
    # Rechecking an unchanged pending card or an empty daily window makes no heartbeat commit.
    if not work and state['events']==original_events:
        report.update(reason='no work',published=False,completed=now())
        write_json(stage/'report.json',report)
        return
    state['discovered_through'] = current.isoformat()
    with (stage/'output.csv').open('x',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=HEADERS.values());writer.writeheader()
        writer.writerows(new[fid].model_dump(mode='json',by_alias=True) for fid in sorted(new))
    build(stage/'ufc_fighters.db',[new[fid] for fid in sorted(new)],registry)
    paired=validate(stage/'output.csv',stage/'ufc_fighters.db')
    validate_merge(old,paired,targets)
    validate_routes(root,stage)
    save(stage,paired,state,sources,report)
    load(stage,paired)
    report.update(reason='validated event candidate',completed=now(),coverage=coverage(paired),
                  hashes={n:digest(stage/n) for n in FILES[:2]},changes=changes(old,paired),
                  total_fighters=len(paired),fetch_provenance=provenance)
    write_json(stage/'report.json',report)


def publish(root, stage):
    if initial(root):
        raise ValueError('Event refresh cannot bootstrap')
    report=json.loads((stage/'report.json').read_text(encoding='utf-8'))
    if report.get('reason')=='no work':
        return False
    if report.get('mode')!='event' or report.get('reason')!='validated event candidate' or report.get('failed'):
        raise ValueError('Not a validated event candidate')
    if report['baseline']!=baseline(root) or report['aliases_hash']!=digest(ALIASES):
        raise ValueError('Candidate baseline or aliases changed; rebuild against newer baseline')
    if report['hashes']!={n:digest(stage/n) for n in FILES[:2]} or report['sidecar_hashes']!={n:digest(stage/n) for n in SIDECARS}:
        raise ValueError('Event candidate manifest mismatch')
    old=validate(root/'output.csv',root/'ufc_fighters.db');load(root,old)
    new=validate(stage/'output.csv',stage/'ufc_fighters.db')
    _, provenance=load(stage,new)
    validate_merge(old,new,report['target_ids'])
    validate_routes(root,stage)
    fetched = [stamp(item['fetched_at']) for fighter in provenance['fighters'].values()
               for item in [fighter['profile'], *fighter['history']] if item]
    report.update(published=True,publication_checked=now(),published_hashes=report['hashes'],
                  data_as_of=min(fetched).date().isoformat(),
                  freshness='Per-fighter timestamps are authoritative; unchanged values do not prove event incorporation')
    replace(root,stage,report,True)
    return True


def main(root='.', *, reviewed=None, pace=1,budget=5400,workers=4,max_events=3,listing_limit=100):
    root=Path(root).resolve()
    with locked(root):
        if reviewed:
            recover(root)
            return publish(root,Path(reviewed).resolve())
        if (root/'.refresh-undo').exists():
            raise ValueError('Recovery required before dry run')
        if initial(root):
            raise ValueError('Event mode requires an explicitly bootstrapped UFC.com baseline')
        folder=root/'candidates';folder.mkdir(exist_ok=True)
        stage=Path(tempfile.mkdtemp(prefix='event-',dir=folder))
        print(f'Candidate directory: {stage}',flush=True)
        report={'mode':'event','schema_version':VERSION,'source':'UFC.com','started':now(),'published':False,
                'baseline':baseline(root),'aliases_hash':digest(ALIASES),'failed':{},'history_pages':{},
                'source_warnings':{},'successful':0}
        # Everything targeted is fresh, including all required history pagination.
        # No cache is required for correctness, and no old current-profile body is used.
        client=Runtime(Client,stage,pace=pace,budget=budget,workers=workers,refresh=True)
        try:
            candidate(root,stage,client,report,datetime.now(UTC),max_events,listing_limit)
        except BaseException as exc:
            report.update(reason=str(exc),status='failed',failure_evidence=client.save_failure(stage/'failure-evidence'))
            write_json(stage/'failure-report.json',report)
            write_json(root/'collection-failure.json',report)
            raise
        finally:
            client.close()
            report.update(runtime=client.metrics.snapshot(),source_fetch_range=client.source_dates())
            write_json(stage/('report.json' if (stage/'report.json').exists() else 'failure-report.json'),report)
        return stage
