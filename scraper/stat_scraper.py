"""Collect full candidates and validate them under the shared refresh lock."""

import csv
import json
import os
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from collections import Counter, defaultdict, deque
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from validate_export import changes, coverage, guard, validate

from .contract import HEADERS, VERSION, Fighter
from .database import build, reader
from .directory import discover
from .fighter_stats import parse_profile, put
from .identity import previous_registry, reconcile, validate_favorite_aliases
from .publication import FILES, baseline, digest, locked, recover, replace, write_json
from .source import Client, SourceError
from .runtime import Cancelled, Runtime

ALIASES = Path(__file__).resolve().parents[1] / "identity-aliases.json"


def now():
    return datetime.now(UTC).isoformat()


def observed_eta(completions, completed, total, current):
    """Recent completions adapt when a cached prefix becomes network work."""
    if completed >= total:
        return 0.0
    recent = list(completions)[-41:]
    if len(recent) < 2 or current <= recent[0]:
        return None
    return (total - completed) * (current - recent[0]) / (len(recent) - 1)


def collect_profile(client, url, today, history_log=None):
    if isinstance(client, Runtime):
        client.begin_profile(url)
    seen, signatures, bouts = set(), set(), {}
    warnings = []
    fields = None
    state = "complete"
    while url:
        if url in seen or len(signatures) >= 100:
            raise SourceError(f"History loop or limit at {url}")
        html, final = client.get(url)
        parsing = time.perf_counter()
        try:
            parsed = parse_profile(html, final, today)
        except ValueError as exc:
            raise SourceError(
                f"Invalid profile response (HTTP 200) at {final}: {exc}"
            ) from exc
        finally:
            if isinstance(client, Runtime):
                client.metrics.add("profile_parse_seconds", time.perf_counter() - parsing)
        if fields is None:
            fields = parsed.fields
            warnings.extend(parsed.warnings)
        else:
            if any(
                parsed.fields.get(k) != fields.get(k)
                for k in ("url", "source_id", "name")
            ):
                raise SourceError(f"History switched athlete at {url}")
            if parsed.history_status == "unknown":
                raise SourceError(f"Missing continuation history at {url}")
            warnings.extend(w for w in parsed.warnings if w["field"] == "history")
        sig = parsed.signature
        if final in seen or sig in signatures:
            raise SourceError(f"Repeated history page at {url}")
        if history_log is not None:
            history_log.append(
                {
                    "url": final,
                    "recognized_completed_bouts": len(parsed.bouts),
                    "page_status": parsed.history_status,
                    "next": parsed.following,
                }
            )
        seen.update((url, final))
        signatures.add(sig)
        for k, v in parsed.bouts.items():
            put(bouts, k, v)
        if parsed.history_status != "complete":
            state = parsed.history_status
        url = parsed.following
    if isinstance(client, Runtime):
        cohort = client.mixed_history_cohort()
        if cohort:
            state = "incomplete"
            warnings.append({"field": "history", "reason": "mixed source-fetch cohort; refresh athlete",
                             "fetch_range": cohort})
    count = len(bouts) if state == "complete" else None
    latest = (
        max((v[0] for v in bouts.values()), default=None)
        if state == "complete"
        else None
    )
    fields.update(
        history_status=state,
        fights_in_ufc=count,
        bad_sample=None if count is None else count < 3,
        last_fight_date=latest,
        most_recent_fight=(today - latest).days if latest else None,
        warnings=", ".join(sorted({w["field"] for w in warnings})) or None,
    )
    return fields, warnings


def initial(root):
    path = root / "output.csv"
    if not path.exists():
        if (root / "ufc_fighters.db").exists():
            with closing(reader(root / "ufc_fighters.db")) as db:
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='identities'"
                ).fetchone():
                    raise ValueError("Missing CSV for existing UFC.com publication")
        return True
    with path.open(newline="", encoding="utf-8-sig") as f:
        return "FighterID" not in next(csv.reader(f))


