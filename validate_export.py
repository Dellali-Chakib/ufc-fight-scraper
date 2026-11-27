"""Validate a staged schema-v2 CSV and its paired SQLite snapshot."""

import argparse
import csv
from contextlib import closing
from pathlib import Path

from scraper.contract import HEADERS, Fighter
from scraper.database import reader


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        rows = csv.DictReader(stream, strict=True)
        if rows.fieldnames != list(HEADERS.values()):
            raise ValueError("Missing, duplicate or reordered CSV headers")
        result = {}
        urls, sources = set(), set()
        for raw in rows:
            if None in raw or None in raw.values():
                raise ValueError("Malformed CSV row width")
            if raw["BadSample"].lower() not in {"", "true", "false", "1", "0"}:
                raise ValueError(f"Invalid BadSample at CSV line {rows.line_num}")
            f = Fighter.model_validate({k: v or None for k, v in raw.items()})
            if (
                f.url in urls
                or f.fighter_id in result
                or f.source_id
                and f.source_id in sources
            ):
                raise ValueError(f"Duplicate profile or identity: {f.url}")
            result[f.fighter_id] = f
            urls.add(f.url)
            sources.add(f.source_id)
        if not result:
            raise ValueError("Empty roster")
        return result


def validate(csv_path, db_path):
    rows = read_csv(csv_path)
    with closing(reader(db_path)) as db:
        found = set()
        registry = {r["fighter_id"]: r for r in db.execute("SELECT * FROM identities")}
        for row in db.execute("SELECT * FROM fighters"):
            fid = row["fighter_id"]
            expected = rows.get(fid)
            identity = registry.get(fid)
            if (
                not expected
                or not identity
                or any(identity[k] != row[k] for k in ("id", "url", "name"))
                or (row["source_id"] and identity["source_id"] != row["source_id"])
            ):
                raise ValueError(f"Database identity mismatch: {fid}")
            for key, val in expected.model_dump(mode="json").items():
                if row[key] != val:
                    raise ValueError(f"CSV/SQLite mismatch: {fid} {key}")
            found.add(fid)
        if found != rows.keys():
            raise ValueError("CSV/SQLite roster mismatch")
    return rows


def changes(old, new):
    shared = old.keys() & new.keys()
    changed = {}
    for fid in sorted(shared):
        diff = {
            k: [getattr(old[fid], k), getattr(new[fid], k)]
            for k in HEADERS
            if k != "most_recent_fight" and getattr(old[fid], k) != getattr(new[fid], k)
        }
        if diff:
            changed[fid] = diff
    return {
        "added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()),
        "changed": changed,
    }


def coverage(rows):
    return {
        k: sum(getattr(row, k) is not None for row in rows.values()) for k in HEADERS
    }


def guard(old, new):
    if len(old.keys() & new.keys()) < 0.95 * len(old) or len(new) > 1.25 * len(old):
        raise ValueError("Roster retention/growth gate")
    before, after = coverage(old), coverage(new)
    for k in HEADERS:
        if k != "warnings" and after[k] / len(new) < 0.75 * before[k] / len(old):
            raise ValueError(f"Coverage collapse: {k}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv")
    parser.add_argument("database")
    args = parser.parse_args()
    print(f"Validated {len(validate(args.csv, args.database))} fighters")
