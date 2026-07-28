# Semantic SRS

Semantic SRS is a private, conversational spaced-repetition system for Claude
Code and Codex on Windows. It grades answers by meaning, schedules with FSRS,
and includes a localhost dashboard. The bundled Local RAG companion can index
your files and supply sourced excerpts; it is installed by default but remains
optional.

Version 0.2.1 supports Windows 10/11 x64, CPython 3.11, internet access during
setup, and at least one installed host. Both hosts share the same learner data.

## Install

Clone with Git or download and extract the GitHub ZIP. From the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

Interactive setup detects Claude Code and Codex and recommends all installed
hosts plus Local RAG. Automated examples:

```powershell
.\setup.ps1 -Host Both -NonInteractive
.\setup.ps1 -Host Codex -SkipLocalRag -NonInteractive
```

Setup creates isolated environments and versioned application code beneath
`%LOCALAPPDATA%\SemanticSRS`. Repeated runs preserve data and reinstall
dependencies only when a requirement lock changes.

## First review and retrieval

Ask your host to “Create a sourced study deck from this text,” approve the card
drafts it presents, then ask to “Start my due-card review.” The answer rubric and
FSRS rating stay private while you answer.

With Local RAG installed, ask “Index `C:\path\to\documents` in Local RAG,” then
ask a source-related question. The embedding model downloads once on first use;
afterward storage and retrieval remain local. Without Local RAG, paste material
or provide readable file paths.

## Showcase deck

The repository ships with
[`showcase/imperial-russia-monarchs.json`](showcase/imperial-russia-monarchs.json),
a sourced 30-card draft deck covering all fourteen emperors and empresses of
Imperial Russia from 1721 through 1917. Ask your host to create the showcase deck
from that file, then review and approve its drafts normally. The bundled export
contains public source snapshots and unreviewed cards, not developer learning
history or live database data.

## Dashboard

After setup, launch from the downloaded repository:

```powershell
.\plugins\semantic-srs\launch-dashboard.ps1
```

The dashboard opens a tokenized localhost URL and uses the same database as both
hosts. After setup, Claude or Codex can also launch it when asked to “Open the
Semantic SRS dashboard.”

## Update and uninstall

Download/pull the new repository version, then run:

```powershell
.\update.ps1 -Host Both
.\uninstall.ps1 -Host Both
```

Uninstall removes host registrations and runtime code but preserves learner data.
Only `.\uninstall.ps1 -Host Both -PurgeData` permanently removes data and
backups.

## Data, privacy, and backups

Persistent locations:

- `%LOCALAPPDATA%\SemanticSRS\data\semantic-srs.sqlite3`
- `%LOCALAPPDATA%\SemanticSRS\rag\qdrant`
- `%LOCALAPPDATA%\SemanticSRS\rag\models`
- `%LOCALAPPDATA%\SemanticSRS\backups`

Semantic SRS and Local RAG store content locally, make no telemetry calls, and
access the network only for dependency and embedding-model downloads. Unrelated
RAG installations are not modified and can coexist.

Stop both hosts and the dashboard before backup. Copy the `data` and `rag`
directories to protected storage. Deck JSON can also be downloaded from the
dashboard. Restore only into an empty destination; the installer refuses to
merge two nonempty stores automatically.

When the destination is empty, interactive setup offers to migrate a legacy
repository `data` directory and `%USERPROFILE%\local-rag-data`. For automation,
add `-MigrateLegacy`.

## Troubleshooting

- `Neither Codex nor Claude Code was detected`: install a host or pass the
  correct `-Host` value after its CLI is on `PATH`.
- `Python failed`: verify `py -3.11 --version`.
- Missing runtime: rerun `setup.ps1`; it is idempotent.
- Qdrant lock error: stop other Local RAG host processes, then retry.
- Dashboard does not open: copy its printed `127.0.0.1` URL into your browser.
- Paths with spaces are supported; use PowerShell's quoted literal paths.

Manual host commands use the `Aeskyr/semantic-srs` marketplace and install
`semantic-srs@semantic-srs`, plus `local-rag@semantic-srs` when desired.

## Development and release

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and
[RELEASE.md](RELEASE.md). Run:

```powershell
.\scripts\verify-release.ps1
```

The project is MIT licensed. Public directory submission for OpenAI or Claude,
macOS/Linux/WSL support, and packaged executable installers are outside 0.2.1.
