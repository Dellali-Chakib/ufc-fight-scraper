# UFC Fighter Explorer data

The collector follows UFC.com's [all-athletes directory](https://www.ufc.com/athletes/all), reads athlete profiles and their history pages, and builds a matched CSV and SQLite snapshot for the Explorer and FastAPI. The checked-in publication can still be in the legacy format until the first reviewed UFC.com publication.

## Run locally

Use Python 3.11+ on Linux, macOS or Windows from the scraper repository root.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -v
python -m scraper.diagnostic
python run_scraper.py
```

For native Windows, keep both the working copy (including SQLite and candidates)
and a separate virtual environment on the Windows filesystem. Do not reuse a WSL
`.venv`. In PowerShell, from that Windows working copy:

```powershell
py -3.12 -m venv "$env:USERPROFILE\venvs\ufc-fight-scraper"
$python = "$env:USERPROFILE\venvs\ufc-fight-scraper\Scripts\python.exe"
& $python -m pip install -r requirements.txt
& $python -m unittest discover -v
& $python -m scraper.diagnostic
& $python -u run_scraper.py --dry-run --pace 2 --budget 21600
```

Environment activation is optional. Use an unused environment path at setup.
Each directory page and athlete prints progress. Windows access must pass the
diagnostic using the same Requests client; WSL and hosted runners can have
different access results. Avoid SQLite through `\\wsl.localhost\...`: Windows
read-only queries against that share have returned `database is locked`.

The default command (also available as `--dry-run`) collects a full candidate in a new local directory under `candidates/` and prints its path. A successful directory contains `report.json`, `output.csv` and `ufc_fighters.db`. A failed attempt records its reason and progress in `collection-failure.json` and the stage's `failure-report.json`. Partial files have no validated manifest. The diagnostic requests one directory page, Kayla Harrison's profile and, when available, her portrait headers. It follows at most five image redirects, checking each destination against the approved HTTPS UFC hosts, and requires final HTTP 200 with an image Content-Type. Image failure does not fail profile collection.

Collection retains compressed response bodies and retrieval metadata under the
stage's `responses/` directory. `collected-profiles.json` is diagnostic evidence,
not a validated export. Reports distinguish collected URLs from distinct node
identities (with canonical-URL fallback when no node ID is supplied), list
duplicate identities and conflicting fields, and report shared name/DOB groups
for review. Duplicate identities are not automatically merged or skipped; the
existing identity and publication gates still apply. `collected_field_coverage`
describes the collected subset, while `coverage` requires a validated candidate.

Resume explicitly with `--resume PRIOR_CANDIDATE` (or its `responses` directory).
Each cached entry must have a matching approved URL, HTTP 200, HTML MIME type,
intact SHA-256 body, recognizable structure and a timezone-aware source-fetch
timestamp within `--cache-age HOURS` (default 24). Raw HTML goes through the
current parser; saved rows and progress counts never establish completeness.
Directory discovery follows the entire pager chain, including its terminal page.

```powershell
$python = "$env:USERPROFILE\venvs\ufc-fight-scraper\Scripts\python.exe"
& $python -u run_scraper.py --dry-run --resume 'candidates\PRIOR_CANDIDATE' --workers 4 --pace 1 --cache-age 24 --budget 21600
& $python -u run_scraper.py --dry-run --refresh-cache --workers 4 --pace 1 --budget 21600
& $python -u run_scraper.py --dry-run --resume 'candidates\PRIOR_CANDIDATE' --refresh-url 'https://www.ufc.com/athlete/kayla-harrison' --pace 1
```

Every invocation creates a new candidate. `resume-sources.json` retains the prior
archive paths across repeated resumes. `--refresh-cache` ignores prior entries
without deleting evidence. Repeatable `--refresh-url` refreshes one resource path
and all its pagination; it also accepts the directory URL. New response versions
have separate checksum filenames. Cached reads retain original fetch dates in
`source_fetch_range` and per-URL provenance. A cached refresh is not a fresh live
observation of every athlete. Expired entries require live requests.

Four profile workers are the default. Each owns a Requests session and follows
one athlete's history sequentially. Workers bound queued tasks and in-flight
requests; `--pace` is a single shared request-start interval across workers,
redirects and retries. Four workers at `--pace 1` still start at most one live
request per second. Retry-After/backoff coordinates all workers. Access denials
and three 429s in a minute stop new activity. Workers never write exports or
publication files. The coordinator sorts profiles before identity assignment.

A refreshed first page never reuses older continuation pages. A cached/resumed
history with a gap over five minutes between adjacent source fetches stays
incomplete, with counts unknown, until a coherent athlete refresh. The same
interrupted-cohort condition prevents directory completeness and requires an
explicit directory refresh. All required pages are still collected; these
checks prevent stale pagination offsets from silently establishing counts.

Progress reports completed/total profiles, cache hits, live requests, failures,
elapsed time and an ETA from the last 40 profile-completion intervals. ETA can change when cached work
gives way to uncached fighters. Create the exact cancel file printed by the
running command (or configure `--cancel-file PATH`) to stop reliably on Windows:

```powershell
New-Item -ItemType File 'candidates\CURRENT_CANDIDATE\cancel.request'
```

Cancellation stops new work, drains bounded in-flight work, preserves archives
and checkpoints, and exits 130. Ctrl-C runs the same cleanup when delivered by
the console. Publication locking and recovery gates remain in force. Metrics
separate cache reads, parsing, network latency, aggregate worker pacing/backoff
waits, response writes and report writes; concurrent sums can exceed wall time.
Few-minute cached or selective refreshes depend on parsing cost and how many
pages remain fresh. A cold full historical build has a request-rate lower bound
and is not promised to take a few minutes.

Worker-local Requests sessions use the user agent `CS571-FighterExplorer/2.0 (+https://github.com/Dellali-Chakib/ufc-fight-scraper)`. The default shared request-start interval is half a second. Use `--pace SECONDS`, `--budget SECONDS` (full reconciliation default 18000; daily event workflow 5400) and `--directory-limit PAGES` (default 1000). An athlete history has a 100-page safety limit. The client uses 5-second connect and 20-second read timeouts, bounded retries for transient errors and coordinated Retry-After delays within its remaining budget. It follows up to five redirects on approved HTTPS UFC hosts. Permanent denials stop collection. Both page types require recognizable source structure.

## Review and publish

Set `stage` to the successful directory printed by the collector. Inspect its report, especially discovery completeness, ambiguous matches, roster changes, field coverage and history warnings. Make any reviewed identity exceptions before rerunning collection. The first UFC.com directory supplies a new roster baseline. The 1,247 legacy CSV rows and 1,849 legacy database rows are migration evidence. An unexpectedly small first candidate or collapsed field coverage warrants investigation before bootstrap.

```sh
stage=candidates/REPLACE_WITH_REVIEWED_DIRECTORY
python validate_export.py "$stage/output.csv" "$stage/ufc_fighters.db"
python -m json.tool "$stage/report.json" | less
python run_scraper.py --publish-candidate "$stage" --bootstrap
```

Bootstrap requires a separate explicit publication of a validated candidate, including on a fresh install. Review the compatible frontend before moving any public feed. For subsequent local refreshes use `python run_scraper.py --publish` or publish an already reviewed candidate with `--publish-candidate "$stage"`. A changed baseline, alias file or candidate checksum invalidates a pending candidate. The ongoing gate requires at least 95% of prior app IDs, limits roster growth to 25%, and requires each measured field's coverage fraction to retain at least 75% of its prior value. Warning incidence is exempt from the field-coverage floor. Large changes need investigation and an explicit code/policy review. Bootstrap only applies at the source transition.

The collector stages a fresh database. Its fighters table must match the CSV by identity and every exported value. A separate identities table reserves application IDs and numeric route IDs across absences. Legacy database-only fighters do not enter the new roster unless collected.

Local candidate, publication, API refresh and recovery commands share a nonblocking file lock (`flock` on POSIX, a fixed byte-range lock on Windows), released on exit or process termination. Run writers on one operating system against a local filesystem; these locks do not establish exclusion between Windows and WSL writers on a shared path. Individual file replacements use same-filesystem renames, with write-through moves on Windows and directory fsync on POSIX. Readers opening CSV and SQLite between replacements can see different generations. A synced undo directory covers CSV, SQLite, success metadata, event state and source timestamps, including which files were initially absent. Replacement errors restore the previous generation. An interrupted publisher leaves recovery state for the next publisher or `python run_scraper.py --recover`. Dry runs stop when recovery is pending. Use the scraper as the sole local writer. Existing SQLite sidecar files require closing writers and checkpointing before replacement. Windows also requires closing all SQLite readers before replacement or recovery; a sharing failure retains the undo journal until recovery succeeds. Keep backups for rollback after a successful publication.

The last successful report is `collection-success.json`. It includes schema and parser versions, UTC collection times, directory and profile counts, history page evidence, migration decisions, additions/removals, field changes, missing counts, coverage and raw warnings. A collection with no meaningful changes advances this report while preserving the prior data files and their as-of date. Candidate hashes and published hashes are identified separately. The failure report records the most recent failure and can predate a later success.

## Schema version 2

The shared Pydantic model and exact CSV header mapping are in [scraper/contract.py](scraper/contract.py). SQLite and JSON use the model's snake_case names. SQLite also has integer `id` for existing API routes. Missing values are Python/JSON null, SQL NULL and empty CSV cells. Numeric zero is a measured value. All accepted profiles are exported.

| CSV fields | Meaning |
| --- | --- |
| FighterID, SourceAthleteID, URL, Source | Stable app key, optional Drupal node number, canonical HTTPS athlete URL, and the literal UFC.com. |
| FavoriteAliases | Supported legacy favorite keys from corroborated/reviewed identity mappings. New UFC.com identities have no inferred name/numeric aliases; competing identities and tombstones block ambiguous names. |
| Name, Weight Class, Status | Displayed profile name, division (without the trailing word Division), and source bio status. |
| Height, Reach, Weight | Numeric inches, inches and pounds, including decimals. A displayed height of `0.00` is unusable source data: normalize to null with the raw text in a structured source-inconsistency warning. Normalized heights must still be positive; other numeric zero values retain their defined meanings. |
| DOB, Stance | Explicit ISO birth date from the athlete's JSON-LD and explicitly labeled stance when supplied. |
| SLpm, SApM | Significant strikes landed and absorbed per minute. |
| StrAcc, StrDef, TDAcc, TDDef | Significant striking accuracy, significant strike defense, takedown accuracy and takedown defense, as fractions from 0 through 1. |
| TDAvg, SubAvg | Displayed takedown average and submission average per 15 minutes. UFC describes submission attempt rates in its statistical reporting. The profile label verifies the time unit but does not explicitly say “attempts.” |
| Record, FightCount | Complete displayed career W-L-D and the sum of those three numbers. An incomplete record such as `11-2- (W-L-D)` yields null for both; raw text remains in structured warnings. Missing draws are never inferred as zero. No-contest totals are unspecified. |
| HistoryStatus | complete when the recognized UFC history reaches its terminal page and each historical entry can be classified, unknown when unavailable, incomplete when entries cannot be resolved. Completeness describes the source listing. |
| FightsInUFC, BadSample | Unique completed UFC bouts in complete history, and whether that count is below three. Both are null for unknown or incomplete history. Known zero is 0 and true. |
| LastFightDate, Most Recent Fight | Latest completed UFC date in complete history and elapsed days as of the data snapshot. Dates use UFC's displayed calendar day, compared with the UTC date at collection start. |
| PortraitURL, HeadshotURL | Explicit hero and optional headshot from the current athlete's linked history corner. Relative paths are resolved with their query parameters. Recognized placeholders are dropped. |
| Warnings | Comma-separated affected fields. The report contains source evidence keyed by profile URL. |

The US athlete page labels rate groups by statistic and time unit. The parser reads the accuracy percentage from the corresponding chart and treats blank chart values as missing. It retains reported values when labeled landed/attempted totals conflict with them. For example, Adesanya's archived chart shows 0% with an empty landed field, 11 attempts and a separate 0.05 takedown average. The warning records these observations. There is no imputation from prior publications. [UFC's explanation of submission attempt rates](https://www.ufc.com/news/ufc-191-numbers)

Only the athlete-results view supplies history pagination. Future dates are excluded. For past cards the parser requires an identifiable athlete corner, UFC event evidence, a completed outcome and a deduplication key. It accepts wins, losses, draws and no contests even when round or time is missing. Unrecognized event formats and unresolved outcomes leave the sample incomplete. A missing history section leaves it unknown. A scheduled-only recognized listing or an explicit empty history can yield a known zero. The directory can change during a crawl and UFC may omit historical bouts. Neither pagination nor structural validation independently establishes historical accuracy.

## Identity

The first migration reads the previous CSV and SQLite locally. A unique normalized full name and explicit matching DOB can preserve a legacy app key and numeric database ID. Normalization case-folds, removes combining marks and collapses whitespace. The displayed name governs matching. The misleading URL ending in tenk-ebbott belongs to Scott Adams in the saved source.

The registry preserves existing source IDs. New athletes receive `ufc-<node number>` or, without an explicit node number, a namespaced UUID derived from their first canonical URL. Subsequent refreshes consult the registry, supporting an ordinary URL change through the node ID or corroborated identity. An athlete with no stable source ID and insufficient corroboration after a URL change needs review. Ambiguous name matches receive distinct identities and appear in the report. To confirm an exception, edit `identity-aliases.json` with a source node number (as a string) or canonical URL as key and the prior FighterID as value. Conflicting mappings and duplicate identities stop publication. Numeric IDs of absent fighters stay reserved.

## API, frontend and automation

```sh
python app.py
python query_fighters.py Harrison
```

FastAPI provides `/docs`, `GET /fighters` (optional limit and weight_class), `GET /fighters/{numeric_id}`, `GET /fighters/search/{name}` and `GET /stats/summary`. Each request opens the current SQLite file read-only and closes it on completion. On POSIX, in-flight requests can finish against the generation they opened; on Windows they must finish before replacement. The API can serve the original schema through bootstrap. `POST /update` queues the standard guarded refresh. Its response acknowledges queuing. Check success or failure metadata for the outcome.

The companion frontend must accept UFC.com athlete URLs, use the explicit FighterID and read blank BadSample with unknown/incomplete history. Older published clients may reject the entire CSV. The local frontend changes read FavoriteAliases, distinguish missing and zero, and try an override, the UFC hero/headshot, a mapped portrait and finally a silhouette. A null override suppresses all images. The displayed image determines the credit. A failed image has no bearing on a fighter's stats.

The read-only diagnostic workflow is manually dispatched. The event refresh workflow runs daily at 13:23 UTC with manual dry-run/publication controls and the shared publisher concurrency group. Full reconciliation is manual and unscheduled. Scheduled/API publication requires an established UFC.com baseline. The workflow's remote commit/push steps run only when that workflow is invoked and validation succeeds.

## Verification limits

The fixtures contain excerpts of genuine archived HTML with individual source and retrieval timestamps in [the fixture manifest](tests/fixtures/README.md). Tests also modify copies to exercise future dates, draws, no contests, malformed markup and rollback faults. Archives are offline test inputs only.

On 2026-11-24 ordinary local HTTPS probes returned 403 for the live directory, eight athlete pages and three archived portrait URLs. No live roster or full migration count was established. Two archived directory captures contained 22 distinct profiles in total. Eight archived first-page athlete samples yielded four legacy identity matches and four new identities, six hero portraits, five headshots and zero explicit stances. Four samples still linked to another history page. GitHub-hosted runner access and full roster coverage require separate verification.

On 2026-11-25 native Windows Python 3.12.0 with Requests 2.32.4 and the
configured scraper User-Agent passed the live directory/profile diagnostic
(11 directory profiles; Kayla Harrison, source ID 136296). The optional portrait
probe reported HTTP 301. All 22 tests passed on Windows and WSL. A full dry-run
attempt at two-second pacing completed 296 directory pages with 3,241 unique
URLs, then stopped after 385 successful profiles: Brendon Marotte's HTTP-200
profile supplied the unsupported record `11-2- (W-L-D)`. Validation was retained;
no candidate CSV/database or final field-coverage report was produced, and no
publication or bootstrap occurred. Local evidence is saved under
`candidates/windows-verification/`. This Windows result does not establish
GitHub-hosted runner access.

Educational project. UFC data and UFC portraits belong to their respective rights holders.

Event-driven refresh, explicit baseline setup, hosted diagnostics, daily and
follow-up behavior, publication safeguards, and rollout commands are documented
in [EVENT_REFRESH.md](EVENT_REFRESH.md). Event mode uses fresh participant profiles
and preserves the rest of the roster. Scheduled jobs cannot bootstrap.