def migration_changes(path, data):
    old = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as file:
            old = {
                row["URL"].rstrip("/").split("/")[-1]: row
                for row in csv.DictReader(file)
            }
    changed = {}
    for fid in sorted(data.keys() & old.keys()):
        diff = {}
        for key in (
            "slpm",
            "sapm",
            "stracc",
            "strdef",
            "tdavg",
            "tdacc",
            "tddef",
            "subavg",
            "record",
        ):
            header = HEADERS[key]
            if header not in old[fid]:
                continue
            before = old[fid][header] or None
            if before and key != "record":
                before = float(before)
            after = getattr(data[fid], key)
            if before != after:
                diff[header] = [before, after]
        if diff:
            changed[fid] = diff
    return {
        "added": sorted(data.keys() - old.keys()),
        "removed": sorted(old.keys() - data.keys()),
        "changed": changed,
    }


def collect_profiles(client, urls, today, stage, report):
    """Only this coordinator writes reports; at most `workers` tasks are queued."""
    completed, pending = {}, {}
    completions = deque(maxlen=41)
    remaining = iter(urls)
    pool = ThreadPoolExecutor(max_workers=client.workers, thread_name_prefix="ufc")
    last_progress = last_checkpoint = time.monotonic()
    error = None

    def task(url):
        pages = []
        try:
            profile, warnings = collect_profile(client, url, today, pages)
            return profile, warnings, pages
        except BaseException as exc:
            client.fail(exc)
            raise

    def aggregate(future, url):
        nonlocal error
        if future.cancelled():
            return
        try:
            profile, warnings, pages = future.result()
        except Cancelled as exc:
            if error is None:
                error = exc
        except BaseException as exc:
            report["failed"][url] = str(exc)
            if error is None or isinstance(error, Cancelled):
                error = exc
        else:
            completed[url] = profile
            completions.append(time.perf_counter())
            report["history_pages"][url] = pages
            if warnings:
                report["source_warnings"][url] = warnings
            report["successful"] = len(completed)

    def checkpoint():
        started = time.perf_counter()
        write_json(stage / "progress.json", {
            "started": report["started"], "completed_profiles": len(completed),
            "total_profiles": len(urls), "directory_complete": report["directory_complete"],
            "directory_pages": report["directory_pages"], "metrics": client.metrics.snapshot(),
            "cancel_file": str(client.limiter.cancel_file), "published": False,
            "eta_seconds": observed_eta(completions, len(completed), len(urls), time.perf_counter()),
            "eta_basis": "last 40 profile completion intervals",
        })
        client.metrics.add("report_write_seconds", time.perf_counter() - started)

    def progress():
        metrics = client.metrics.snapshot()
        elapsed = metrics["elapsed_seconds"]
        eta = observed_eta(completions, len(completed), len(urls), time.perf_counter())
        eta_text = f"{eta:.0f}s" if eta is not None else "pending"
        print(f"Profiles {len(completed)}/{len(urls)} | cache {metrics.get('cache_hits', 0)} | "
              f"live {metrics.get('live_requests', 0)} | failures {len(report['failed'])} | "
              f"elapsed {elapsed:.0f}s | ETA(recent) {eta_text}", flush=True)

    try:
        for _ in range(client.workers):
            url = next(remaining, None)
            if url is not None:
                pending[pool.submit(task, url)] = url
        checkpoint()
        while pending:
            client.check()
            done, _ = wait(pending, timeout=.2, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda f: pending[f]):
                aggregate(future, pending.pop(future))
            if error is not None:
                raise error
            for _ in range(client.workers - len(pending)):
                url = next(remaining, None)
                if url is not None:
                    pending[pool.submit(task, url)] = url
            current = time.monotonic()
            if current - last_progress >= 5:
                progress()
                last_progress = current
            if current - last_checkpoint >= 10:
                checkpoint()
                last_checkpoint = current
    except BaseException as exc:
        error = exc
        client.cancel(str(exc))
    finally:
        if error is not None:
            for future in pending:
                future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        for future, url in sorted(pending.items(), key=lambda item: item[1]):
            aggregate(future, url)
        checkpoint()
        progress()
        collected = [dict(requested_url=url, **completed[url]) for url in sorted(completed)]
        writing = time.perf_counter()
        write_json(stage / "collected-profiles.json", collected)
        report["identity_audit"] = identity_audit(collected)
        report["collected_field_coverage"] = {
            key: sum(p.get(key) is not None for p in completed.values()) for key in HEADERS
        }
        client.metrics.add("report_write_seconds", time.perf_counter() - writing)
        report["runtime"] = client.metrics.snapshot()
        report["source_fetch_range"] = client.source_dates()
        report["fetch_provenance"] = client.provenance_snapshot()
    if error is not None:
        raise error
    return [completed[url] for url in urls]


