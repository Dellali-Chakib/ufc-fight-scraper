import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import requests
import subprocess
import sys
import json
import sqlite3

from scraper.source import parse_index, fetch_html, SourceError
from scraper.fighter_stats import parse_fighter_details, get_fighter_details
from scraper.clean_data import clean_fighter_stats
from scraper.fighter_model import Fighter
from scraper import stat_scraper as scrape
from validate_export import validate

FIXTURES = Path(__file__).parent / 'tests/fixtures'
EXPECTED = {
    '4a28cb716c19157a': ('Stephen Thompson', '18-9-1', 4.09, False),
    '519e4fe37ce9ff75': ('Drew Dober', '29-16-0', 4.40, False),
    '787bb1f087ccff8a': ('Ciryl Gane', '15-2-0', 5.90, False),
    '74939a16c7b56f33': ('Juan Diaz', '17-1-1', 5.25, True),
    '438d497617ecb16e': ('Samuel Sanches', '11-2-0', 5.00, True),
}
CHALLENGE = '<html><p>Checking your browser…</p></html>'
EMPTY_INDEX = '<h2 class="b-content__title">Fighters</h2><table class="b-statistics__table"><thead><tr>'+''.join(f'<th>{h}</th>' for h in ['First','Last','W','L','D'])+'</tr></thead><tbody><tr><td></td></tr></tbody></table>'


def fighters():
    result=[]
    for identity in EXPECTED:
        url='http://ufcstats.com/fighter-details/'+identity
        raw=parse_fighter_details((FIXTURES/(identity+'.html')).read_text(),url)
        result.append(Fighter(**clean_fighter_stats([dict(raw,url=url)])[0]))
    return result


