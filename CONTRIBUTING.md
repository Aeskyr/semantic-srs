# Contributing

Semantic SRS 0.2.x targets Windows 10/11 x64 and CPython 3.11. Fork the
repository, create a focused branch, and keep code, tests, documentation, and
`PROJECT.md` synchronized. Never commit learner data, vector collections, model
caches, virtual environments, logs, tokens, or generated host configuration.

Run `powershell -File scripts/verify-release.ps1` before opening a pull request.
Installer changes must be tested with a temporary `LOCALAPPDATA`, paths
containing spaces, and fake host executables. Contributions are accepted under
the MIT license.
