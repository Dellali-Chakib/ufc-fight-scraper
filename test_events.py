"""Event lifecycle tests; altered genuine fixtures are explicitly synthetic cases."""
import copy
import csv
from contextlib import closing
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import requests
from bs4 import BeautifulSoup
from scraper import event_refresh as refresh, publication, refresh_state as state
from scraper.contract import Fighter, HEADERS
from scraper.database import build, reader
from scraper.events import LISTING, discover_events, parse_event, parse_listing
from scraper.fighter_stats import is_ufc_event, parse_profile
from scraper.identity import reconcile
from scraper.source import SourceError
from scraper.stat_scraper import collect_profile
from scripts.actions_refresh import allowed_publish, push_candidate
from test_refresh import BASE, FIXTURES, Pages, fixture, terminal
from test_runtime import response
from validate_export import validate

EVENT='https://www.ufc.com/event/ufc-334'
NOW=datetime(2026,11,27,23,tzinfo=UTC)


def event_fixture():
    return (FIXTURES/'events/ufc-334.html').read_text(encoding='utf-8')


def small_event():
    p=BeautifulSoup(event_fixture(),'html.parser')
    cards=p.select('.c-listing-fight')
    for c in cards[1:]: c.decompose()
    for color,slug in [('red','kayla-harrison'),('blue','israel-adesanya')]:
        for a in cards[0].select('.c-listing-fight__corner--'+color+' a[href*="/athlete/"]'):
            a['href']=BASE+slug
    return str(p)


def small_listing():
    p=BeautifulSoup((FIXTURES/'events/listing.html').read_text(encoding='utf-8'),'html.parser')
    v=p.select_one('.view-id-events_upcoming_past.view-display-id-past')
    for card in v.select('article.c-card-event--result'):
        if card.select_one('.c-card-event--result__headline a')['href']!='/event/ufc-334':card.decompose()
    for n in v.select('.pager'):n.decompose()
    return str(p)


