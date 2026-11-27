# Event-driven refresh rollout

Implementation is prepared for review. No hosted workflow has been dispatched,
no UFC.com bootstrap has been performed, and the published legacy CSV/SQLite
files remain unchanged. Local Windows success is not hosted access verification.

## Baseline review and explicit setup

Use a native Windows filesystem for SQLite and candidates. The existing local
interpreter is `C:\Users\shiro\venvs\ufc-fight-scraper\Scripts\python.exe`.
The WSL environment is independent. Do not run Windows and WSL publishers against
one shared path: their locks do not provide cross-OS exclusion.

```powershell
Set-Location 'C:\Users\shiro\ufc-fight-scraper-windows-20261125'
$python = 'C:\Users\shiro\venvs\ufc-fight-scraper\Scripts\python.exe'
& $python -m pip install -r requirements.txt
& $python -m unittest discover -v
# Select the actual reviewed archive; entries older than 24h are fetched again.
& $python -u run_scraper.py --dry-run --resume 'candidates\PRIOR_CANDIDATE' --cache-age 24 --workers 4 --pace 1 --budget 18000
& $python validate_export.py 'candidates\REVIEWED_CANDIDATE\output.csv' 'candidates\REVIEWED_CANDIDATE\ufc_fighters.db'
```

Review that candidate's `report.json`, history coverage, migration mappings,
`event-refresh-state.json`, and `fighter-source-times.json`. Exact observed
legacy UFC event paths are listed in `scraper/ufc_event_paths.json`; this is not
permission to count other promotions or infer unlabeled outcomes. Unknown
outcomes keep history incomplete. The 98 existing ambiguous mappings need human
review: 75 DOB disagreements, 21 missing source DOBs, two missing legacy DOBs.
Do not resolve them from names alone. Document confirmed aliases in
`identity-aliases.json` and regenerate a candidate; alias changes invalidate an
already reviewed candidate. Unresolved matches keep separate source identities.

Check CSV/SQLite/API compatibility and the consuming frontend before approving
the source transition. The current native directory is an evidence workspace,
not a Git checkout. For rollout, use an approved Windows-native clone of the
reviewed code on the intended default branch, retaining the separate evidence
workspace. In a **later explicitly authorized local session**:

```powershell
# Run only after the implementation has been reviewed and merged.
git clone 'https://github.com/Dellali-Chakib/ufc-fight-scraper.git' 'C:\Users\shiro\ufc-fight-scraper-rollout'
Set-Location 'C:\Users\shiro\ufc-fight-scraper-rollout'
$python = 'C:\Users\shiro\venvs\ufc-fight-scraper\Scripts\python.exe'
& $python -m pip install -r requirements.txt
& $python -m unittest discover -v
```

The reviewed baseline from this implementation session is
`C:\Users\shiro\ufc-fight-scraper-windows-20261125\candidates\tmpdrrcd61s`.
Its baseline/alias hashes must still match the rollout checkout. If they do not,
regenerate and review a candidate against that checkout, optionally resuming the
existing response archive. Never alter the manifest to bypass the check.

```powershell
$stage = 'C:\Users\shiro\ufc-fight-scraper-windows-20261125\candidates\tmpdrrcd61s'
& $python validate_export.py "$stage\output.csv" "$stage\ufc_fighters.db"
# Explicit source-transition bootstrap; never available inside GitHub Actions.
& $python run_scraper.py --publish-candidate $stage --bootstrap
# Review and commit the five publication files together using the repository's
# normal branch-protection/PR process. Do not include response caches.
git add -- output.csv ufc_fighters.db collection-success.json event-refresh-state.json fighter-source-times.json
```

Use the approved review/commit/PR process after staging; no push command is
provided to bypass branch policy. The five-file generation must reach the intended default branch before enabling
scheduled publication. This guide does not authorize committing/pushing during
the implementation session. Initial state covers events starting 30 days before
the baseline collection began, so the first event run catches up recent events
even if a cached baseline predates their final statistics. Older baseline history
comes from the full reconciliation; event discovery does not claim an unlimited
pre-baseline results audit.

## GitHub setup and hosted diagnostic

1. Review and merge code/workflows through the repository's normal process.
   Keep **Refresh completed UFC events** disabled until baseline and diagnostic
   review finish (Actions → workflow → `…` → Disable workflow).
2. In Settings → Actions → General, permit the repository's approved actions.
   The publishing jobs request `contents: write`; the diagnostic requests only
   `contents: read`. Use the repository `GITHUB_TOKEN` supplied by checkout.
   No personal token or branch-protection bypass is needed or supported.
3. Actions → **Diagnose hosted UFC access** → Run workflow → choose the default
   branch. Inspect the job and download `hosted-access-diagnostic`.
   Require genuine official listing, event, directory and profile structure;
   HTTP 200 alone is insufficient. Optional portrait status/MIME and bounded
   HTTPS redirects are reported separately. Access denial fails the diagnostic.
4. If protected branches reject direct bot pushes, keep publishing disabled and
   arrange an approved publication PR process. Do not disable protection to make
   this workflow succeed. The provided publisher fails visibly on rejection.
5. After explicit baseline setup, Actions → **Refresh completed UFC events** →
   Run workflow with `publish` **unchecked**. Review the complete candidate,
   pending work, timestamps, profile warnings and retained roster.
6. Run the same workflow with `publish` checked on the default branch only.
   After reviewing the first successful publication, enable the daily workflow.

