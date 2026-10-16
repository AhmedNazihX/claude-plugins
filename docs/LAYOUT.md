# Repo layout

This file is the single source of truth for where things live. Every *Output* path in `docs/BACKLOG.md` must fit
this layout. A story that adds a new folder, or a new top-level file, updates this file in the same branch.
`CLAUDE.md` keeps a short summary of it.

## Tree

Story IDs in brackets create or first change the path. Unmarked paths exist already.

```
.
├── CLAUDE.md                          project rules for Claude Code (short; links here)
├── README.md                          the marketplace README
├── .claude-plugin/marketplace.json    the nazihx marketplace
├── .github/workflows/test.yml         CI: tests, hook tests, lint, plugin validate (F2)
├── .claude/foreman.json               the workflow config for this repo (setup)
├── .gitattributes                     `foreman/CHANGELOG.md merge=union` (planning)
├── .claude/worktrees/                 ⚠ gitignored: worker worktrees, workers.json, handoffs/, ledger.tsv, ANDON,
│                                        attention.log
├── .claude/foreman-autopilot.json     ⚠ gitignored: autopilot state (B4, B5)
├── .claude/foreman-retro-index.json   ⚠ gitignored: retro transcript index (B7)
│
├── foreman/
│   ├── .claude-plugin/plugin.json     the version: release stories only (V1, V2, V3)
│   ├── CHANGELOG.md                   stories append under "## Unreleased" (F1 adds it); release stories number it
│   ├── README.md                      the version line: release stories only
│   ├── HANDOVER.md                    ⚠ untracked: the maintainer's notes from real runs
│   ├── agents/<name>.md               one file per agent; name = file name
│   │   ├── readiness-auditor.md       (R12)
│   │   └── advisor.md                 (B2)
│   ├── skills/<name>/SKILL.md         one folder per skill; name = folder name
│   │   ├── autopilot/SKILL.md         (B5)
│   │   └── retro/SKILL.md             (B8)
│   ├── hooks/
│   │   ├── hooks.json                 hook registration (shared: Resource hooks-config)
│   │   ├── <name>.sh                  one hook per file, executable
│   │   ├── test-<name>.sh             its test: blocks the forbidden case, passes a near-miss
│   │   ├── report-gate.sh             SubagentStop gate for story-worker (R4)
│   │   ├── workaround-guard.sh        (B1)
│   │   ├── autopilot-stop.sh          (B4)
│   │   └── lib/                       shared shell helpers
│   ├── scripts/                       Python 3, standard library only; each has a docstring with usage
│   │   ├── backlog.py
│   │   ├── workers.py
│   │   ├── lint.py                    (F1)
│   │   ├── pages.py                   HTML pages: merge page, status page (B9, B10)
│   │   └── retro.py                   transcript index for the retro (B7)
│   ├── templates/
│   │   ├── foreman.example.json       every config key, with an example
│   │   ├── worker-brief.md            the story-worker launch prompt template (R13)
│   │   └── page.css                   shared style for pages.py output, inlined at render (B9)
│   └── tests/
│       ├── test_<script>.py           one file per script: test_backlog, test_workers, test_lint (F1), test_retro (B7), test_pages (B9)
│       └── fixtures/                  sample backlogs, transcripts (synthetic only, never copied from real ones), configs
│
├── git-guardrails/                    the dependency plugin; not changed by this backlog
└── docs/
    ├── DESIGN.md                      the approved design
    ├── BACKLOG.md                     this backlog
    ├── LAYOUT.md                      this file
    ├── foreman-merge-plan.md          historical (the 0.1 port plan)
    ├── decisions/NNN-<slug>.md        decision records; 001–003 reserved for X1–X3, 004 for R3
    └── trials/<date>-<wave>.md        trial notes from real use (H2)
```

## Rules

| Rule | Why |
| --- | --- |
| Scripts are Python 3 standard library only, under `foreman/scripts/`, each a CLI with subcommands | The plugin installs with no dependencies |
| Every hook is its own executable `foreman/hooks/<name>.sh` with a `test-<name>.sh` next to it; registration only in `hooks.json` | CI runs every `test-*.sh` by glob, so a new hook's test runs without editing the workflow |
| Tests mirror the scripts: `foreman/tests/test_<script>.py`; fixtures are synthetic | Easy to find; real transcripts may hold private project data |
| Agent `name` = file name, skill `name` = folder name | The lint (F1) checks it; `foreman:<name>` references resolve |
| Only V1, V2, V3 change `plugin.json`'s version and the README version line (F1 corrects the stale README once); others append under `## Unreleased`, merged with `merge=union` | User decision 2026-10-16: no version collisions between parallel stories |
| Runtime state lives in the main checkout's gitignored `.claude/worktrees/`, never in the repo | It belongs to one machine's session, not to the project |
| A new folder or top-level file gets an entry here in the same story | Keeps this file the source of truth |
