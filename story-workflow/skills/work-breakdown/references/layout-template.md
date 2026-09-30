# Repo layout

This file is the single source of truth for where things live. Every *Output* path in `docs/BACKLOG.md` must fit
this layout. A story that adds a new folder, or a new top-level file, updates this file in the same branch.
`CLAUDE.md` keeps a short summary of it.

## Tree

<Draw the tree down to the key files. After each path, write what it holds and the story that creates it, in
brackets. Mark gitignored, generated and gated paths.>

```
.
├── CLAUDE.md                        project rules for Claude Code (short; links here)
├── README.md                        (W1)
├── .github/workflows/ci.yml         (F2)
│
├── <app>/                           <the main project, e.g. backend/ with its package manager>
│   ├── <manifest>                   <pyproject.toml / package.json> (F1)
│   ├── <package>/                   all application code lives here
│   │   ├── cli.<ext>                command root: scripts are subcommands, not loose files (F1)
│   │   ├── <area>/                  <what it holds> (<story IDs>)
│   │   └── <gated area>/            ⚠ created only after <gate story> (hook-enforced)
│   └── tests/                       mirrors the package; fixtures/, recordings/
│
├── data/                            <inputs the app reads; raw/ gitignored>
├── <fenced data folder>/            <data only, no code; lane X never reads it>
├── <infra>/                         <migrations, seeds, config>
└── docs/
    ├── BACKLOG.md
    ├── LAYOUT.md                    this file
    └── decisions/NNN-<slug>.md
```

## Rules

| Rule | Why |
| --- | --- |
| All code lives in `<app>/<package>/`. Scripts are CLI subcommands, not loose files | One lint, type-check and test setup; scripts can import the package |
| `<fenced data folder>/` holds data only, and code that reads it lives in the package | A pure data folder can be excluded by sparse checkout and guarded by a hook |
| Tests mirror the package: `tests/<area>/test_<module>.<ext>` | Tests are easy to find; the verifier can check coverage |
| Migrations are created only with `<tool> migration new`, and a merged migration is never edited | Parallel stories can't collide |
| Gitignored: `<.env, raw data, private data, agent worktrees>` | Secrets, large files, licensing |
| A new top-level folder or package area gets an entry here, in the same story that adds it | Keeps this file the source of truth |