class EventParserTests(unittest.TestCase):
    def test_genuine_completed_and_synthetic_upcoming_unknown(self):
        e=parse_event(event_fixture(),EVENT,NOW)
        self.assertEqual(e['status'],'complete');self.assertEqual(len(e['bouts']),13)
        self.assertEqual(len(e['participants']),26)
        self.assertTrue(any(b['outcomes']==['draw','draw'] for b in e['bouts']))
        p=BeautifulSoup(small_event(),'html.parser')
        for n in p.select('[class*=c-listing-fight__outcome--]'):n.clear()
        self.assertEqual(parse_event(str(p),EVENT,NOW)['status'],'pending')
        with self.assertRaises(SourceError):parse_event(event_fixture(),EVENT,NOW-timedelta(days=20))
        with self.assertRaises(SourceError):parse_event('<title>Access Denied</title>',EVENT,NOW)

    def test_canceled_replacement_draw_and_no_contest(self):
        p=BeautifulSoup(small_event(),'html.parser');c=p.select_one('.c-listing-fight')
        old=copy.copy(c);old['data-fmid']='90001';old['data-status']='cancelled'
        for a in old.select('a[href*="/athlete/"]'):a['href']=BASE+'withdrawn-athlete'
        c.insert_after(old)
        e=parse_event(str(p),EVENT,NOW)
        self.assertNotIn(BASE+'withdrawn-athlete',e['participants'])
        self.assertEqual(len(e['participants']),2)
        for label in ['Draw','No Contest']:
            q=BeautifulSoup(small_event(),'html.parser')
            for n in q.select('[class*=c-listing-fight__outcome--]'):n.string=label
            self.assertEqual(parse_event(str(q),EVENT,NOW)['status'],'complete')

    def test_missing_participant_conflicts_and_duplicate_bout(self):
        p=BeautifulSoup(small_event(),'html.parser')
        for a in p.select('.c-listing-fight__corner--blue a[href*="/athlete/"]'):a.decompose()
        with self.assertRaises(SourceError):parse_event(str(p),EVENT,NOW)
        p=BeautifulSoup(small_event(),'html.parser');c=p.select_one('.c-listing-fight');c.insert_after(copy.copy(c))
        self.assertEqual(len(parse_event(str(p),EVENT,NOW)['bouts']),1)
        p.select('.c-listing-fight')[1]['data-status']='cancelled'
        with self.assertRaises(SourceError):parse_event(str(p),EVENT,NOW)

    def test_listing_outage_catchup_bound_and_duplicate_pages(self):
        raw=(FIXTURES/'events/listing.html').read_text(encoding='utf-8')
        more=(FIXTURES/'events/listing-page1.html').read_text(encoding='utf-8')
        entries,nxt=parse_listing(raw)
        self.assertEqual(nxt,LISTING+'?page=1')
        self.assertNotIn('https://www.ufc.com/event/ufc-335',{i['id'] for i in entries})
        pages=Pages({LISTING:raw,LISTING+'?page=1':more})
        found=discover_events(pages,datetime(2026,9,15,tzinfo=UTC),NOW)
        self.assertIn(EVENT,found);self.assertGreater(len(found),len(entries))
        with self.assertRaises(SourceError):discover_events(pages,datetime(2026,9,15,tzinfo=UTC),NOW,1)
        pages.data[LISTING+'?page=1']=raw
        with self.assertRaises(SourceError):discover_events(pages,datetime(2026,9,15,tzinfo=UTC),NOW)

    def test_history_observed_paths_and_unknown_outcomes(self):
        for path in ['/event/FOX8','/event/FX4','/event/FUEL9','/event/UFN24',
                     '/event/Ultimate-Ultimate-96','/event/cryptocom-ufc-331']:
            self.assertTrue(is_ufc_event(path))
        for path in ['/event/strikeforcer-heavyweight-grand-prix-final','/event/road-to-ufc-season-5-semifinals',
                     '/event/tuf-unrelated-show','/event/boxing-1','/event/FOX999unknown']:
            self.assertFalse(is_ufc_event(path))
        saved=(FIXTURES/'events/aaron-riley-legacy.html').read_text(encoding='utf-8')
        legacy=parse_profile(saved,BASE+'aaron-riley',NOW.date())
        self.assertEqual(legacy.bouts['bout:4377'][1], 'loss')
        self.assertFalse(any(w['field']=='history' for w in legacy.warnings))
        p=parse_profile(fixture('aalon-cruz'),BASE+'aalon-cruz',NOW.date())
        # Unknown outcomes remain incomplete even when event recognition improves.
        self.assertEqual(p.history_status,'incomplete')

    def test_unknown_event_type_is_not_silently_discarded(self):
        raw=small_listing().replace('/event/ufc-334','/event/unrecognized-sponsor-event')
        with self.assertRaisesRegex(SourceError,'Unclassified'):parse_listing(raw)

    def test_followup_eligibility(self):
        e={'status':'pending','checks':{}};self.assertIsNone(state.due(e,NOW))
        e['status']='complete';self.assertEqual(state.due(e,NOW),'initial')
        e['checks']['initial']={'checked_at':NOW.isoformat()}
        self.assertIsNone(state.due(e,NOW+timedelta(hours=23)))
        self.assertEqual(state.due(e,NOW+timedelta(hours=24)),'24h')
        e['checks']['24h']={'checked_at':(NOW+timedelta(hours=24)).isoformat()}
        self.assertEqual(state.due(e,NOW+timedelta(hours=48)),'48h')
        e['checks']['48h']={};self.assertIsNone(state.due(e,NOW+timedelta(days=5)))


class EventRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.html={BASE+s:terminal(fixture(s)) for s in ['kayla-harrison','israel-adesanya','alex-pereira','anderson-silva','brendon-marotte']}
        self.html.update({LISTING:small_listing(),EVENT:small_event()})
        fields=[]
        for slug in ['kayla-harrison','israel-adesanya','alex-pereira','anderson-silva']:
            f,_=collect_profile(Pages(self.html),BASE+slug,datetime.now(UTC).date());fields.append(f)
        self.registry={};reconcile(fields,self.registry,{}, {})
        self.rows={f['fighter_id']:Fighter.model_validate(f) for f in fields}
        with (self.root/'output.csv').open('w',newline='',encoding='utf-8') as stream:
            w=csv.DictWriter(stream,fieldnames=HEADERS.values());w.writeheader()
            w.writerows(self.rows[k].model_dump(mode='json',by_alias=True) for k in sorted(self.rows))
        build(self.root/'ufc_fighters.db',list(self.rows.values()),self.registry)
        stamp=(datetime.now(UTC)-timedelta(days=1)).isoformat()
        src={r.url:{'fetched_at':stamp} for r in self.rows.values()}
        report={'started':datetime.now(UTC).isoformat(),'fetch_provenance':src}
        state.full_sidecars(self.root,self.root,self.rows,report)
        publication.write_json(self.root/'collection-success.json',{'generation':report['generation']})
        self.calls=[]

    def run_candidate(self):
        def get(session,url,**kwargs):
            self.calls.append(url)
            return response(self.html[url])
        with patch.object(requests.Session,'get',new=get):
            return refresh.main(self.root,pace=0,budget=30,workers=2,max_events=1)

    def test_fresh_unchanged_full_roster_preserved_and_repeat_execution(self):
        before=publication.baseline(self.root);stage=self.run_candidate()
        r=json.loads((stage/'report.json').read_text());self.assertEqual(r['reason'],'validated event candidate')
        self.assertEqual(r['runtime']['live_requests'],4);self.assertEqual(r['runtime'].get('cache_hits',0),0)
        self.assertEqual(publication.baseline(self.root),before)
        new=validate(stage/'output.csv',stage/'ufc_fighters.db');self.assertEqual(new,self.rows)
        st,src=state.load(stage,new);check=st['events'][EVENT]['checks']['initial']
        self.assertEqual(len(check['unchanged_fighters']),2)
        self.assertIn('unverified',check['upstream_incorporation'])
        for fid in set(self.rows)-set(r['target_ids']):
            self.assertEqual(src['fighters'][fid],state.load(self.root,self.rows)[1]['fighters'][fid])
        refresh.main(self.root,reviewed=stage)
        success=json.loads((self.root/'collection-success.json').read_text())
        datetime.fromisoformat(success['data_as_of'])
        self.assertIn('authoritative',success['freshness'])
        baseline=publication.baseline(self.root);self.calls=[]
        again=self.run_candidate();again_report=json.loads((again/'report.json').read_text())
        self.assertEqual(again_report['reason'],'no work');self.assertEqual(self.calls,[LISTING])
        self.assertFalse(refresh.main(self.root,reviewed=again));self.assertEqual(publication.baseline(self.root),baseline)

    def test_fresh_checks_ignore_old_or_expired_current_profile_archives(self):
        from scraper.runtime import Runtime
        from test_runtime import metadata
        for hours in (1,48):
            def runtime(*args,**kwargs):
                client=Runtime(*args,**kwargs)
                fetched=(datetime.now(UTC)-timedelta(hours=hours)).isoformat()
                url=BASE+'kayla-harrison'
                client.archive.put(url,self.html[url].replace('4.29','4.88').encode(),metadata(url,fetched=fetched))
                return client
            self.calls=[]
            with patch.object(refresh,'Runtime',side_effect=runtime):stage=self.run_candidate()
            self.assertIn(BASE+'kayla-harrison',self.calls)
            report=json.loads((stage/'report.json').read_text())
            self.assertEqual(report['runtime'].get('cache_hits',0),0)
            self.assertEqual(validate(stage/'output.csv',stage/'ufc_fighters.db'),self.rows)

    def test_verified_newcomer_is_added_without_dropping_anyone(self):
        self.html[EVENT]=self.html[EVENT].replace(BASE+'israel-adesanya',BASE+'brendon-marotte')
        stage=self.run_candidate();new=validate(stage/'output.csv',stage/'ufc_fighters.db')
        self.assertEqual(len(new),5);self.assertTrue(set(self.rows)<=set(new))
        self.assertTrue(any(r.name=='Brendon Marotte' for r in new.values()))

    def test_transport_or_validation_failure_leaves_work_retryable(self):
        before=publication.baseline(self.root)
        self.html[BASE+'kayla-harrison']='<title>Access Denied</title>'
        with self.assertRaises(SourceError):self.run_candidate()
        self.assertEqual(publication.baseline(self.root),before)
        self.assertTrue(list((self.root/'candidates').glob('*/failure-report.json')))
        self.html[BASE+'kayla-harrison']=terminal(fixture('kayla-harrison'))
        stage=self.run_candidate()
        with patch.object(refresh,'validate_merge',side_effect=ValueError('injected validation failure')),self.assertRaises(ValueError):
            refresh.main(self.root,reviewed=stage)
        self.assertEqual(publication.baseline(self.root),before)

    def test_numeric_api_ids_are_preserved_and_checked(self):
        import sqlite3
        stage=self.run_candidate()
        refresh.validate_routes(self.root,stage)
        fid=next(iter(self.rows))
        with closing(sqlite3.connect(stage/'ufc_fighters.db')) as db, db:
            db.execute('UPDATE fighters SET id=id+10000 WHERE fighter_id=?',(fid,))
            db.execute('UPDATE identities SET id=id+10000 WHERE fighter_id=?',(fid,))
        # CSV/SQLite normalization alone cannot detect numeric API ID drift.
        validate(stage/'output.csv',stage/'ufc_fighters.db')
        with self.assertRaisesRegex(ValueError,'numeric API'):refresh.validate_routes(self.root,stage)

    def test_generation_tampering_and_nonparticipant_changes_fail(self):
        stage=self.run_candidate();r=json.loads((stage/'report.json').read_text())
        old=validate(self.root/'output.csv',self.root/'ufc_fighters.db');new=copy.deepcopy(old)
        fid=next(f for f in old if f not in r['target_ids']);new[fid]=new[fid].model_copy(update={'height':99})
        with self.assertRaisesRegex(ValueError,'Nonparticipant'):refresh.validate_merge(old,new,r['target_ids'])
        st=json.loads((stage/state.STATE).read_text());st['generation']='wrong'
        publication.write_json(stage/state.STATE,st)
        with self.assertRaisesRegex(ValueError,'generation'):state.load(stage,old)
        with self.assertRaisesRegex(ValueError,'manifest'):refresh.main(self.root,reviewed=stage)

    def test_transaction_failure_restores_dataset_state_and_provenance(self):
        stage=self.run_candidate();before=publication.baseline(self.root)
        real=publication.install
        failed=False
        def install(src,dest):
            nonlocal failed
            if dest==self.root/state.SOURCES and not failed:
                failed=True;raise OSError('injected source sidecar install failure')
            real(src,dest)
        with patch.object(publication,'install',side_effect=install),self.assertRaises(OSError):
            refresh.main(self.root,reviewed=stage)
        self.assertEqual(publication.baseline(self.root),before)
        self.assertFalse((self.root/'.refresh-undo').exists())
        refresh.main(self.root,reviewed=stage)
        state.load(self.root,validate(self.root/'output.csv',self.root/'ufc_fighters.db'))

    def test_legacy_baseline_no_bootstrap_and_missing_sources(self):
        other=self.root/'empty';other.mkdir()
        with self.assertRaisesRegex(ValueError,'bootstrapped'):refresh.main(other)
        before=(self.root/'output.csv').read_bytes()
        (self.root/state.SOURCES).unlink()
        with self.assertRaises(OSError):self.run_candidate()
        self.assertEqual((self.root/'output.csv').read_bytes(),before)

    def test_corrected_replacement_invalidates_checks(self):
        stage=self.run_candidate();refresh.main(self.root,reviewed=stage)
        st,src=state.load(self.root,self.rows)
        st['events'][EVENT]['checks']['initial']['checked_at']=(datetime.now(UTC)-timedelta(hours=25)).isoformat()
        publication.write_json(self.root/state.STATE,st)
        self.html[EVENT]=self.html[EVENT].replace(BASE+'israel-adesanya',BASE+'brendon-marotte')
        stage=self.run_candidate();new=validate(stage/'output.csv',stage/'ufc_fighters.db');st,_=state.load(stage,new)
        self.assertEqual(set(st['events'][EVENT]['checks']),{'initial'})
        self.assertIn('previous_results',st['events'][EVENT])


