"""Fetch a complete roster, validate fresh candidates, then replace local publications."""
import csv
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scraper.source import fetch_html, parse_index, profile_id, SourceError
from scraper.fighter_stats import get_fighter_details
from scraper.clean_data import clean_fighter_stats
from scraper.fighter_model import Fighter
from scraper.database import get_engine, init_database, add_fighters
from validate_export import validate

INDEX = 'http://ufcstats.com/statistics/fighters?char={}&page=all'
WORKERS = 4


def discover():
    urls = set()
    failures = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        jobs = {pool.submit(fetch_html, INDEX.format(c)): c for c in 'abcdefghijklmnopqrstuvwxyz'}
        for future in as_completed(jobs):
            letter = jobs[future]
            try:
                found = parse_index(future.result(), INDEX.format(letter))
                print(f'Index {letter}: {len(found)} profiles')
                urls.update(found)
            except Exception as error:
                failures.append(letter)
                print(f'Index fetch/parse failure [{letter}]: {error}', flush=True)
    print(f'Discovered IDs ({len(urls)}): {json.dumps(sorted(profile_id(u) for u in urls))}')
    if failures:
        raise SourceError(f'Discovery incomplete: failed indexes {failures}')
    if not urls:
        raise SourceError('Discovery empty: no fighter IDs; publication refused')
    return sorted(urls)


def collect_fighters():
    urls = discover()
    fighters, failures = [], []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        jobs = {pool.submit(get_fighter_details, url): url for url in urls}
        for future in as_completed(jobs):
            url = jobs[future]
            try:
                data = clean_fighter_stats([dict(future.result(), url=url)])[0]
                fighters.append(Fighter(**data))
            except Exception as error:
                failures.append(profile_id(url))
                print(f'Profile fetch/parse failure [{profile_id(url)}]: {error}', flush=True)
    print(f'Profiles: discovered={len(urls)} accepted={len(fighters)} failed={len(failures)} low_sample={sum(f.bad_sample for f in fighters)}')
    # Never interpret retrieval failures as roster removals or valid newcomers.
    if failures:
        raise SourceError(f'Incomplete profiles; publication refused. Failed IDs: {json.dumps(sorted(failures))}')
    return fighters


