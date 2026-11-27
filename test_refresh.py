import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from bs4 import BeautifulSoup
from pydantic import ValidationError

import app
from schemas import FighterDetailResponse
from scraper import diagnostic, publication, stat_scraper
from scraper.contract import Fighter
from scraper.database import reader
from scraper.directory import discover
from scraper.fighter_stats import history, parse_profile
from scraper.identity import reconcile
from scraper.source import DIRECTORY, Client, SourceError
from validate_export import validate

FIXTURES = Path(__file__).parent / "tests/fixtures"
TODAY = date(2026, 11, 24)
BASE = "https://www.ufc.com/athlete/"


def fixture(name):
    return (FIXTURES / (name + ".html")).read_text(encoding="utf-8")


def parsed(name, html=None):
    return parse_profile(html or fixture(name), BASE + name, TODAY)


def terminal(html):
    page = BeautifulSoup(html, "html.parser")
    for pager in page.select("[data-drupal-views-infinite-scroll-pager]"):
        pager.decompose()
    return str(page)


class Pages:
    def __init__(self, data):
        self.data = data
        self.calls = []
        self.session = MagicMock()

    def get(self, url):
        self.calls.append(url)
        return self.data[url], url


class ParserTests(unittest.TestCase):
    def test_genuine_zero_source_height_is_unknown_without_relaxing_contract(self):
        url = BASE + "adrian-serrano"
        html = fixture("adrian-serrano")
        fields, warnings = stat_scraper.collect_profile(Pages({url: terminal(html)}), url, TODAY)
        self.assertIsNone(fields["height"])
        self.assertEqual(fields["weight"], 170)
        self.assertEqual(fields["fight_count"], 0)
        self.assertEqual(fields["fights_in_ufc"], 1)
        self.assertIn({"field": "height", "raw": "0.00", "category": "source_inconsistency",
                       "reason": "unusable zero source height"}, warnings)
        row = Fighter.model_validate(dict(fields, fighter_id="test-adrian"))
        self.assertIsNone(row.height)
        with self.assertRaises(ValidationError):
            Fighter.model_validate(dict(fields, fighter_id="test-adrian", height=0))
        page = BeautifulSoup(html, "html.parser")
        field = next(f for f in page.select(".c-bio__field")
                     if f.select_one(".c-bio__label").get_text(strip=True) == "Height")
        field.select_one(".c-bio__text").string = "-1"
        with self.assertRaises(SourceError):
            parsed("adrian-serrano", str(page))

    def test_saved_incomplete_record_preserves_independent_fields(self):
        html = fixture("brendon-marotte")
        p = parsed("brendon-marotte")
        self.assertEqual(p.fields["name"], "Brendon Marotte")
        self.assertIsNone(p.fields["record"])
        self.assertIsNone(p.fields["fight_count"])
        self.assertIn(
            {"field": "record", "raw": "11-2- (W-L-D)",
             "reason": "missing source value", "category": "missing_optional"},
            p.warnings,
        )
        normal = parsed("brendon-marotte", html.replace("11-2- (W-L-D)", "11-2-0 (W-L-D)"))
        self.assertEqual(normal.fields["record"], "11-2-0")
        self.assertEqual(normal.fields["fight_count"], 13)
        self.assertEqual(
            {k:v for k,v in p.fields.items() if k not in {"record", "fight_count"}},
            {k:v for k,v in normal.fields.items() if k not in {"record", "fight_count"}},
        )
        self.assertEqual(p.bouts, normal.bouts)
        self.assertTrue(p.bouts)
        self.assertTrue(p.fields["portrait_url"])
        self.assertIn("slpm", p.fields)
        url = BASE + "brendon-marotte"
        fields, warnings = stat_scraper.collect_profile(Pages({url: html}), url, TODAY)
        row = Fighter.model_validate(dict(fields, fighter_id="test-marotte"))
        self.assertIsNone(row.record)
        self.assertIsNone(row.fight_count)
        self.assertIn("record", row.warnings)
        with self.assertRaises(SourceError):
            parsed("brendon-marotte", html.replace("11-2- (W-L-D)", "unexpected layout"))
        for bad in (
            html.replace("<title>", "<title>Access Denied "),
            html.replace('class="hero-profile__name"', 'class="missing-name"'),
            html.replace('href="https://www.ufc.com/athlete/brendon-marotte" rel="canonical"',
                         'href="https://www.ufc.com/athlete/other" rel="canonical"'),
        ):
            with self.assertRaises(SourceError):
                parsed("brendon-marotte", bad)

    def test_missing_optional_values_and_unknown_layout(self):
        page = BeautifulSoup(fixture("kayla-harrison"), "html.parser")
        group = next(g for g in page.select(".c-stat-compare__group")
                     if g.select_one(".c-stat-compare__label").get_text(strip=True) == "Sig. Str. Landed")
        group.select_one(".c-stat-compare__number").clear()
        group.select_one(".c-stat-compare__label-suffix").decompose()
        page.select_one(".hero-profile__division-body").clear()
        p = parsed("kayla-harrison", str(page))
        self.assertIsNone(p.fields["slpm"])
        self.assertIsNone(p.fields["record"])
        self.assertIsNone(p.fields["fight_count"])
        self.assertIsNotNone(p.fields["sapm"])
        group.select_one(".c-stat-compare__number").string = "4.29"
        with self.assertRaisesRegex(SourceError, "Unexpected unit"):
            parsed("kayla-harrison", str(page))
        sparse = parsed("alberta-cerra")
        self.assertEqual(sparse.fields["name"], "Alberta Cerra")
        self.assertTrue(any(w["field"] == "statistics" for w in sparse.warnings))
        source = parsed("aalon-cruz")
        accuracy = next(w for w in source.warnings if "counts" in w)
        self.assertIsNone(accuracy["counts"]["Takedowns Landed"])
        self.assertEqual(source.history_status, "incomplete")

    def test_profiles_and_source_evidence(self):
        p = parsed("israel-adesanya")
        self.assertEqual(
            [
                p.fields[k]
                for k in ("source_id", "height", "reach", "dob", "tdacc", "tdavg")
            ],
            ["28692", 76, 80, "1989-07-22", 0, 0.05],
        )
        self.assertEqual(
            p.warnings[0]["counts"],
            {"Takedowns Attempted": "11", "Takedowns Landed": None},
        )
        kayla = parsed("kayla-harrison")
        self.assertIn("HARRISON", kayla.fields["headshot_url"])
        self.assertIn("itok=", kayla.fields["portrait_url"])
        self.assertEqual(kayla.fields["subavg"], 0.95)
        self.assertEqual(len(kayla.bouts), 3)
        sparse = parsed("john-adajar")
        self.assertEqual(sparse.history_status, "unknown")
        self.assertIsNone(sparse.fields.get("reach"))
        self.assertIsNone(sparse.fields["tddef"])
        self.assertEqual(sparse.fields["tdavg"], 0)
        self.assertNotIn("stance", sparse.fields)
        self.assertEqual(parsed("ricardo-abreu").fields["status"], "Retired")
        self.assertEqual(parsed("tenk-ebbott").fields["name"], "Scott Adams")
        self.assertIsNone(parsed("tenk-ebbott").fields.get("portrait_url"))
        self.assertEqual(parsed("tank-abbott").fields["name"], "Tank Abbott")
        html = (
            fixture("kayla-harrison")
            .replace("68.00", "68.75")
            .replace("66.00", "66.25")
        )
        self.assertEqual(parsed("kayla-harrison", html).fields["height"], 68.75)
        self.assertEqual(parsed("kayla-harrison", html).fields["reach"], 66.25)

    def test_duplicate_labels_identity_and_challenge(self):
        html = fixture("kayla-harrison")
        for bad in [
            html.replace(
                'class="hero-profile__name">Kayla', 'class="hero-profile__name">Other'
            ),
            html
            + '<div class="c-bio__field"><b class="c-bio__label">Height</b><b class="c-bio__text">11</b></div>',
            "<title>Just a moment</title>",
            "<h1>Unexpected HTML</h1>",
        ]:
            with self.assertRaises(SourceError):
                parsed("kayla-harrison", bad)
        parsed("kayla-harrison", html + "<footer><h1>captcha</h1></footer>")

    def test_history_pagination_outcomes_and_overlap(self):
        slug = "anderson-silva"
        url = BASE + slug
        first = fixture(slug)
        second = BeautifulSoup(terminal(fixture(slug + "-page1")), "html.parser")
        duplicate = BeautifulSoup(first, "html.parser").select_one(
            "article.c-card-event--athlete-results"
        )
        second.select_one(".view-id-athlete_results").append(duplicate)
        p = parsed(slug)
        self.assertEqual(p.bouts["bout:8762"][1], "loss")
        fields, _ = stat_scraper.collect_profile(
            Pages({url: first, p.following: str(second)}), url, TODAY
        )
        self.assertEqual(fields["fights_in_ufc"], 6)
        self.assertEqual(fields["last_fight_date"], date(2020, 10, 31))
        with self.assertRaisesRegex(SourceError, "Repeated"):
            stat_scraper.collect_profile(
                Pages({url: first, p.following: first}), url, TODAY
            )

    def test_completed_draw_nc_future_and_sparse_details(self):
        slug = "tenk-ebbott"
        base = BeautifulSoup(fixture(slug), "html.parser")
        base.select_one(".c-card-event--athlete-results__results").decompose()
        self.assertEqual(parsed(slug, str(base)).bouts["bout:1560"][1], "win")
        for label, outcome in [("draw", "draw"), ("nc", "no contest")]:
            html = (
                str(base)
                .replace("red-image win", "red-image " + label)
                .replace("plaque win", "plaque " + label)
                .replace("Win\n", label + "\n")
            )
            self.assertEqual(parsed(slug, html).bouts["bout:1560"][1], outcome)
        url = BASE + slug
        fields, _ = stat_scraper.collect_profile(
            Pages({url: str(base).replace("Mar. 10, 2000", "Mar. 10, 2030")}),
            url,
            TODAY,
        )
        self.assertEqual(fields["fights_in_ufc"], 0)
        self.assertTrue(fields["bad_sample"])

    def test_portrait_failure_does_not_fail_page_access(self):
        class Response:
            def __init__(self):
                self.status_code = 403
                self.headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        client = Client(pace=0, budget=5)
        self.addCleanup(client.session.close)
        client.session = MagicMock()
        client.session.get.return_value = Response()
        with patch("builtins.print") as output:
            diagnostic.probe_image(client, "https://ufc.com/portrait.jpg")
        self.assertTrue(
            any(
                "Hero portrait unavailable" in str(call)
                for call in output.call_args_list
            )
        )
        self.assertEqual(parsed("kayla-harrison").fields["name"], "Kayla Harrison")

    def test_saved_continuations_keep_identity_and_change_bouts(self):
        for slug in (
            "alex-pereira",
            "israel-adesanya",
            "anderson-silva",
            "tank-abbott",
        ):
            first = parsed(slug)
            later = parse_profile(fixture(slug + "-page1"), first.following, TODAY)
            self.assertEqual(later.fields["source_id"], first.fields["source_id"])
            self.assertEqual(later.fields["url"], first.fields["url"])
            self.assertNotEqual(later.bouts.keys(), first.bouts.keys())
            self.assertTrue(later.following.endswith("?page=2"))

    def test_archived_draw_and_no_contest_cards(self):
        for name, slug, key, result in [
            ("jan-blachowicz-page1", "jan-blachowicz", "bout:10211", "draw"),
            ("ciryl-gane", "ciryl-gane", "bout:12277", "no contest"),
        ]:
            url = BASE + slug
            view = BeautifulSoup(fixture("history/" + name), "html.parser")
            bouts, state, following, _ = history(view, url, TODAY, {"url": url}, [])
            self.assertEqual(bouts[key][1], result)
            self.assertEqual(state, "complete")
            self.assertIsNotNone(following)

    def test_directory_next_terminal_limit_and_loop(self):
        first, second = fixture("directory"), fixture("directory1")
        url = DIRECTORY + "?page=1"
        outside = '<a href="/athlete/not-in-roster">Link</a>'
        client = Pages({DIRECTORY: first + outside, url: terminal(second)})
        report = {}
        self.assertEqual(len(discover(client, report)), 22)
        self.assertEqual(report["directory_pages"], 2)
        for html in [
            first,
            second.replace("?page=2", "?page=1"),
            "<h1>Error</h1>",
            '<div class="view-id-all_athletes"></div>',
        ]:
            with self.assertRaises(SourceError):
                discover(Pages({DIRECTORY: first, url: html}), {})
        with self.assertRaises(SourceError):
            discover(client, {}, limit=1)


