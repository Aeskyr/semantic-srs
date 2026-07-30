# Semantic SRS

Last updated: 2026-07-28

## Public Windows release plan

Version 0.2.1 packages this project as the public MIT-licensed
`Aeskyr/semantic-srs` marketplace repository for Windows 10/11 x64 and CPython
3.11. The repository contains two cooperating but independently installable
plugins: `semantic-srs` and the optional `local-rag` retrieval companion. Claude
Code and Codex use the same learner state beneath
`%LOCALAPPDATA%\SemanticSRS`, while application code, virtual environments,
model caches, logs, and persistent data remain outside plugin checkouts.

The release work includes portable Claude and Codex manifests, versioned
application staging, dependency-lock-aware setup/update scripts, data-preserving
uninstall and legacy migration, installer tests with fake host executables,
Windows CI, public documentation, and clean-room release instructions.
Publication, tag creation, and release creation remain pending until automated
checks and clean Windows clone/ZIP smoke tests pass.

The repository includes `showcase/imperial-russia-monarchs.json`, a portable
Semantic SRS export with 15 public source snapshots and 30 unreviewed draft cards
covering Imperial Russia's fourteen emperors and empresses from 1721 to 1917.
Release validation fixes its identity and counts and rejects reviewed cards, so
no developer learning history is shipped.

## Purpose and user experience

Semantic SRS is a single-user, local spaced-repetition system where the connected
agent remains the conversational review tutor. It creates sourced cards, varies questions,
judges answers by meaning, gives feedback, and submits a hidden rating. A local
dashboard visualizes and manages the same persistent state but never grades
answers or conducts reviews.

The learner approves generated drafts before they enter the queue. Reviews feel
like a conversation rather than self-reported Again/Hard/Good/Easy buttons. The
dashboard is launched with one click, opens in a browser, refreshes every five
seconds, and reflects Codex review writes while it is open.
The shipped review skill explicitly triggers on dashboard requests and launches
the installed dashboard in a background PowerShell process; it directs users to
rerun `setup.ps1` only when the shared runtime is missing. Dashboard launch
commands quote paths containing spaces, and the Python launcher flushes its
tokenized URL immediately so wrappers can open it directly when browser handoff
fails.

## Architecture and data flow

`server.py` exposes the MCP interface and owns the established SQLite/FSRS
operations. `service.py` is the shared import facade used by the dashboard and is
the migration seam for continuing to separate persistence from transports.
`dashboard.py` is a Starlette ASGI application. `launch_dashboard.py` binds
Uvicorn to `127.0.0.1`, selects the first free port from 8765, creates a fresh
token, opens the browser, and supports normal Ctrl+C shutdown. `web/` contains
offline vanilla HTML, CSS, JavaScript, and SVG rendering.

Data flows as follows: sourced material -> immutable `source_snapshots` -> draft
rubrics in `cards` -> learner approval -> Codex review -> semantic score -> hidden
rating -> FSRS baseline -> supplemental interval policy -> transactional SQLite
update -> dashboard polling.
Dates are stored in UTC ISO 8601 form and localized only by the browser.

## Component responsibilities

- Plugin: packages the review skill and MCP server for Claude Code and Codex.
- MCP: provides exact state-changing and read interfaces to the host; it never asks
  the learner to select an FSRS rating.
- Review skill: governs source capture, draft approval, conversational question
  variation, semantic grading, follow-ups, correction, and feedback.
- Local RAG: discovers this file through the stable
  `project://semantic-srs/context` pointer and can supply evidence snapshots.
- SQLite: is the shared source of truth, using foreign keys, WAL, transactions,
  optimistic card/deck versions, and non-destructive migrations.
- FSRS 6: calculates baseline memory state and intervals at 0.90 desired
  retention. The server applies the versioned supplemental interval policy below;
  the dashboard never overrides scheduling.
- Dashboard: provides local visualization and administrative actions; it does not
  perform conversational review or semantic grading.

## Database entities and invariants

- `decks`: unique case-insensitive name, description, active/archived `status`,
  optimistic `version`, and timestamps. Archival is reversible.
- `source_snapshots`: immutable excerpt, URI, title, and content hash, unique per
  deck/URI/content tuple.
- `cards`: draft/active/rejected/suspended lifecycle, private rubric, source IDs,
  initial and current FSRS JSON, server-owned `due_at`, optimistic `version`,
  current review/lapse counters, and monotonic `scheduling_epoch`.
- `sessions`: start/end timestamps and review count for a deck.
- `review_events`: append-oriented exact question/answer, semantic evidence,
  mastery, confidence, hidden rating, FSRS before/after state, and correction
  metadata. Each row records its scheduling epoch. Active-card reset edits
  preserve these rows while excluding earlier epochs from future scheduling.