class WorkflowTests(unittest.TestCase):
    def test_branch_restriction_and_remote_change(self):
        env={'DEFAULT_BRANCH':'main','GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'schedule'}
        self.assertTrue(allowed_publish(env))
        for override in [{'GITHUB_REF':'refs/heads/feature'},{'GITHUB_EVENT_NAME':'pull_request'},{'DEFAULT_BRANCH':''}]:
            self.assertFalse(allowed_publish(dict(env,**override)))
        with patch('scripts.actions_refresh.git',side_effect=['','old','','new']),patch('scripts.actions_refresh.event_main') as pub:
            with self.assertRaisesRegex(ValueError,'Remote baseline changed'):push_candidate(Path('candidate'),'event',env)
            pub.assert_not_called()

    def test_failed_remote_push_never_rebases_or_forces(self):
        env={'DEFAULT_BRANCH':'main','GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch'}
        calls=[]
        def git(*args):
            calls.append(args)
            if args==('rev-parse','HEAD') or args==('rev-parse','FETCH_HEAD'):return 'same'
            if args[0]=='push':raise subprocess.CalledProcessError(1,args)
            return ''
        with patch('scripts.actions_refresh.git',side_effect=git),patch('scripts.actions_refresh.event_main'),patch('scripts.actions_refresh.subprocess.run') as run:
            run.return_value.returncode=1
            with self.assertRaises(subprocess.CalledProcessError):push_candidate(Path('candidate'),'event',env)
        self.assertIn(('add','--',*publication.FILES),calls)
        self.assertFalse(any('rebase' in c or '--force' in c or '-A' in c for c in calls))

    def test_workflow_schedule_permissions_platform_and_no_bootstrap(self):
        root=Path(__file__).parent/'.github/workflows'
        daily=(root/'update_data.yml').read_text();full=(root/'reconcile_ufc.yml').read_text();diag=(root/'diagnose_ufc.yml').read_text()
        self.assertIn("cron: '23 13 * * *'",daily)
        self.assertNotIn('schedule:',full)
        for s in [daily,full]:
            for expected in ['group: fighter-data-publish','cancel-in-progress: false','runs-on: windows-latest','shell: pwsh','python -m pip','contents: write','default: false','retention-days: 14']:
                self.assertIn(expected,s)
            self.assertNotIn('--bootstrap',s);self.assertNotIn('git add -A',s);self.assertNotIn('secrets.PAT',s)
        self.assertIn('contents: read',diag);self.assertNotIn('contents: write',diag)
        self.assertIn('--events',diag);self.assertIn('runs-on: windows-latest',diag)
        self.assertIn("'--budget', '5400'",daily);self.assertIn('timeout-minutes: 120',daily)
        self.assertIn("'--budget', '18000'",full);self.assertIn('timeout-minutes: 360',full)


if __name__=='__main__':unittest.main()