def candidate(root, stage, client, report):
    today = datetime.fromisoformat(report["started"]).date()
    urls = discover(client, report, limit=report["directory_limit"])
    write_json(stage / "discovery.json", {
        "complete": report["directory_complete"], "pages": report["directory_pages"],
        "urls": urls, "fetch_provenance": client.provenance_snapshot(),
    })
    profiles = collect_profiles(client, urls, today, stage, report)
    export_started = time.perf_counter()
    registry = previous_registry(root)
    report["migration"] = {}
    reconcile(
        profiles,
        registry,
        json.loads(ALIASES.read_text(encoding="utf-8")),
        report["migration"],
    )
    rows = sorted(
        (Fighter.model_validate(p) for p in profiles), key=lambda f: f.fighter_id
    )
    with (stage / FILES[0]).open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS.values())
        writer.writeheader()
        writer.writerows(row.model_dump(mode="json", by_alias=True) for row in rows)
    build(stage / FILES[1], rows, registry)
    data = validate(stage / FILES[0], stage / FILES[1])
    report["coverage"] = coverage(data)
    report["missing"] = {k: len(data) - n for k, n in report["coverage"].items()}
    report["history"] = dict(Counter(f.history_status for f in rows))
    if initial(root):
        report["changes"] = migration_changes(root / FILES[0], data)
    else:
        old = validate(root / FILES[0], root / FILES[1])
        report["changes"] = changes(old, data)
        guard(old, data)
    from .refresh_state import full_sidecars
    full_sidecars(root, stage, data, report)
    report.update(
        completed=now(),
        reason="validated candidate",
        hashes={n: digest(stage / n) for n in FILES[:2]},
    )
    client.metrics.add("export_validation_seconds", time.perf_counter() - export_started)
    report["runtime"] = client.metrics.snapshot()
    write_json(stage / "report.json", report)


def identity_audit(profiles):
    groups = defaultdict(list)
    names = defaultdict(list)
    for p in profiles:
        key = "node:" + p["source_id"] if p.get("source_id") else "url:" + p["url"]
        groups[key].append(p)
        if p.get("dob"):
            names[(p["name"].casefold(), p["dob"])].append(p["requested_url"])
    duplicates = {}
    for key, items in groups.items():
        if len(items) > 1:
            differences = [
                field for field in HEADERS if field != "url"
                and any(p.get(field) != items[0].get(field) for p in items[1:])
            ]
            duplicates[key] = {
                "urls": [p["requested_url"] for p in items],
                "conflicting_fields": differences,
            }
    return {
        "collected_urls": len(profiles),
        "distinct_source_identities": len(groups),
        "distinct_node_ids": len({p["source_id"] for p in profiles if p.get("source_id")}),
        "missing_node_id_profiles": sum(not p.get("source_id") for p in profiles),
        "duplicate_source_identities": duplicates,
        "shared_name_and_dob": [urls for urls in names.values() if len(urls) > 1],
    }