- `audit_events`: timestamped event type, entity, JSON details, and actor.

Foreign keys are enabled on every connection. Writes use `BEGIN IMMEDIATE`.
Active-card content edits require explicit confirmation, reset current FSRS state
and counters, increment `scheduling_epoch`, increment `version`, preserve review
history, and add an audit event. No permanent-delete interface is provided.

For FSRS learning or relearning intervals shorter than 24 hours, the baseline is
preserved. Longer intervals are multiplied by:

`min(1, offerings / 4) * easy_streak_factor * clamp(average_score / 0.90, 0.50, 1.10)`

The product is clamped to `0.125–1.60`. Easy-streak factors for zero through four
consecutive scores at least `0.90` are `0.80`, `1.00`, `1.15`, `1.30`, and
`1.45`; five or more use `1.60`. A lower score resets the streak. Adjusted long
intervals are clamped between one day and FSRS's maximum interval. Statistics
include only the card's current scheduling epoch, so a reset edit starts them
over. The adjusted due date is written to both the FSRS card JSON and `due_at`;
FSRS stability and difficulty remain unchanged.

## MCP tools and grading thresholds

Registered MCP tools:

- `srs_status`
- `srs_create_deck`
- `srs_list_decks`
- `srs_add_source_snapshot`
- `srs_add_draft_card`
- `srs_list_drafts`
- `srs_update_draft_card`
- `srs_set_draft_status`
- `srs_start_session`
- `srs_get_due_cards`
- `srs_record_review`
- `srs_correct_latest_review`
- `srs_end_session`
- `srs_deck_stats`
- `srs_export_deck`
- `srs_dashboard_summary`
- `srs_set_card_suspension`
- `srs_archive_deck`

Hidden FSRS ratings use mastery score intervals: Again `[0.00, 0.45)`, Hard
`[0.45, 0.70)`, Good `[0.70, 0.90)`, and Easy `[0.90, 1.00]`. Codex asks exactly
one targeted follow-up when confidence is below 0.70 or a provisional score lies
within 0.05 of a rating boundary.

## Dashboard design and API

The overview balances due, overdue, active, draft, suspended, and lapse metrics.
It renders mastery trend, hidden-rating distribution, weak cards, and a 14-day
workload forecast with local SVG. Cards are searchable and filterable and expose
an expandable section labeled exactly `Answer` containing only the answer
concepts without a redundant field label; source identifiers remain available internally, through the API, and
in the Sources view but are not shown in card answers. Expanded answers retain
their open or closed state across five-second polling, manual refreshes, searches,
filters, edits, and draft actions while their cards remain in the displayed
result set. Cards are grouped under the same kind of exact deck-name disclosures
as Sources, including active and archived decks with no matching cards. These
deck disclosures start collapsed and independently preserve their state across
polling, manual refreshes, searches, filters, edits, and card actions while the
deck continues to exist. Cards also expose schedules, lifecycle actions, edits, and bulk
actions for shown drafts. Sources group stable snapshots under an alphabetical
list of every active and archived deck, including decks without snapshots. Each
deck is an accessible disclosure labeled with its exact name; disclosures start
collapsed and independently retain their open or closed state across five-second
polling and manual refreshes while the deck continues to exist. Snapshots retain
the source endpoint's newest-first order within their deck. The dashboard omits a
redundant trailing `— intent` or `- intent` from displayed snapshot titles without
changing stored titles or API payloads. Source identifiers that the browser URL
parser recognizes as complete HTTP or HTTPS URLs render as links that open in a
new tab with `noopener noreferrer`; their labels omit only the displayed scheme
while preserving the host, explicit port, path, query, and fragment. The link
target retains the complete original URI. Malformed URLs and non-web schemes
such as `file://` and `project://` remain escaped plain text. History shows recent
sessions and review events. Deck controls provide reversible archive/restore and
portable JSON downloads.

The header, navigation, and main dashboard content share a centered responsive
container with a maximum width of 1440px and fluid side gutters. Ultrawide space
remains as balanced outer margin; the dashboard retains its two-column desktop
grid and existing single-column tablet and mobile layouts rather than adding
columns at wider viewports.

Authenticated JSON routes:

- `GET /api/overview`, `/api/decks`, `/api/cards`, `/api/sources`,
  `/api/sessions`, and `/api/reviews`
- `POST /api/actions/draft-status`, `/api/actions/draft-edit`,
  `/api/actions/suspension`, `/api/actions/archive`, and
  `/api/actions/reset-edit`
- `GET /api/export/{deck_id}` for a portable JSON download

The launcher binds only to `127.0.0.1`. Every API call requires a per-launch bearer
token. Host must be localhost and Origin, when present, must match localhost and
the selected port. Assets are bundled locally. Responses disable caching and set
a restrictive content security policy. Dashboard actions use external-script
event listeners and data attributes rather than inline event handlers, so draft,
card, and deck controls remain compatible with `script-src 'self'` without
weakening the policy.