The workflows run on `windows-latest`; only actual hosted evidence can justify
changing that runner. The schedule is `23 13 * * *` (13:23 UTC daily). GitHub may
delay cron execution, and disabled workflows or prolonged outages delay checks.
Publishing workflows share `fighter-data-publish`, with cancellation disabled.
Event collection has a 5,400-second request budget below its 120-minute job
limit. Manual full reconciliation has an 18,000-second budget below 360 minutes.

## Daily behavior, follow-ups and freshness

Pure parsers read the official past-event view and canonical event cards.
Retrieval follows validated pagination until the durable catch-up boundary is
covered, with a 100-page safety bound and no assumption that the first event is
complete. Dates select discovery coverage; explicit finalized bout outcomes
establish completion. All active bouts need two canonical athlete links and a
consistent win/loss, draw/draw or no-contest/no-contest result. Canceled bouts do
not supply participants. Missing links, conflicting identities and unsupported
structure fail visibly. Unknown results remain pending. Replacement results
replace the actual participants and invalidate the event's prior checks.

Each run performs at most three due event checks, oldest event first. Other work
stays pending. An initial check is followed by checks eligible 24 and 48 hours
**after the initial successful check**. Delayed initial processing shifts these
checks; a long outage does not manufacture three observations from one response.
An overdue follow-up is performed on the next eligible daily run, one stage per
event per run. Completed events are revisited while follow-ups remain due;
corrections after all three checks require manual reconciliation/investigation.

Event retrieval is always fresh. Targeted current profiles and all their
required sequential history pages are also fetched fresh through worker-local
Requests sessions and the shared limiter. Event mode deliberately does not reuse
prior HTML, so absent/expired caches cannot change its correctness. Same-run
identical URLs are deduplicated. Full reconciliation may reuse integrity-checked
archives up to `--cache-age` (24h default), always preserving their fetch dates.
No cached body is described as freshly checked.

Unchanged statistics are a successful fresh observation, not proof that UFC has
incorporated an event. Checks explicitly record incorporation as unverified,
with results evidence and per-profile source times. History counts remain null
unless the current parser proves completeness. Image URL coverage does not imply
HTTP image availability. Event mode does not download all portraits.

Only participants are updated or added. All nonparticipants, including derived
`Most Recent Fight`, remain byte-for-field equivalent in normalized rows. That
relative-day field therefore ages between their checks; use `LastFightDate` and
source timestamps when freshness matters. A full reconciliation recalculates it
for everyone. Numeric IDs, source IDs and legacy favorite aliases retain existing
identity reconciliation safeguards. A same-name newcomer with ambiguous legacy
evidence blocks the event candidate instead of receiving a guessed mapping.

## Durable state and publication

`event-refresh-state.json` schema 1 stores canonical event identities, bout IDs,
actual participants, pending results, initial/24h/48h observations and source
evidence. `fighter-source-times.json` schema 1 holds every fighter's current
profile and history source times. Both identify the exact generation computed
from the CSV and SQLite SHA-256 hashes. The catch-up cursor advances only in a
validated state candidate; pending events are retried even after falling outside
the seven-day listing overlap. An outage uses the last successful discovery
boundary, not a fixed recent-event count. Exceeding pagination bounds fails
rather than discarding missed events.

Candidates never mutate the published state. Local publication rechecks the
baseline, aliases, paired dataset, generation, sidecar hashes, retention and
nonparticipant equality under the existing lock. The undo journal covers all
five files, including initial absence, and retains the existing SQLite sidecar
and Windows replacement safeguards. Readers across separate files still need to
verify generation if they require a consistent multi-file snapshot.

Actions fetches the default branch immediately before local publication and
requires remote HEAD to equal the checked-out commit. The regular Git push is
the remote transaction: dataset, event state, provenance and success metadata
travel in one commit. Only those five files are staged. No caches are committed.
A concurrent update or branch protection rejects the push; no force push or
binary rebase occurs. The candidate remains in the artifact and remote work
remains pending. A repeated run with no new/due work creates no heartbeat commit.

## Manual reconciliation and recovery

Actions → **Reconcile full UFC roster** → Run workflow. Leave `publish` unchecked
for review; publication requires the default branch and an existing UFC.com
baseline. It has no schedule and cannot bootstrap. Full reconciliation preserves
the event queue while refreshing the entire roster and per-fighter provenance.

Local event commands:

```powershell
& $python -u run_events.py --dry-run --workers 4 --pace 1 --budget 5400 --max-events 3
# Later, only after explicit approval of that candidate:
& $python run_events.py --publish-candidate 'candidates\event-REVIEWED'
# If an interrupted local replacement left an undo journal:
& $python run_scraper.py --recover
```

On failure, inspect `collection-failure.json`, candidate failure report, exact
response metadata/bodies and `actions-refresh-summary.json`. Artifacts retain
candidate summaries and response evidence for 14 days. A failed collection,
validation or push does not acknowledge the work remotely. Fix the underlying
access/structure/identity problem and rerun from the current default branch.
Do not hand-edit pending checks to mark them successful. If the remote baseline
changed, rebuild against that baseline instead of rebasing SQLite. If state and
dataset generations disagree, stop and restore a complete last-good Git commit
or explicitly rebuild/review a coherent baseline; do not silently reseed state.

Workflow reference: [GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[repository token permissions](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token),
and [scheduled workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