def publish(root, stage, bootstrap):
    report = json.loads((stage / "report.json").read_text(encoding="utf-8"))
    if report["baseline"] != baseline(root) or report["aliases_hash"] != digest(
        ALIASES
    ):
        raise ValueError("Candidate baseline or reviewed aliases changed")
    if (
        report["schema_version"] != VERSION
        or report["source"] != "UFC.com"
        or report["hashes"] != {n: digest(stage / n) for n in FILES[:2]}
    ):
        raise ValueError("Candidate manifest mismatch")
    rows = validate(stage / FILES[0], stage / FILES[1])
    if (
        not report["directory_complete"]
        or not report["directory_pages"]
        or report["failed"]
        or len(rows) != report["successful"]
        or len(rows) != report["discovered"]
    ):
        raise ValueError("Incomplete collection")
    from .refresh_state import SIDECARS, load as load_state
    if report.get("sidecar_hashes") != {n: digest(stage / n) for n in SIDECARS}:
        raise ValueError("Candidate refresh sidecars missing or changed")
    load_state(stage, rows)
    validate_favorite_aliases(rows, previous_registry(root), json.loads(ALIASES.read_text(encoding="utf-8")))
    first = initial(root)
    if bootstrap and os.environ.get("GITHUB_ACTIONS") == "true":
        raise ValueError("Bootstrap is unavailable in GitHub Actions")
    if first != bootstrap:
        raise ValueError(
            "First UFC.com publication requires explicit candidate review and --bootstrap"
        )
    changed = True
    if not first:
        old = validate(root / FILES[0], root / FILES[1])
        guard(old, rows)
        changed = any(changes(old, rows).values())
    data_as_of = datetime.fromisoformat(
        report.get("source_fetch_range", {}).get("oldest") or report["started"]
    ).date().isoformat()
    if not changed:
        # A rebuilt SQLite file can have different bytes even with equal rows.
        # Sidecars describe the installed generation, so install the validated pair.
        changed = report["hashes"] != {n: digest(root / n) for n in FILES[:2]}
    if not changed:
        success = root / FILES[2]
        data_as_of = (
            json.loads(success.read_text(encoding="utf-8")).get("data_as_of")
            if success.exists()
            else None
        )
    report.update(
        data_as_of=data_as_of,
        published=changed,
        reason="validated replacement" if changed else "unchanged validated refresh",
        publication_checked=now(),
        published_hashes=report["hashes"]
        if changed
        else {name: report["baseline"][name] for name in FILES[:2]},
    )
    replace(root, stage, report, changed)


def main(
    output_dir=".",
    *,
    publish_now=False,
    reviewed=None,
    bootstrap=False,
    pace=0.5,
    budget=18000,
    directory_limit=1000,
    workers=4,
    resume=None,
    cache_age=24,
    refresh_cache=False,
    refresh_urls=(),
    cancel_file=None,
):
    root = Path(output_dir).resolve()
    with locked(root):
        if publish_now or reviewed:
            recover(root)
        elif (root / ".refresh-undo").exists():
            raise ValueError("Interrupted publication requires --recover")
        report = {
            "schema_version": VERSION,
            "source": "UFC.com",
            "source_version": 1,
            "started": now(),
            "published": False,
            "successful": 0,
            "failed": {},
            "source_warnings": {},
            "history_pages": {},
            "directory_limit": directory_limit,
            "discovered": 0,
            "directory_pages": 0,
            "directory_complete": False,
        }
        stage = None
        try:
            if reviewed:
                return publish(root, Path(reviewed).resolve(), bootstrap)
            if publish_now and initial(root):
                raise ValueError(
                    "Generate and review the first candidate before bootstrap"
                )
            report.update(baseline=baseline(root), aliases_hash=digest(ALIASES))
            folder = root / "candidates"
            folder.mkdir(exist_ok=True)
            stage = Path(tempfile.mkdtemp(dir=folder))
            print(f"Candidate directory: {stage}", flush=True)
            client = Runtime(
                Client, stage, pace=pace, budget=budget, workers=workers, resume=resume,
                cache_age=cache_age, refresh=refresh_cache, refresh_urls=refresh_urls,
                cancel_file=cancel_file,
            )
            print(f"Cancel file: {client.limiter.cancel_file}", flush=True)
            try:
                candidate(root, stage, client, report)
            except BaseException as exc:
                client.cancel(str(exc))
                save = getattr(client, "save_failure", None)
                if callable(save):
                    report["failure_evidence"] = save(stage / "failure-evidence")
                raise
            finally:
                report["runtime"] = client.metrics.snapshot()
                report["source_fetch_range"] = client.source_dates()
                report["fetch_provenance"] = client.provenance_snapshot()
                client.close()
            if publish_now:
                publish(root, stage, False)
            return stage
        except BaseException as exc:
            report.update(reason=str(exc) or type(exc).__name__, completed=now(),
                          status="cancelled" if isinstance(exc, (KeyboardInterrupt, Cancelled)) else "failed")
            if stage is not None:
                write_json(stage / "failure-report.json", report)
            write_json(root / "collection-failure.json", report)
            raise
