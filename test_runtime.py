import hashlib
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import requests
from bs4 import BeautifulSoup

from scraper import publication, stat_scraper
from scraper.database import reader
from scraper.directory import discover
from scraper.fighter_stats import parse_profile
from scraper.runtime import Archive, Cancelled, Limiter, Metrics, Runtime
from scraper.source import Client, DIRECTORY, SourceError
from test_refresh import BASE, FIXTURES, TODAY, fixture, terminal
from validate_export import validate


def response(html, status=200, headers=None):
    r = requests.Response()
    r.status_code, r._content, r._content_consumed = status, html.encode(), True
    r.encoding = "utf-8"
    r.headers.update(headers or {"Content-Type": "text/html; charset=utf-8"})
    return r


def metadata(url, fetched=None, status=200):
    return {"url": url, "status": status, "content_type": "text/html",
            "encoding": "utf-8", "retrieved": fetched or datetime.now(UTC).isoformat()}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.count = 0

    def folder(self):
        self.count += 1
        p = self.root / str(self.count)
        p.mkdir()
        return p

    def runtime(self, **kwargs):
        stage = self.folder()
        r = Runtime(lambda p,b: Client(p,b,attempts=1), stage, pace=0, budget=10, **kwargs)
        self.addCleanup(r.close)
        return r

    def seed(self, url, html, **kwargs):
        root = self.folder()
        archive = Archive(root / "responses")
        path = Path(archive.put(url, html.encode(), metadata(url, **kwargs)))
        return root, path

    def report(self):
        return {"started": datetime.now(UTC).isoformat(), "successful": 0, "failed": {},
                "source_warnings": {}, "history_pages": {}, "directory_complete": True,
                "directory_pages": 1, "published": False}

    def test_filtered_parser_matches_full_dom_for_genuine_fixtures(self):
        for path in FIXTURES.glob("*.html"):
            if path.stem.startswith("directory"):
                continue
            slug = path.stem.replace("-page1", "")
            url = BASE + slug + ("?page=1" if path.stem.endswith("-page1") else "")
            html = path.read_text(encoding="utf-8") + '<div class><p>Unrelated decoration</p></div>'
            with self.subTest(path=path.name):
                self.assertEqual(parse_profile(html,url,TODAY),
                                 parse_profile(BeautifulSoup(html,"html.parser"),url,TODAY))

    def test_recent_eta_discards_cached_prefix_and_accounts_for_stalls(self):
        times=[i*.01 for i in range(1000)]+[100+10*i for i in range(41)]
        self.assertEqual(stat_scraper.observed_eta(times,1041,1141,500),1000)
        self.assertEqual(stat_scraper.observed_eta(times,1041,1141,600),1250)
        self.assertEqual(stat_scraper.observed_eta([],10,10,0),0)
        self.assertIsNone(stat_scraper.observed_eta([],0,10,0))

    def test_resume_partial_history_fetches_missing_only_and_keeps_dates(self):
        url = BASE + "anderson-silva"
        old = (datetime.now(UTC)-timedelta(minutes=1)).isoformat()
        root, _ = self.seed(url, fixture("anderson-silva"), fetched=old)
        first = self.runtime(resume=root)
        with patch.object(requests.Session,"get",side_effect=requests.Timeout), self.assertRaises(SourceError):
            stat_scraper.collect_profile(first,url,TODAY)
        self.assertFalse((first.stage/"report.json").exists())
        second = self.runtime(resume=first.stage)
        with patch.object(requests.Session,"get",return_value=response(terminal(fixture("anderson-silva-page1")))) as get:
            fields, _ = stat_scraper.collect_profile(second,url,TODAY)
        self.assertEqual(get.call_count,1)
        self.assertEqual(fields["history_status"],"complete")
        self.assertEqual(fields["fights_in_ufc"],6)
        self.assertEqual(second.provenance[url]["fetched_at"],old)
        third = self.runtime(resume=second.stage)
        with patch.object(requests.Session,"get",side_effect=AssertionError("Unexpected network")):
            again, _ = stat_scraper.collect_profile(third,url,TODAY)
        self.assertEqual(again,fields)
        self.assertEqual(third.metrics.snapshot()["cache_hits"],2)

    def test_missing_corrupt_expired_and_invalid_cache_are_not_trusted(self):
        url = BASE+"kayla-harrison"
        html = terminal(fixture("kayla-harrison"))
        for failure in ("missing", "checksum", "gzip", "expired", "future", "url", "status", "mime", "challenge", "structure"):
            with self.subTest(failure=failure):
                root, path = self.seed(url,html)
                m = json.loads(path.read_text())
                if failure == "missing": (path.parent/m["body"]).unlink()
                elif failure == "gzip": (path.parent/m["body"]).write_bytes(b"not a gzip file")
                elif failure == "checksum": m["sha256"]="0"*64
                elif failure == "expired": m["retrieved"]=(datetime.now(UTC)-timedelta(days=2)).isoformat()
                elif failure == "future": m["retrieved"]=(datetime.now(UTC)+timedelta(hours=1)).isoformat()
                elif failure == "url": m["url"]=BASE+"other"
                elif failure == "status": m["status"]=403
                elif failure == "mime": m["content_type"]="image/png"
                elif failure in {"challenge","structure"}:
                    bad = "<title>Access Denied</title>" if failure=="challenge" else "<h1>Unrelated page</h1>"
                    Archive(root/"responses").put(url,bad.encode(),metadata(url))
                    m=json.loads(path.read_text())
                path.write_text(json.dumps(m),encoding="utf-8")
                r=self.runtime(resume=root)
                with patch.object(requests.Session,"get",return_value=response(html)) as get:
                    fields,_=stat_scraper.collect_profile(r,url,TODAY)
                self.assertEqual(fields["name"],"Kayla Harrison")
                self.assertEqual(get.call_count,1)

    def test_partial_directory_is_not_complete_until_terminal_page_validates(self):
        root,_=self.seed(DIRECTORY,fixture("directory"))
        r=self.runtime(resume=root);report={}
        with patch.object(requests.Session,"get",side_effect=requests.Timeout),self.assertRaises(SourceError):
            discover(r,report)
        self.assertFalse(report.get("directory_complete",False))
        again=self.runtime(resume=r.stage);report={}
        with patch.object(requests.Session,"get",return_value=response(terminal(fixture("directory1")))) as get:
            urls=discover(again,report)
        self.assertEqual(get.call_count,1)
        self.assertEqual(len(urls),22)
        self.assertTrue(report["directory_complete"])

    def test_redirect_targets_share_rate_limit_and_url_deduplication(self):
        r=self.runtime(workers=2);r.limiter.pace=.02
        first=BASE+"alias";target=BASE+"kayla-harrison"
        calls=[]
        def get(session,url,**kwargs):
            calls.append((url,time.monotonic()))
            return response("redirect",301,{"Location":target}) if url==first else response(terminal(fixture("kayla-harrison")))
        with patch.object(requests.Session,"get",new=get),ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(r.get,first);b=pool.submit(r.get,target)
            self.assertEqual(a.result()[1],target);b.result()
        self.assertEqual([url for url,_ in calls].count(target),1)
        self.assertEqual(len(calls),2)
        self.assertGreaterEqual(calls[1][1]-calls[0][1],.015)

    def test_cached_html_is_reprocessed_and_explicit_refresh_is_available(self):
        url=BASE+"kayla-harrison";html=terminal(fixture("kayla-harrison"))
        root,_=self.seed(url,html)
        r=self.runtime(resume=root)
        original=stat_scraper.parse_profile
        def changed(*args,**kwargs):
            p=original(*args,**kwargs);p.fields["slpm"]=9.25;return p
        with patch.object(stat_scraper,"parse_profile",side_effect=changed), patch.object(requests.Session,"get",side_effect=AssertionError("network")):
            fields,_=stat_scraper.collect_profile(r,url,TODAY)
        self.assertEqual(fields["slpm"],9.25)
        for kwargs in ({"refresh":True},{"refresh_urls":[url]}):
            fresh=self.runtime(resume=root,**kwargs)
            with patch.object(requests.Session,"get",return_value=response(html)) as get:
                fresh.get(url);fresh.get(url)
            self.assertEqual(get.call_count,1) # Still deduplicates within a fresh run.

    def test_mixed_old_partial_history_stays_unknown_until_coherent_refresh(self):
        url=BASE+"anderson-silva"
        root,_=self.seed(url,fixture("anderson-silva"),fetched=(datetime.now(UTC)-timedelta(hours=2)).isoformat())
        r=self.runtime(resume=root)
        with patch.object(requests.Session,"get",return_value=response(terminal(fixture("anderson-silva-page1")))) as get:
            fields,warnings=stat_scraper.collect_profile(r,url,TODAY)
        self.assertEqual(get.call_count,1)
        self.assertEqual(fields["history_status"],"incomplete")
        self.assertIsNone(fields["fights_in_ufc"])
        self.assertTrue(any('mixed source-fetch cohort' in w.get('reason','') for w in warnings))
        fresh=self.runtime(resume=r.stage,refresh_urls=[url])
        with patch.object(requests.Session,"get",side_effect=[response(fixture("anderson-silva")),response(terminal(fixture("anderson-silva-page1")))]) as get:
            fields,_=stat_scraper.collect_profile(fresh,url,TODAY)
        self.assertEqual(get.call_count,2)
        self.assertEqual(fields["fights_in_ufc"],6)

    def test_workers_share_rate_limit_but_not_sessions_and_deduplicate(self):
        r=self.runtime(workers=4);r.limiter.pace=.025
        starts=[];sessions=set();lock=threading.Lock()
        def get(session,url,**kwargs):
            with lock: starts.append(time.monotonic());sessions.add(id(session))
            time.sleep(.06)
            return response(terminal(fixture("kayla-harrison")).replace(BASE+"kayla-harrison",url))
        with patch.object(requests.Session,"get",new=get), ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(r.get,[BASE+f"athlete-{i}" for i in range(8)]))
        self.assertGreater(len(sessions),1)
        self.assertTrue(all(b-a>=.02 for a,b in zip(starts,starts[1:])))
        self.assertGreater(r.metrics.snapshot()["peak_inflight"],1)
        self.assertLessEqual(r.metrics.snapshot()["peak_inflight"],4)
        shared=self.runtime(workers=4);url=BASE+"kayla-harrison"
        with patch.object(requests.Session,"get",return_value=response(terminal(fixture("kayla-harrison")))) as get, ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(shared.get,[url]*4))
        self.assertEqual(get.call_count,1)
        self.assertEqual(shared.metrics.snapshot()["deduplicated_requests"],3)

    def test_retry_after_blocks_all_workers_and_sustained_throttle_stops(self):
        r=self.runtime(workers=2);r.limiter.pace=.02
        # Default Client retries are intentional in this test.
        r.factory=lambda p,b:Client(p,b,attempts=2)
        url=BASE+"kayla-harrison";second=BASE+"other"
        starts=[];counts={};ready=threading.Event();lock=threading.Lock()
        def get(session,target,**kwargs):
            with lock:
                starts.append((target,time.monotonic()));counts[target]=counts.get(target,0)+1
                first=target==url and counts[target]==1
            if first:
                ready.set();return response("throttled",429,{"Content-Type":"text/html","Retry-After":"1"})
            return response(terminal(fixture("kayla-harrison")).replace(url,target))
        with patch.object(requests.Session,"get",new=get), ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(r.get,url);self.assertTrue(ready.wait(2));b=pool.submit(r.get,second)
            a.result();b.result()
        self.assertEqual(len(starts),3)
        self.assertTrue(all(t-starts[0][1]>=.9 for _,t in starts[1:]))
        metrics=Metrics();limiter=Limiter(0,2,metrics)
        for _ in range(3): limiter.throttled()
        with self.assertRaisesRegex(Cancelled,"Sustained throttling"):limiter.check()

    def test_controlled_cancellation_and_worker_failure_preserve_checkpoints(self):
        for failure in (False,True):
            with self.subTest(failure=failure):
                r=self.runtime(workers=2);urls=[BASE+f"fighter-{i}" for i in range(6)]
                def get(session,url,**kwargs):
                    if url.endswith("-1"):
                        if failure:return response("<title>Access Denied</title>")
                        r.limiter.cancel_file.write_text("stop")
                    return response(terminal(fixture("kayla-harrison")).replace(BASE+"kayla-harrison",url))
                report=self.report()
                with patch.object(requests.Session,"get",new=get), self.assertRaises(SourceError):
                    stat_scraper.collect_profiles(r,urls,TODAY,r.stage,report)
                self.assertTrue((r.stage/"progress.json").exists())
                self.assertTrue((r.stage/"collected-profiles.json").exists())
                self.assertFalse((r.stage/"report.json").exists())
                self.assertLessEqual(r.metrics.snapshot()["live_requests"],2)
                if failure:self.assertIn(urls[1],report["failed"])

    def test_deterministic_exports_identity_and_last_good_preservation(self):
        seed=self.folder();archive=Archive(seed/"responses")
        cards=[];urls=[]
        for n in range(3):
            url=BASE+f"fighter-{n}";urls.append(url)
            html=terminal(fixture("kayla-harrison")).replace(BASE+"kayla-harrison",url).replace("Kayla Harrison",f"Fighter {n}").replace("node/136296",f"node/13629{n}")
            archive.put(url,html.encode(),metadata(url))
            cards.append(f'<div class="node--view-mode-all-athletes-result"><div class="c-listing-athlete-flipcard__action"><a href="{url}">Profile</a></div></div>')
        directory='<div class="view-id-all_athletes">'+''.join(cards)+'</div>'
        archive.put(DIRECTORY,directory.encode(),metadata(DIRECTORY))
        candidates=[]
        for workers in (1,4):
            root=self.folder()
            with patch.object(requests.Session,"get",side_effect=AssertionError("Unexpected network")):
                stage=stat_scraper.main(root,resume=seed,workers=workers,pace=0)
            candidates.append(stage)
            self.assertEqual(len(validate(stage/"output.csv",stage/"ufc_fighters.db")),3)
            with closing(reader(stage/"ufc_fighters.db")) as db:
                self.assertEqual([row[0] for row in db.execute('SELECT id FROM fighters ORDER BY url')],[1,2,3])
            report=json.loads((stage/"report.json").read_text())
            self.assertEqual(report["runtime"]["cache_hits"],4)
        self.assertEqual((candidates[0]/"output.csv").read_bytes(),(candidates[1]/"output.csv").read_bytes())
        root=self.folder()
        for name in publication.FILES:(root/name).write_bytes(b"last good publication")
        before=publication.baseline(root)
        bad,_=self.seed(DIRECTORY,directory)
        with patch.object(requests.Session,"get",return_value=response("denied",403)),self.assertRaises(SourceError):
            stat_scraper.main(root,resume=bad,workers=1,pace=0)
        self.assertEqual(publication.baseline(root),before)


if __name__=="__main__":unittest.main()
