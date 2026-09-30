# <Project name> — Build Backlog

## Context
<Two or three sentences: what the project is, which documents define it (paths), and why this backlog exists.>
<The timeline, and what scope it allows.>

The design sets these ordering rules (gates), which this backlog enforces:
- **<Gate name>:** <what must happen before what> (<design doc › section>).
- …

---

## How to use this backlog

**Picking up a story with a fresh context:** read (1) `CLAUDE.md`, (2) the story, (3) the design sections named in its
*Context* line, (4) the files in its *Input*. Nothing else should be needed. Where a new file goes is fixed by `docs/LAYOUT.md`, and
every *Output* path fits it.

**Story format**
- **Deps:** stories that must be done first.
- **Type:** `agent` (can be delegated fully), `human` (needs the user), `mixed` (an agent drafts, the user approves).
- **Context:** design sections to read. **Input:** files and data consumed. **Output:** files produced. **DoD:** checkable definition of done.
- **Optional tags:** `Lane`, `Size` (S/M/L), `Solo` (runs alone), `Resource` (a shared thing it changes).

**Commands** (`backlog.py` ships with the `story-workflow` plugin: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py …`):
- `backlog.py check`: validate the backlog.
- `backlog.py plan`: the critical path and waves.
- `backlog.py status`: what's ready now.
- `backlog.py tick <ID> "<note>"`: tick a story after its merge.

**Global rules for every story**
- **Checks:** <the exact commands, e.g. `uv run ruff check . && uv run ruff format --check .`, `uv run pytest -q`>.
  This is the only list of them until `setup` copies it, verbatim, into `.claude/story-workflow.json` › `checks`;
  after that, this line points to the config instead. Stories say "the global checks pass", never the commands.
- <Rules that protect the gates, e.g. "lane X never reads folder Y".>
- <How decisions are recorded, e.g. `docs/decisions/NNN-title.md`.>
- <How external or live calls are handled in tests.>

---

## Critical path
<Paste the output of `backlog.py graph` here. Re-run it after every change to the deps; never edit this by hand.>

## Lanes

| Lane | Stories | Notes |
| --- | --- | --- |
| <Infra> | <F1, F2, …> | <e.g. F1 first; the rest fan out right after> |

## Waves
<Paste the output of `backlog.py plan` here.>

---

## Phase 0 — Foundations

- [ ] **F0 · Put the backlog in the repo** · Deps: – · Type: agent · Size: S
  Input: this plan. Output: `docs/BACKLOG.md`, `docs/LAYOUT.md`, and a `CLAUDE.md` holding the global rules, a short layout summary
  (linking to `docs/LAYOUT.md`) and the standard commands.
  DoD: all three files committed; `backlog.py check` reports OK; every Output path in the backlog fits `docs/LAYOUT.md`.

- [ ] **F1 · <Scaffold>** · Deps: – · Type: agent · Solo
  Context: <design › tech stack>. Output: <…>.
  DoD: <the project's standard checks pass with one trivial test>.

## Phase 1 — <…>

## Wrap-up

- [ ] **W1 · README and demo** · Deps: <…> · Type: mixed
  Output: <…>. DoD: <…>; the user has reviewed it.