def write_csv(fighters, path):
    if not fighters:
        raise SourceError('Export empty: publication refused')
    rows = [f.to_dict() for f in sorted(fighters, key=lambda f: profile_id(f.url))]
    with open(path, 'x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f'Fresh candidate written: {path}; accepted rows={len(rows)}')


def meaningful_changes(previous, candidate):
    def read(path):
        with open(path, newline='', encoding='utf-8-sig') as stream:
            # Recency is derived from today's date, not a changed source statistic.
            return {profile_id(r['URL']): {k: v for k, v in r.items() if k not in {'URL', 'Most Recent Fight'}} for r in csv.DictReader(stream)}
    old, new = read(previous), read(candidate)
    changed = {identity: sorted(k for k in old[identity].keys() | new[identity].keys() if old[identity].get(k) != new[identity].get(k))
               for identity in old.keys() & new.keys() if old[identity] != new[identity]}
    report = {'added': sorted(new.keys() - old.keys()), 'removed': sorted(old.keys() - new.keys()), 'changed': changed}
    print('Meaningful changes by profile ID: ' + json.dumps(report, sort_keys=True))
    return any(report.values())


def save_to_database(fighters, db_path):
    engine = get_engine(str(db_path))
    try:
        init_database(engine)
        add_fighters(fighters, engine)
    finally:
        engine.dispose()


def validate_database_export(export, database):
    """Compare every exported field; historical DB-only rows remain permitted."""
    columns = dict(zip(
        ['Name', 'URL', 'Height', 'Weight', 'Weight Class', 'Reach', 'Stance', 'DOB',
         'SLpm', 'StrAcc', 'SApM', 'StrDef', 'TDAvg', 'TDAcc', 'TDDef', 'SubAvg',
         'Record', 'Most Recent Fight', 'FightCount', 'FightsInUFC', 'BadSample'],
        ['name', 'url', 'height', 'weight', 'weight_class', 'reach', 'stance', 'dob',
         'slpm', 'stracc', 'sapm', 'strdef', 'tdavg', 'tdacc', 'tddef', 'subavg',
         'record', 'most_recent_fight', 'fight_count', 'fights_in_ufc', 'bad_sample']))
    numeric = {'Height', 'Reach', 'SLpm', 'StrAcc', 'SApM', 'StrDef', 'TDAvg',
               'TDAcc', 'TDDef', 'SubAvg', 'Most Recent Fight', 'FightCount', 'FightsInUFC'}
    connection = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        connection.row_factory = sqlite3.Row
        with open(export, newline='', encoding='utf-8-sig') as stream:
            for row in csv.DictReader(stream):
                matches = connection.execute('SELECT * FROM fighters WHERE url = ?', (row['URL'],)).fetchall()
                if len(matches) != 1:
                    raise ValueError('CSV/SQLite mismatch: missing or duplicate fighter ' + row['URL'])
                for field, column in columns.items():
                    value, stored = row[field], matches[0][column]
                    if value == '':
                        equal = stored is None or stored == ''
                    elif field == 'BadSample':
                        equal = stored in (0, 1) and (value.lower() in {'true', '1'}) == bool(stored)
                    elif field in numeric:
                        equal = stored is not None and float(value) == float(stored)
                    else:
                        equal = value == stored
                    if not equal:
                        raise ValueError(f'CSV/SQLite mismatch: {row["URL"]} {field}')
    finally:
        connection.close()


def main(output_dir='.'):
    output_dir = Path(output_dir).resolve()
    published = output_dir / 'output.csv'
    database = output_dir / 'ufc_fighters.db'
    # Same filesystem for atomic per-file replacement; unique path prevents stale candidate reuse.
    with tempfile.TemporaryDirectory(prefix='.fighter-refresh-', dir=output_dir) as directory:
        stage = Path(directory)
        candidate = stage / 'candidate.csv'
        fighters = collect_fighters()
        collected_count = len(fighters)
        fighters = [f for f in fighters if not f.bad_sample]
        write_csv(fighters, candidate)
        validate(candidate, published)  # Retain the existing 95% minimum.
        success = stage / 'collection-success.json'
        success.write_text(json.dumps({'last_successful_collection': datetime.now(timezone.utc).isoformat(),
                                      'collected': collected_count, 'exported': len(fighters),
                                      'filtered': collected_count - len(fighters)}, indent=2) + '\n')
        if not meaningful_changes(published, candidate):
            validate_database_export(published, database)
            os.replace(success, output_dir / 'collection-success.json')
            print('Fresh scrape validated; no meaningful changes. Published files unchanged.')
            return
        candidate_db = stage / 'candidate.db'
        if database.exists():
            # SQLite backup also captures committed WAL content from a local API database.
            with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as source, sqlite3.connect(candidate_db) as target:
                source.backup(target)
        save_to_database(fighters, candidate_db)
        validate_database_export(candidate, candidate_db)
        # All retrieval, parsing, validation and DB work finish before touching published files.
        shutil.copy2(published, stage / 'previous.csv')
        if database.exists():
            shutil.copy2(database, stage / 'previous.db')
        try:
            os.replace(candidate_db, database)
            os.replace(candidate, published)
            os.replace(success, output_dir / 'collection-success.json')
        except OSError:
            os.replace(stage / 'previous.csv', published)
            if (stage / 'previous.db').exists():
                os.replace(stage / 'previous.db', database)
            elif database.exists():
                database.unlink()
            raise
        print('Validated CSV and database replaced; ready for workflow change detection.')


if __name__ == '__main__':
    main()
