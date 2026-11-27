"""Immutable publication snapshots. Each reader opens the current file afresh."""

import sqlite3
from contextlib import closing
from pathlib import Path

from .contract import HEADERS

TYPES = dict.fromkeys(HEADERS, "TEXT")
TYPES.update(
    dict.fromkeys(
        [
            "height",
            "weight",
            "reach",
            "slpm",
            "stracc",
            "sapm",
            "strdef",
            "tdavg",
            "tdacc",
            "tddef",
            "subavg",
        ],
        "REAL",
    )
)
TYPES.update(
    dict.fromkeys(
        ["most_recent_fight", "fight_count", "fights_in_ufc", "bad_sample"], "INTEGER"
    )
)


def reader(path):
    uri = Path(path).resolve().as_uri()
    # SQLite rejects non-local URI authorities in its default build. Keep UNC
    # hosts in the path (file:////server/share), with an empty URI authority.
    if uri.startswith("file://") and not uri.startswith("file:///"):
        uri = "file:////" + uri[len("file://") :]
    db = sqlite3.connect(uri + "?mode=ro", uri=True, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def build(path, rows, registry):
    if path.exists():
        raise ValueError("Stage database already exists")
    with closing(sqlite3.connect(path)) as db, db:
        columns = ", ".join(f"{key} {kind}" for key, kind in TYPES.items())
        db.execute(
            f"CREATE TABLE fighters (id INTEGER PRIMARY KEY, {columns}, UNIQUE(fighter_id), UNIQUE(source_id), UNIQUE(url))"
        )
        db.execute("CREATE INDEX fighter_names ON fighters(name)")
        db.execute(
            "CREATE TABLE identities (fighter_id TEXT PRIMARY KEY, id INTEGER UNIQUE, source_id TEXT UNIQUE, url TEXT UNIQUE, name TEXT, dob TEXT, favorite_aliases TEXT)"
        )
        db.executemany(
            "INSERT INTO identities VALUES (:fighter_id,:id,:source_id,:url,:name,:dob,:favorite_aliases)",
            registry.values(),
        )
        params = ",".join(":" + k for k in HEADERS)
        db.executemany(
            f"INSERT INTO fighters VALUES (:id,{params})",
            (
                dict(f.model_dump(mode="json"), id=registry[f.fighter_id]["id"])
                for f in rows
            ),
        )