## Testing, installation, and development

Install dependencies with `.venv\Scripts\python.exe -m pip install -r
requirements.txt`. Run unit/API/migration/security tests with `.venv\Scripts\
python.exe -m unittest discover -s tests -v`. Run `scripts/check_docs.py` to
ensure every SQLite table and decorated MCP tool in `server.py` appears here.
Run skill validation and plugin validation before release.

Launch with `launch-dashboard.cmd`. The MCP process and dashboard may run
concurrently against WAL-mode SQLite. Development updates finish by updating this
document, applying the plugin cachebuster helper, validating, and reinstalling the
local marketplace plugin. The project is maintained as a local Git repository;
source, tests, documentation, plugin metadata, and the empty `data/` directory
marker are versioned, while the virtual environment, Python caches, test
artifacts, logs, and live SQLite data are ignored.

`scripts/reschedule_supplemental.py` deterministically replays every active
card's current epoch from `initial_fsrs_json`. It defaults to a read-only dry run;
`--apply` rewrites review before/after snapshots and card schedules in one
transaction, increments changed card versions, and records policy version plus
old/new due dates in `audit_events`. Rollout requires a timestamped SQLite backup,
a reviewed dry run, then an apply run. Repeating an applied replay is idempotent.

## Current implementation status

Implemented for 0.2.1 on 2026-07-28: two-plugin public repository layout;
synchronized Claude and Codex manifests and marketplace catalogs; portable
PowerShell MCP launchers; versioned shared runtime staging beneath
`%LOCALAPPDATA%\SemanticSRS`; isolated lock-hash-aware environments; optional
Local RAG; idempotent setup/update; guarded legacy migration; data-preserving
uninstall with explicit purge; MIT, privacy, security, contribution, changelog,
release, backup, troubleshooting, and clean-room documentation; Local RAG mock
tests; installer tests; release hygiene validation; and Windows GitHub Actions.
The developer's pre-release SQLite and Qdrant stores were backed up before the
repository restructure.

Implemented on 2026-07-28: canonical documentation and agent enforcement;
stable Local RAG discovery pointer verified against representative development
queries;
idempotent migrations for deck status/version, scheduling epoch, and audit actor;
current-epoch review tagging and supplemental-policy replay;
dashboard overview/cards/sources/sessions/reviews; draft approval/rejection/edit;
card suspension/restoration; deck archive/restore service and API; confirmed
active-card reset edits with preserved history; JSON export downloads;
localhost/token/Host/Origin controls; bundled offline UI; five-second refresh;
dashboard summary, suspension, and archival MCP tools.

The established review flow, correction flow, source deduplication, optimistic
card writes, UTC dates, and WAL mode remain implemented. FSRS 6 supplies the
baseline memory model, while supplemental policy `supplemental-v1` bounds
long-term intervals using exposure, consecutive Easy performance, and average
semantic correctness. Normal reviews and grade corrections share this scheduler
path; corrections deterministically replay the current epoch.
Card answer disclosures use the exact `Answer` label, omit source identifiers,
and preserve their per-card open or closed state during card-list refreshes.
Cards are grouped by `deck_id` beneath exact deck-name disclosures, with empty
and archived decks included and per-deck disclosure state preserved independently
from each card's Answer disclosure. Card status pills are vertically centered
against their card-header content.
Source snapshots are grouped by `deck_id` beneath exact deck-name disclosures,
with empty and archived decks included, and preserve per-deck disclosure state
during dashboard refreshes. Redundant trailing intent labels are hidden in
displayed source titles while remaining intact in source data. Valid HTTP and
HTTPS source identifiers are clickable, scheme-free-label new-tab links; other
source identifiers remain escaped plain text. All generated action buttons are
wired by delegated listeners in the bundled script and require no CSP exception
for inline JavaScript.

## Known limitations and deferred features

- The `v0.2.1` tag/release, official host CLI
  validation, and clean Windows clone/ZIP smoke tests require external
  authenticated hosts and remain release gates rather than locally completed
  work.

- The shared `service.py` is currently a compatibility facade over the established
  MCP module. A future cleanup may move all transport-neutral functions into it
  without changing interfaces.
- Suspension controls are currently single-card in the UI, although the JSON route
  accepts bulk card IDs.
- Review trend uses daily averages rather than a configurable smoothing model.
- Import/restore, permanent deletion, multi-user access, remote binding,
  independent grading, and an autonomous documentation daemon are intentionally
  out of scope.

## Decision log

- 2026-07-28: Package version 0.2.1 as two independent plugins with Local RAG
  installed by default but omitted from hard dependencies.