class AccessTests(unittest.TestCase):
    def test_portrait_redirect_validation_and_non_image(self):
        client = Client(pace=0, budget=5)
        self.addCleanup(client.session.close)
        def response(code, **headers):
            r = MagicMock(status_code=code, headers=headers)
            r.__enter__.return_value = r
            return r
        start = "https://ufc.com/image.png?itok=abc"
        final = "https://www.ufc.com/image.png?itok=abc"
        sequences = [
            ([response(301, Location=final), response(200, **{"Content-Type":"image/png"})], True, 2),
            ([response(301, Location="https://evil.test/a")], False, 1),
            ([response(301, Location="http://ufc.com/a")], False, 1),
            ([response(301, Location=start)], False, 1),
            ([response(200, **{"Content-Type":"text/html"})], False, 1),
            ([response(302, Location=f"/image{i}.png") for i in range(6)], False, 6),
        ]
        for seq, available, count in sequences:
            with patch.object(client.session, "get", side_effect=seq) as get, patch("builtins.print"):
                result = diagnostic.probe_image(client, start)
            self.assertEqual(bool(result and result["available"]), available)
            self.assertEqual(get.call_count, count)
            self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_failed_response_evidence_keeps_exact_bytes(self):
        client = Client(pace=0, budget=5, attempts=1)
        self.addCleanup(client.session.close)
        r = requests.Response()
        r.status_code, r._content, r.encoding = 403, b"<h1>Access Denied</h1>\r\n", "utf-8"
        r.headers["Content-Type"] = "text/html"
        with tempfile.TemporaryDirectory() as tmp:
            client.evidence_dir = Path(tmp) / "responses"
            with patch.object(client.session, "get", return_value=r), self.assertRaises(SourceError):
                client.get(DIRECTORY)
            folder = Path(tmp) / "failure"
            metadata = json.loads(Path(client.save_failure(folder)).read_text())
            self.assertEqual((folder / metadata["body"]).read_bytes(), r.content)
            self.assertEqual(metadata["status"], 403)

    def test_http_limits_redirects_and_retry(self):
        def response(code, **headers):
            r = MagicMock(status_code=code, headers=headers, text="hello")
            r.__enter__.return_value = r
            return r

        c = Client(pace=0, budget=5)
        ok = response(200, **{"Content-Type": "text/html"})
        for seq in [
            [response(403)],
            [requests.exceptions.SSLError()],
            [response(302, Location="https://evil.test/")],
            [response(301, Location=DIRECTORY)],
            [response(429, **{"Retry-After": "500"})],
        ]:
            with (
                patch.object(c.session, "get", side_effect=seq) as get,
                self.assertRaises(SourceError),
            ):
                c.get(DIRECTORY)
            self.assertEqual(get.call_count, 1)
        seq = [
            response(302, Location="/athletes/all/"),
            response(503, **{"Retry-After": "0"}),
            ok,
        ]
        with patch.object(c.session, "get", side_effect=seq) as get:
            self.assertEqual(c.get(DIRECTORY), ("hello", DIRECTORY + "/"))
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
            self.assertEqual(len(get.call_args.kwargs["timeout"]), 2)
        with (
            patch.object(c.session, "get", side_effect=requests.Timeout),
            patch.object(c, "pause"),
            self.assertRaises(SourceError),
        ):
            c.get(DIRECTORY)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        # These exercise explicitly authorized local bootstrap, including in CI.
        env = patch.dict(os.environ, {"GITHUB_ACTIONS": "false"})
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        slug = "kayla-harrison"
        index = BeautifulSoup(terminal(fixture("directory")), "html.parser")
        cards = index.select(".node--view-mode-all-athletes-result")
        for card in cards[1:]:
            card.decompose()
        cards[0].select_one("a")["href"] = "/athlete/" + slug
        self.pages = Pages({DIRECTORY: str(index), BASE + slug: fixture(slug)})
        mock = patch.object(stat_scraper, "Client", return_value=self.pages)
        mock.start()
        self.addCleanup(mock.stop)

    def collect(self):
        return stat_scraper.main(self.root)

    def bootstrap(self):
        stage = self.collect()
        stat_scraper.main(self.root, reviewed=stage, bootstrap=True)
        return stage

    def test_fresh_bootstrap_noop_lock_and_api(self):
        stage = self.collect()
        with self.assertRaisesRegex(ValueError, "bootstrap"):
            stat_scraper.main(self.root, reviewed=stage)
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), self.assertRaisesRegex(ValueError, "unavailable"):
            stat_scraper.main(self.root, reviewed=stage, bootstrap=True)
        stat_scraper.main(self.root, reviewed=stage, bootstrap=True)
        before = publication.baseline(self.root)
        dbpath = self.root / publication.FILES[1]
        with closing(reader(dbpath)) as db:
            types = {
                r["name"]: r["type"] for r in db.execute("pragma table_info(fighters)")
            }
            self.assertEqual(types["reach"], "REAL")
            response = FighterDetailResponse.model_validate(
                app.get_fighter_by_id(1, db)
            )
            self.assertEqual(response.fighter.source_id, "136296")
            self.assertEqual(response.fighter.fighter_id, "ufc-136296")
            stat_scraper.main(self.root, publish_now=True)
            after = publication.baseline(self.root)
            self.assertEqual(before["output.csv"], after["output.csv"])
            self.assertNotEqual(
                before["collection-success.json"], after["collection-success.json"]
            )
            self.pages.data[BASE + "kayla-harrison"] = self.pages.data[
                BASE + "kayla-harrison"
            ].replace("4.29", "4.99")
            if os.name == "nt":
                # SQLite's Windows handles deny replacement while readers exist.
                with self.assertRaises(PermissionError):
                    stat_scraper.main(self.root, publish_now=True)
                self.assertTrue((self.root / ".refresh-undo").exists())
                db.close()
                with publication.locked(self.root):
                    publication.recover(self.root)
                self.assertEqual(publication.baseline(self.root), after)
                stat_scraper.main(self.root, publish_now=True)
            else:
                stat_scraper.main(self.root, publish_now=True)
                self.assertEqual(app.get_fighter_by_id(1, db)["fighter"]["slpm"], 4.29)
            with closing(reader(dbpath)) as fresh:
                self.assertEqual(
                    app.get_fighter_by_id(1, fresh)["fighter"]["slpm"], 4.99
                )
        with publication.locked(self.root), self.assertRaisesRegex(ValueError, "lock"):
            self.collect()

    def test_lock_process_exclusion_and_release(self):
        code = (
            "import sys; from pathlib import Path; "
            "from scraper.publication import locked; "
            "\nwith locked(Path(sys.argv[1])): print('acquired', flush=True)"
        )
        command = [sys.executable, "-c", code, str(self.root)]
        repo = Path(stat_scraper.__file__).resolve().parents[1]
        with publication.locked(self.root):
            blocked = subprocess.run(
                command, cwd=repo, capture_output=True, text=True, timeout=20
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("Another refresh holds the local lock", blocked.stderr)
        with self.assertRaises(KeyboardInterrupt):
            with publication.locked(self.root):
                raise KeyboardInterrupt()
        released = subprocess.run(
            command, cwd=repo, capture_output=True, text=True, timeout=20
        )
        self.assertEqual(released.returncode, 0, released.stderr)
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                code + "; import time; time.sleep(60)",
                str(self.root),
            ],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(holder.stdout.readline().strip(), "acquired")
            with self.assertRaisesRegex(ValueError, "lock"):
                with publication.locked(self.root):
                    pass
        finally:
            holder.kill()
            holder.communicate(timeout=20)
        with publication.locked(self.root):
            pass

    def test_unicode_candidate_and_readonly_path(self):
        self.pages.data[BASE + "kayla-harrison"] = fixture("kayla-harrison").replace(
            "Kayla Harrison", "Kayla Łukasz"
        )
        stage = self.collect()
        self.assertIn(
            "Kayla Łukasz", (stage / "output.csv").read_text(encoding="utf-8")
        )
        path = self.root / "snapshot Ł #%.db"
        publication.install(stage / "ufc_fighters.db", path)
        with closing(reader(path)) as db:
            self.assertEqual(
                db.execute("SELECT name FROM fighters").fetchone()[0], "Kayla Łukasz"
            )
            with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                db.execute("DELETE FROM fighters")
        path.unlink()  # Also verifies the connection has released its handle.

    def test_one_time_migration_and_numeric_id(self):
        with closing(sqlite3.connect(self.root / "ufc_fighters.db")) as db, db:
            db.execute("CREATE TABLE fighters (id INTEGER,name TEXT,url TEXT,dob TEXT)")
            db.execute(
                "INSERT INTO fighters VALUES(84,'Kayla Harrison','http://ufcstats.com/fighter-details/1af1170ed937cba7','Jul 02, 1990')"
            )
            db.execute(
                "INSERT INTO fighters VALUES(85,'Other','http://ufcstats.com/fighter-details/1111111111111111',NULL)"
            )
        (self.root / "output.csv").write_text(
            'Name,URL,DOB\nKayla Harrison,http://ufcstats.com/fighter-details/1af1170ed937cba7,"Jul 02, 1990"\n'
        )
        stage = self.bootstrap()
        data = validate(stage / "output.csv", stage / "ufc_fighters.db")
        self.assertEqual(list(data), ["1af1170ed937cba7"])
        with closing(reader(self.root / "ufc_fighters.db")) as db:
            self.assertEqual(
                app.get_fighter_by_id(84, db)["fighter"]["fighter_id"],
                "1af1170ed937cba7",
            )
            self.assertEqual(
                db.execute("select count(*) from identities").fetchone()[0], 2
            )

    def test_failures_preserve_last_success(self):
        self.bootstrap()
        before = publication.baseline(self.root)
        for url, broken in [
            (DIRECTORY, "<h1>captcha</h1>"),
            (BASE + "kayla-harrison", "<title>Access Denied</title>"),
        ]:
            with (
                patch.dict(self.pages.data, {url: broken}),
                self.assertRaises(SourceError),
            ):
                stat_scraper.main(self.root, publish_now=True)
            self.assertEqual(publication.baseline(self.root), before)
        with (
            patch.object(stat_scraper, "build", side_effect=sqlite3.DatabaseError),
            self.assertRaises(sqlite3.DatabaseError),
        ):
            stat_scraper.main(self.root, publish_now=True)
        self.assertEqual(publication.baseline(self.root), before)
        self.assertFalse(
            json.loads((self.root / "collection-failure.json").read_text())["published"]
        )

    def test_mismatch_and_stale_candidate_rejected(self):
        stage = self.collect()
        (stage / "output.csv").write_text(
            (stage / "output.csv").read_text().replace("4.29", "4.88")
        )
        with self.assertRaisesRegex(ValueError, "mismatch"):
            stat_scraper.main(self.root, reviewed=stage, bootstrap=True)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            validate(stage / "output.csv", stage / "ufc_fighters.db")
        self.bootstrap()
        with closing(sqlite3.connect(self.root / "ufc_fighters.db")) as db, db:
            db.execute("UPDATE fighters SET slpm=999")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            stat_scraper.main(self.root, publish_now=True)

    def test_cli_failure_and_stale_manifest(self):
        stage = self.bootstrap()
        before = publication.baseline(self.root)
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(stat_scraper.__file__).parents[1] / "run_scraper.py"),
                "--publish-candidate",
                str(stage),
                "--bootstrap",
            ],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("baseline", proc.stderr)
        self.assertEqual(publication.baseline(self.root), before)

    def test_manifest_and_database_required(self):
        stage = self.collect()
        report_path = stage / "report.json"
        report = json.loads(report_path.read_text())
        for change in [
            {"directory_complete": False},
            {"discovered": 2},
            {"failed": {"x": "error"}},
        ]:
            report_path.write_text(json.dumps(report | change))
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                stat_scraper.main(self.root, reviewed=stage, bootstrap=True)
        self.bootstrap()
        (self.root / "ufc_fighters.db").unlink()
        before = publication.baseline(self.root)
        with self.assertRaises(ValueError):
            stat_scraper.main(self.root, publish_now=True)
        self.assertEqual(publication.baseline(self.root), before)

    def test_replacement_and_restart_recovery(self):
        self.bootstrap()
        before = publication.baseline(self.root)
        self.pages.data[BASE + "kayla-harrison"] = fixture("kayla-harrison").replace(
            "4.29", "4.88"
        )
        stage = self.collect()
        install = publication.install
        for error in (OSError, KeyboardInterrupt):

            def fail(src, dest, error=error):
                if src == stage / "ufc_fighters.db":
                    raise error()
                return install(src, dest)

            with patch.object(publication, "install", fail), self.assertRaises(error):
                stat_scraper.main(self.root, reviewed=stage)
            if error is KeyboardInterrupt:
                with self.assertRaisesRegex(ValueError, "recover"):
                    self.collect()
                with publication.locked(self.root):
                    publication.recover(self.root)
            self.assertEqual(publication.baseline(self.root), before)