class RefreshTests(unittest.TestCase):
    def test_noop_rejects_inconsistent_or_missing_database_without_success(self):
        values = [f for f in fighters() if not f.bad_sample]
        for fault in ('stat', 'recency', 'missing_row', 'missing_db', 'corrupt_db'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                scrape.write_csv(values, root/'output.csv')
                if fault != 'missing_db':
                    scrape.save_to_database(values, root/'ufc_fighters.db')
                    if fault == 'corrupt_db':
                        (root/'ufc_fighters.db').write_bytes(b'corrupt')
                    else:
                        with sqlite3.connect(root/'ufc_fighters.db') as db:
                            db.execute({'stat': 'UPDATE fighters SET slpm=999',
                                        'recency': 'UPDATE fighters SET most_recent_fight=999',
                                        'missing_row': 'DELETE FROM fighters'}[fault])
                (root/'collection-success.json').write_bytes(b'previous success')
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                with patch.object(scrape, 'collect_fighters', return_value=values):
                    with self.assertRaises((ValueError, sqlite3.Error)):
                        scrape.main(root)
                self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_cli_failure_preserves_publication_and_success_record(self):
        entry = Path(__file__).parent / 'run_scraper.py'
        for html in (CHALLENGE, EMPTY_INDEX):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                originals = {'output.csv': b'old csv', 'ufc_fighters.db': b'old db',
                             'collection-success.json': b'old success'}
                for name, data in originals.items():
                    (root / name).write_bytes(data)
                code = ('import sys,runpy; from unittest.mock import patch; '
                        f'sys.path.insert(0,{str(entry.parent)!r}); '
                        f'p=patch("scraper.stat_scraper.fetch_html",return_value={html!r}); '
                        f'p.start(); runpy.run_path({str(entry)!r},run_name="__main__")')
                result = subprocess.run([sys.executable, '-B', '-c', code], cwd=root,
                                        capture_output=True, text=True, timeout=20)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('publication stopped', result.stderr)
                for name, data in originals.items():
                    self.assertEqual((root / name).read_bytes(), data)

    def test_permanent_http_error_is_not_retried(self):
        response = requests.Response()
        response.status_code = 403
        with patch('scraper.source.requests.get', side_effect=requests.HTTPError(response=response)) as get:
            with self.assertRaises(SourceError): fetch_html('http://ufcstats.com/')
            self.assertEqual(get.call_count, 1)

    def test_source_contract_and_timeouts(self):
        with self.assertRaisesRegex(SourceError,'Challenge'): parse_index(CHALLENGE,'index')
        with self.assertRaisesRegex(SourceError,'structure'): parse_index('<html>Error</html>','index')
        self.assertEqual(parse_index(EMPTY_INDEX,'index'),[])
        url='http://ufcstats.com/fighter-details/74939a16c7b56f33'
        with self.assertRaisesRegex(SourceError,'Challenge'): parse_fighter_details(CHALLENGE,url)
        with self.assertRaisesRegex(SourceError,'identity'): parse_fighter_details('<html>ok</html>',url)
        with patch('scraper.source.requests.get') as get:
            response = requests.Response()
            response.status_code = 503
            get.return_value.raise_for_status.side_effect=requests.HTTPError('503', response=response)
            with patch('scraper.source.time.sleep'), self.assertRaisesRegex(SourceError,'HTTP fetch failed'): fetch_html(url)
            self.assertEqual(get.call_count,3)
            self.assertEqual(get.call_args.kwargs['timeout'],(5,20))
        with patch('scraper.source.requests.get',side_effect=requests.Timeout('timed out')), patch('scraper.source.time.sleep'):
            with self.assertRaises(SourceError): fetch_html(url)
        with patch('scraper.fighter_stats.fetch_html',return_value=CHALLENGE):
            with self.assertRaises(SourceError): get_fighter_details(url)

    def test_old_publication_survives_challenge_zero_discovery_and_empty_export(self):
        for html in [CHALLENGE, EMPTY_INDEX]:
            with self.subTest(html=html), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); (root/'output.csv').write_bytes(b'old publication'); (root/'ufc_fighters.db').write_bytes(b'old db')
                with patch.object(scrape,'fetch_html',return_value=html), self.assertRaises(SourceError): scrape.main(root)
                self.assertEqual((root/'output.csv').read_bytes(),b'old publication')
                self.assertEqual((root/'ufc_fighters.db').read_bytes(),b'old db')
        with tempfile.TemporaryDirectory() as directory, patch.object(scrape,'collect_fighters',return_value=[]):
            path=Path(directory)/'output.csv';path.write_bytes(b'old publication')
            with self.assertRaisesRegex(SourceError,'Export empty'): scrape.main(directory)
            self.assertEqual(path.read_bytes(),b'old publication')

    def test_profile_failures_abort_instead_of_creating_newcomers(self):
        url='http://ufcstats.com/fighter-details/74939a16c7b56f33'
        with patch.object(scrape,'discover',return_value=[url]), patch.object(scrape,'get_fighter_details',side_effect=SourceError('bad profile')):
            with self.assertRaisesRegex(SourceError,'Incomplete profiles'): scrape.collect_fighters()

    def test_diagnosis_profiles_and_low_sample_export(self):
        values=fighters()
        for f in values:
            self.assertEqual((f.name,f.record,f.slpm,f.bad_sample),EXPECTED[f.url.rsplit('/',1)[-1]])
        values = [f for f in values if not f.bad_sample]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);baseline=root/'output.csv';scrape.write_csv(values,baseline)
            candidate=root/'fresh.csv';scrape.write_csv(values,candidate);validate(candidate,baseline)
            with candidate.open() as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual(len(rows),3)
            self.assertEqual(sum(r['BadSample']=='True' for r in rows),0)
            # Change an actual source stat to force the staged DB + CSV replacement path.
            values[0].slpm=4.10
            with patch.object(scrape,'collect_fighters',return_value=values): scrape.main(root)
            self.assertTrue((root/'ufc_fighters.db').exists())
            with baseline.open() as stream:
                refreshed={r['Name']:r for r in csv.DictReader(stream)}
            self.assertEqual(refreshed['Stephen Thompson']['SLpm'], '4.1')
            self.assertNotIn('Juan Diaz', refreshed)

    def test_noop_ignores_order_and_elapsed_days_and_keeps_both_files(self):
        values=[f for f in fighters() if not f.bad_sample]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);scrape.write_csv(values,root/'output.csv')
            with (root/'output.csv').open(newline='') as stream:
                reader=csv.DictReader(stream); rows=list(reader); headers=reader.fieldnames
            with (root/'output.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=headers);writer.writeheader();writer.writerows(reversed(rows))
            before=(root/'output.csv').read_bytes()
            scrape.save_to_database(values, root/'ufc_fighters.db')
            before_db=(root/'ufc_fighters.db').read_bytes()
            for f in values: f.most_recent_fight+=1
            with patch.object(scrape,'collect_fighters',return_value=values): scrape.main(root)
            self.assertEqual((root/'output.csv').read_bytes(),before)
            self.assertEqual((root/'ufc_fighters.db').read_bytes(),before_db)
            metadata = json.loads((root/'collection-success.json').read_text())
            self.assertEqual(metadata['exported'], len(values))
            self.assertIn('last_successful_collection', metadata)

    def test_drop_and_database_failure_leave_publication_intact(self):
        values=[f for f in fighters() if not f.bad_sample]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);scrape.write_csv(values,root/'output.csv'); before=(root/'output.csv').read_bytes()
            with patch.object(scrape,'collect_fighters',return_value=values[:1]), self.assertRaisesRegex(ValueError,'roster drop'): scrape.main(root)
            self.assertEqual((root/'output.csv').read_bytes(),before)
            values[0].slpm+=1
            with patch.object(scrape,'collect_fighters',return_value=values), patch.object(scrape,'save_to_database',side_effect=RuntimeError('db failed')), self.assertRaises(RuntimeError): scrape.main(root)
            self.assertEqual((root/'output.csv').read_bytes(),before)

    def test_replacement_error_restores_both_publications(self):
        values=[f for f in fighters() if not f.bad_sample]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);scrape.write_csv(values,root/'output.csv')
            scrape.save_to_database(values,root/'ufc_fighters.db')
            before={name:(root/name).read_bytes() for name in ['output.csv','ufc_fighters.db']}
            values[0].slpm+=1
            replace=scrape.os.replace
            def fail_csv(source,destination):
                if Path(source).name=='candidate.csv': raise OSError('replacement failed')
                return replace(source,destination)
            with patch.object(scrape,'collect_fighters',return_value=values), patch.object(scrape.os,'replace',side_effect=fail_csv), self.assertRaises(OSError):
                scrape.main(root)
            for name,data in before.items(): self.assertEqual((root/name).read_bytes(),data)

if __name__=='__main__': unittest.main()
