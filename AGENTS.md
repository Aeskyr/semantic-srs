# Semantic SRS agent instructions

Before planning, debugging, reviewing, or modifying this project, read `PROJECT.md`
in full. Treat it as the canonical source of truth for Semantic SRS.

After every accepted plan or implemented change, update `PROJECT.md` to reflect the
current interfaces, schema, behavior, tests, implementation status, roadmap,
decisions, milestones, and relevant dates. Never describe planned work as
implemented. When a plan is created in a non-mutating planning mode, make updating
`PROJECT.md` the first implementation step rather than claiming it has changed.

Before completing implementation work, run:

```powershell
& .\.venv\Scripts\python.exe .\scripts\check_docs.py
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Also validate the review skill and plugin manifest, and keep documentation changes
in the same handoff as their corresponding code changes.

