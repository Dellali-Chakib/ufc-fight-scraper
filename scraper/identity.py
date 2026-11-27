"""Exact identity reconciliation, including tombstones for absent athletes."""

import csv
import copy
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


def favorite_slug(name):
    """The exact key produced by the legacy frontend, not identity evidence."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower())


def filter_favorite_aliases(profiles, registry, previous_names):
    """Reserve names belonging to any competing identity, even tombstones.

    A non-exported or unresolved legacy identity must still prevent a unique
    visible display name from claiming its saved favorite key.
    """
    names = [*previous_names, *((fid, row["name"]) for fid, row in registry.items())]
    name_owners, key_owners = defaultdict(set), defaultdict(set)
    for fid, name in names:
        name_owners[name_key(name)].add(fid)
        key_owners[favorite_slug(name)].add(fid)
    blocked = {favorite_slug(name) for _, name in names
               if len(name_owners[name_key(name)]) > 1}
    for p in profiles:
        for key in (p.get("favorite_aliases") or "").split():
            key_owners[key].add(p["fighter_id"])
    for p in profiles:
        fid = p["fighter_id"]
        keys = {key for key in (p.get("favorite_aliases") or "").split()
                if key not in blocked and key_owners[key] == {fid}}
        p["favorite_aliases"] = " ".join(sorted(keys)) or None
        registry[fid]["favorite_aliases"] = p["favorite_aliases"]


def reconcile(profiles, registry, aliases, report):
    previous_names = [(fid, row["name"]) for fid, row in registry.items()]
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
        # Only a corroborated/reviewed legacy identity may supply migration
        # aliases. A new UFC.com source identity has no legacy name mapping.
        # Do not carry the former name-only policy forward for ufc-* IDs.
        favorite_aliases = set()
        if old and re.fullmatch(r"[a-f0-9]{16}", fid):
            favorite_aliases.update((old.get("favorite_aliases") or "").split())
            if old.get("id") is not None:
                favorite_aliases.add(str(old["id"]))
            # Only the original legacy record proves a historic name key.
            # Later source display names must not create new legacy aliases.
            if not old.get("source_id"):
                favorite_aliases.add(favorite_slug(old["name"]))
        p["favorite_aliases"] = " ".join(sorted(favorite_aliases)) or None
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
    filter_favorite_aliases(profiles, registry, previous_names)
    report["unmatched"] = sorted(old_ids - seen)


def validate_favorite_aliases(rows, registry, aliases):
    """Reject stale candidates created under the former name-only policy."""
    profiles = [row.model_dump(mode="json") for row in sorted(rows.values(), key=lambda row: row.url)]
    expected = copy.deepcopy(registry)
    reconcile(profiles, expected, aliases, {})
    for profile in profiles:
        row = rows.get(profile["fighter_id"])
        if row is None or row.favorite_aliases != profile["favorite_aliases"]:
            raise ValueError("FavoriteAliases violate supported identity mappings; regenerate candidate")
