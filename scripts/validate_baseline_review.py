"""Read-only validation of an archived baseline candidate. Never collect or publish."""
import argparse
import json
from contextlib import closing
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scraper.contract import VERSION
from scraper.database import reader
from scraper.identity import previous_registry, validate_favorite_aliases
from scraper.publication import baseline, digest
from scraper.refresh_state import SIDECARS, load
from schemas import FighterListResponse
from validate_export import validate


def check(root, candidate):
    report = json.loads((candidate / 'report.json').read_text(encoding='utf-8'))
    rows = validate(candidate / 'output.csv', candidate / 'ufc_fighters.db')
    state, times = load(candidate, rows)
    if report['schema_version'] != VERSION or report['source'] != 'UFC.com':
        raise ValueError('Unexpected candidate source/schema')
    if report['baseline'] != baseline(root):
        raise ValueError('Candidate baseline changed; regenerate against the current baseline')
    if report['aliases_hash'] != digest(root / 'identity-aliases.json'):
        raise ValueError('Reviewed identity configuration changed')
    if report['hashes'] != {n: digest(candidate / n) for n in ('output.csv', 'ufc_fighters.db')}:
        raise ValueError('Candidate dataset manifest mismatch')
    if report['sidecar_hashes'] != {n: digest(candidate / n) for n in SIDECARS}:
        raise ValueError('Candidate sidecar manifest mismatch')
    if (not report['directory_complete'] or not report['directory_pages'] or report['failed']
            or len(rows) != report['discovered'] or len(rows) != report['successful']):
        raise ValueError('Incomplete candidate')
    for path, expected in report.get('implementation_hashes', {}).items():
        if digest(root / path) != expected:
            raise ValueError(f'Candidate implementation changed: {path}')
    aliases = json.loads((root / 'identity-aliases.json').read_text(encoding='utf-8'))
    validate_favorite_aliases(rows, previous_registry(root), aliases)
    # The installed generation must also remain stable on subsequent refreshes.
    validate_favorite_aliases(rows, previous_registry(candidate), aliases)
    with closing(reader(candidate / 'ufc_fighters.db')) as db:
        payload = {'count': len(rows), 'fighters': [dict(r) for r in db.execute('SELECT * FROM fighters ORDER BY id')]}
        FighterListResponse.model_validate(payload)
    return {'status': 'validated review candidate', 'fighters': len(rows),
            'generation': state['generation'], 'fighter_source_records': len(times['fighters']),
            'ambiguous_identities_kept_separate': len(report['migration']['ambiguous']),
            'source_fetch_range': report['source_fetch_range'], 'read_only': True,
            'live_requests': 0, 'bootstrap_called': False, 'published': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--summary', type=Path)
    args = parser.parse_args()
    result = check(args.root.resolve(), args.candidate.resolve())
    text = json.dumps(result, indent=2) + '\n'
    if args.summary:
        args.summary.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