- 2026-07-28: Resolve all runtime paths from `%LOCALAPPDATA%\SemanticSRS` through
  portable PowerShell launchers so Claude Code and Codex share learner state.
- 2026-07-28: Preserve data by default during update and uninstall, and refuse
  automatic migration merges when both source and destination stores are nonempty.
- 2026-07-28: Ship the sourced Imperial Russia Monarchs deck as a validated,
  unreviewed showcase export rather than bundling live learner data.
- 2026-07-28: Trigger the review skill on dashboard requests and launch the
  installed dashboard through a detached PowerShell process.

- 2026-07-28: Make `PROJECT.md` canonical and index only a stable Local RAG
  discovery pointer so documentation edits cannot leave stale semantic chunks.
- 2026-07-28: Pair semantic discovery with `AGENTS.md` because retrieval wording
  cannot guarantee enforcement.
- 2026-07-28: Keep conversational review and semantic grading exclusively in
  Codex; the dashboard is an administrative and visualization surface.
- 2026-07-28: Use single-user localhost plus an ephemeral bearer token, strict
  Host/Origin checks, and offline assets as the dashboard security boundary.
- 2026-07-28: Preserve review history during confirmed active-card edits while
  resetting only current scheduling state and counters.
- 2026-07-28: Cap the shared dashboard content container at 1440px, center it
  with responsive side gutters, and preserve the existing two-column maximum.
- 2026-07-28: Label card answer disclosures exactly `Answer`, show only required
  concepts there, and preserve disclosure state across card-list rerenders while
  cards remain displayed.
- 2026-07-28: Group Sources under exact deck-name disclosures, include empty and
  archived decks, preserve source order, and retain disclosure state across
  polling and manual refreshes.
- 2026-07-28: Group Cards under the same refresh-stable deck disclosures as
  Sources, including empty and archived decks, while preserving Answer state
  independently.
- 2026-07-28: Hide a trailing `— intent` or `- intent` from source titles in the
  dashboard only; preserve immutable snapshots and API responses.
- 2026-07-28: Make only browser-parseable HTTP and HTTPS source identifiers
  clickable in Sources, preserve the complete URI as the target, hide only the
  displayed scheme, and keep malformed or non-web identifiers escaped text.
- 2026-07-28: Keep `script-src 'self'` strict and wire dynamic dashboard action
  buttons through external-script event delegation rather than inline handlers.
- 2026-07-28: Keep the project in local Git while excluding reproducible
  environments, generated caches, logs, test artifacts, and live learner data.
- 2026-07-28: Retain FSRS 6 stability and difficulty as the baseline memory
  model, then apply `supplemental-v1` to intervals of at least one day using
  current-epoch exposure, Easy streak, and average semantic correctness.
- 2026-07-28: Make supplemental rollout a backed-up, dry-run-first,
  transactional replay that rewrites review scheduling snapshots and records
  old/new due-date audits without changing MCP response shapes.

## Completed milestone log

- 2026-07-28: Reorganized the repository for the Windows 0.2.1 marketplace
  release, imported maintained Local RAG source, and added shared runtime
  lifecycle tooling, documentation, automated tests, and CI.
- 2026-07-28: Added the 30-card Imperial Russia Monarchs deck as a validated
  showcase export with 15 public source snapshots and no review history.
- 2026-07-28: Made dashboard discovery and background launch an explicit review
  skill capability for Claude and Codex.

- 2026-07-28: Initial Semantic SRS plugin, FSRS scheduler, SQLite persistence,
  source snapshots, drafts, review sessions, correction, stats, and export.
- 2026-07-28: Canonical living-document workflow and documentation consistency
  checker added; stable RAG pointer registered and retrieval verified.
- 2026-07-28: Local dashboard service, authenticated API, offline UI, launcher,
  non-destructive migrations, audit behavior, and expanded MCP management tools
  implemented.
- 2026-07-28: Simplified card answer disclosures and stabilized their state
  across dashboard polling and other card-list rerenders.
- 2026-07-28: Grouped source snapshots by deck with accessible, refresh-stable
  disclosures for all active and archived decks.
- 2026-07-28: Grouped cards by deck with the same accessible, refresh-stable
  disclosure behavior as Sources.
- 2026-07-28: Removed redundant intent suffixes from displayed source titles
  without modifying stored source snapshots.
- 2026-07-28: Added secure new-tab links for HTTP and HTTPS source identifiers
  with scheme-free labels and plain-text fallback for all other identifiers.
- 2026-07-28: Removed CSP-blocked inline action handlers and restored draft,
  card, and deck controls with delegated listeners.
- 2026-07-28: Initialized local source control with runtime and learner-data
  exclusions.
- 2026-07-28: Added supplemental FSRS interval policy, deterministic
  current-epoch rescheduling and correction replay, migration audits, tests, and
  rollout tooling.
