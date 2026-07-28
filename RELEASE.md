# Release and clean-room verification

1. Confirm the worktree contains no live data, absolute developer paths, secrets,
   caches, virtual environments, generated configuration, or Qdrant files.
2. Run `scripts\verify-release.ps1` and require the GitHub `windows-latest`
   workflow to pass.
3. In clean Windows 10/11 x64 VMs with CPython 3.11, test both a Git clone and a
   GitHub ZIP. Test Claude Code alone, Codex alone, and both together.
4. Create and review a card in Claude Code; inspect the same deck and history in
   Codex. Index and retrieve a source through Local RAG, launch the dashboard,
   restart both hosts, and confirm persistence.
5. Run `update.ps1`; compare hashes/backups of learner data and confirm no data
   changed unexpectedly. Run uninstall with preservation, then separately in a
   disposable profile with `-PurgeData`.
6. Confirm every README command works without undocumented steps.
7. Merge only with a green workflow, tag the exact commit `v0.2.0`, and create a
   GitHub release from that tag with `CHANGELOG.md` notes.

Repository publication, tag pushing, and GitHub release creation require the
maintainer's authenticated GitHub session. Public plugin-directory submissions
are intentionally separate.
