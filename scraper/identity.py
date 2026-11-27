"""Exact identity reconciliation, including tombstones for absent athletes."""

import csv
import re
import unicodedata
import uuid
from collections import defaultdict
from contextlib import closing
from datetime import datetime

from .database import reader


def name_key(name):
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", name.casefold())
            if not unicodedata.combining(c)
        ).split()
    )


def legacy(row):
    match = re.fullmatch(
        r"https?://(?:www\.)?ufcstats\.com/fighter-details/([a-f0-9]{16})/?", row["url"]
    )
    if not match:
        raise ValueError(f"Invalid legacy URL {row['url']}")
    dob = None if row["dob"] == "--" else row["dob"]
    if dob:
        dob = datetime.strptime(dob, "%b %d, %Y").date().isoformat()
    return {
        "fighter_id": match[1],
        "id": row["id"],
        "url": row["url"],
        "name": row["name"],
        "dob": dob or None,
        "source_id": None,
        "favorite_aliases": None,
    }


def previous_registry(root):
    db_path = root / "ufc_fighters.db"
    registry = {}
    if db_path.exists():
        with closing(reader(db_path)) as db:
            current = db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='identities'"
            ).fetchone()
            sql = (
                "SELECT * FROM identities"
                if current
                else "SELECT id,url,name,dob FROM fighters"
            )
            for row in db.execute(sql):
                entry = dict(row) if current else legacy(row)
                registry[entry["fighter_id"]] = entry
    csv_path = root / "output.csv"
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                if "FighterID" in row:
                    if row["FighterID"] not in registry:
                        raise ValueError(
                            "New-format CSV requires matching database registry"
                        )
                else:
                    entry = legacy(
                        {
                            "url": row["URL"],
                            "name": row["Name"],
                            "dob": row["DOB"],
                            "id": None,
                        }
                    )
                    prior = registry.setdefault(entry["fighter_id"], entry)
                    if (
                        name_key(prior["name"]) != name_key(entry["name"])
                        or prior["dob"]
                        and entry["dob"]
                        and prior["dob"] != entry["dob"]
                    ):
                        raise ValueError(
                            f"CSV/database identity conflict: {entry['fighter_id']}"
                        )
    return registry


def reconcile(profiles, registry, aliases, report):
    by_name = defaultdict(list)
    by_source, by_url = {}, {}
    for fid, old in registry.items():
        by_name[name_key(old["name"])].append(old)
        if old["source_id"]:
            by_source[old["source_id"]] = fid
        by_url[old["url"]] = fid
    next_id = max((r["id"] or 0 for r in registry.values()), default=0) + 1
    seen = set()
    report.update(matched=[], new=[], ambiguous={}, unmatched=[])
    old_ids = set(registry)
    for p in profiles:
        sid, url = p.get("source_id"), p["url"]
        forced_ids = {aliases[key] for key in (sid, url) if key in aliases}
        if len(forced_ids) > 1:
            raise ValueError(f"Conflicting reviewed mappings for {url}")
        forced = next(iter(forced_ids), None)
        candidates = {x for x in [by_source.get(sid), by_url.get(url), forced] if x}
        if len(candidates) > 1 or forced and forced not in registry:
            raise ValueError(f"Conflicting identity mappings for {url}: {candidates}")
        fid = next(iter(candidates), None)
        matches = by_name[name_key(p["name"])]
        if not fid:
            exact = [
                r
                for r in matches
                if p.get("dob")
                and p["dob"] == r["dob"]
                and not (sid and r["source_id"])
            ]
            if len(exact) == 1:
                fid = exact[0]["fighter_id"]
            elif matches:
                report["ambiguous"][url] = [r["fighter_id"] for r in matches]
        if fid and not forced and not (sid and registry[fid]["source_id"] == sid):
            old = registry[fid]
            if name_key(old["name"]) != name_key(p["name"]) or (
                p.get("dob") and old["dob"] and old["dob"] != p["dob"]
            ):
                raise ValueError(f"Conflicting identity evidence at {url}")
        if (
            fid
            and not forced
            and p.get("dob")
            and registry[fid]["dob"]
            and p["dob"] != registry[fid]["dob"]
        ):
            raise ValueError(f"Conflicting DOB for mapped identity at {url}")
        if fid and sid and registry[fid]["source_id"] not in (None, sid):
            raise ValueError(f"Source ID conflict at {url}")
        if not fid:
            fid = (
                "ufc-" + sid
                if sid
                else "ufc-" + uuid.uuid5(uuid.NAMESPACE_URL, url).hex
            )
        if fid in seen:
            raise ValueError(f"Duplicate fighter/source ID at {url}: {fid}")
        seen.add(fid)
        report["matched" if fid in old_ids else "new"].append(fid)
        old = registry.get(fid, {})
        num = old.get("id")
        if num is None:
            num, next_id = next_id, next_id + 1
        # Historic clients persisted numeric IDs and ASCII name slugs in localStorage.
        favorite_aliases = set((old.get("favorite_aliases") or "").split())
        favorite_aliases.add(str(num))
        for name in [old.get("name"), p["name"]]:
            if name:
                favorite_aliases.add(re.sub(r"[^a-z0-9]+", "-", name.lower()))
        p["favorite_aliases"] = " ".join(sorted(favorite_aliases))
        registry[fid] = {
            "favorite_aliases": p["favorite_aliases"],
            "fighter_id": fid,
            "id": num,
            "source_id": sid or old.get("source_id"),
            "url": url,
            "name": p["name"],
            "dob": p.get("dob") or old.get("dob"),
        }
        p["fighter_id"] = fid
    report["unmatched"] = sorted(old_ids - seen)