class IdentityTests(unittest.TestCase):
    def test_source_identity_audit_reports_duplicates_without_merging(self):
        p = dict(parsed("kayla-harrison").fields, requested_url=BASE + "kayla-harrison")
        other = dict(p, requested_url=BASE + "alias", slpm=9.5)
        audit = stat_scraper.identity_audit([p, other])
        self.assertEqual(audit["collected_urls"], 2)
        self.assertEqual(audit["distinct_source_identities"], 1)
        duplicate = audit["duplicate_source_identities"]["node:136296"]
        self.assertIn("slpm", duplicate["conflicting_fields"])
        self.assertEqual(len(duplicate["urls"]), 2)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            reconcile([dict(p), dict(p)], {}, {}, {})

    def test_name_dob_ambiguity_alias_and_url_change(self):
        p = parsed("kayla-harrison").fields
        reg = {
            k: {
                "fighter_id": k,
                "id": i,
                "url": BASE + k,
                "name": p["name"],
                "dob": p["dob"],
                "source_id": None,
            }
            for i, k in enumerate(["one", "two"], 1)
        }
        report = {}
        reconcile([p], reg, {}, report)
        self.assertEqual(report["ambiguous"][p["url"]], ["one", "two"])
        p["url"] = BASE + "changed"
        reconcile([p], reg, {}, report)
        self.assertEqual(p["fighter_id"], "ufc-136296")
        with self.assertRaises(ValueError):
            reconcile([p], reg, {p["source_id"]: "one"}, report)
        with self.assertRaises(ValueError):
            reconcile([p, p.copy()], reg, {}, report)
