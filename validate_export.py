"""Fail closed before publishing a CSV; no third-party dependencies."""
import argparse
import csv
import re
import sys

REQUIRED = {'Name', 'URL', 'Height', 'Weight', 'Weight Class', 'Reach', 'Stance',
            'SLpm', 'StrAcc', 'SApM', 'StrDef', 'TDAvg', 'TDAcc', 'TDDef', 'SubAvg', 'Record', 'BadSample'}
PROFILE = re.compile(r'https?://(?:www\.)?ufcstats\.com/fighter-details/([0-9a-f]{16})/?', re.I)
# A weekly roster should be nearly stable. 5% permits routine corrections while
# rejecting partial runs; deliberate larger removals require reviewing this gate.
MIN_RETAINED = 0.95


def usable_ids(path):
    with open(path, newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source, strict=True)
        headers = reader.fieldnames or []
        if not REQUIRED.issubset(headers) or len(headers) != len(set(headers)):
            raise ValueError(f'{path}: missing required or duplicate headers')
        ids = set()
        for row in reader:
            if None in row or None in row.values():
                raise ValueError(f'{path}:{reader.line_num}: malformed row width')
            match = PROFILE.fullmatch(row['URL'].strip())
            name = row['Name'].strip()
            if not name or not any(c.isalpha() for c in name) or name.lower() in {'unknown', 'none', 'null', 'n/a'} or not match:
                raise ValueError(f'{path}:{reader.line_num}: unusable name or profile URL')
            if row['BadSample'].strip().lower() not in {'false', '0'}:
                raise ValueError(f'{path}:{reader.line_num}: bad sample or invalid BadSample flag')
            identity = match[1].lower()
            if identity in ids:
                raise ValueError(f'{path}:{reader.line_num}: duplicate profile ID {identity}')
            ids.add(identity)
        if not ids:
            raise ValueError(f'{path}: empty roster')
        return ids


def validate(candidate, previous):
    current, baseline = usable_ids(candidate), usable_ids(previous)
    if len(current) < len(baseline) * MIN_RETAINED:
        raise ValueError(f'roster drop: {len(baseline)} -> {len(current)}; must retain at least {MIN_RETAINED:.0%}')
    print(f'CSV validation passed: {len(current)} unique usable fighters (previous {len(baseline)})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate')
    parser.add_argument('previous')
    args = parser.parse_args()
    try:
        validate(args.candidate, args.previous)
    except (ValueError, csv.Error, OSError) as error:
        print(f'CSV publication rejected: {error}', file=sys.stderr)
        sys.exit(1)
