---
name: setup
description: Configures a repo that has a story backlog (docs/BACKLOG.md) for the story workflow — writes .claude/foreman.json (checks, gitignored files to link, shared env, reviewers, lanes that must not see some folders, per-story exceptions, mechanical gates), the project settings a plugin can't set (worktree.baseRef, permissions), the .gitignore entries and the CLAUDE.md section, then verifies the guards. Use after work-breakdown, when the user wants agents to run stories in parallel, or to change the workflow config.
argument-hint: "[--no-guards]"
---

# Set up the story workflow

The plugin ships the skills, agents, hooks and `backlog.py`; nothing is copied into the repo. This skill writes
only the project's own facts. Everything project-specific lives in `.claude/foreman.json` and in the
backlog's tags (`Lane`, `Solo`, `Resource`).

## 1. Preconditions

- A git repo with a clean main checkout. Work on the planning branch (`planning/<yyyy-mm-dd>`, see `next`), or
  create it from the base branch; `next` merges it into the base branch with the user's go-ahead.
- `docs/BACKLOG.md` exists and `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py check` reports OK. If not, run
  `next` instead.
- `jq` is installed.
- If `.claude/settings.json`, `.claude/foreman.json` or a CLAUDE.md section already exist, show the
  difference and ask before changing them. Never overwrite silently.

## 2. Collect the project's facts

Detect what you can; ask only for the rest, **one question at a time**, with a recommended answer.

| Config key | How to fill it |
| --- | --- |
| `base_branch` | `git symbolic-ref refs/remotes/origin/HEAD`, or the current branch |
| `checks` | Copied **verbatim** from the backlog's **Global rules for every story** section (the marker is a bold line, not a heading — find it with `rg -n -i -A6 'global rules' docs/BACKLOG.md` rather than reading the whole backlog). Look for a `- **Checks:**` line with the commands, or (once a project has already run `setup` before) a line pointing at `.claude/foreman.json` › `checks` instead — follow that pointer rather than re-typing stale commands. Else derive from the repo: `pyproject.toml` means uv/ruff/pyright/pytest, `package.json` scripts mean lint, typecheck, test. Confirm with the user. Before the scaffold story exists, use the commands it will create and say so. |
| `link_files` | Gitignored local files a worker needs, such as `.env` (from `.gitignore` and `.env.example`) |
| `env` | Shared paths workers need, e.g. `{"APP_DATA_DIR": "{MAIN}/data"}`; empty if none |
| `reviewers` | Review agents run by `story-finish` on every story; default `["foreman:diff-reviewer", "foreman:security-reviewer"]` (the security reviewer judges each diff against the design's *Data, security and compliance* section) |
| `lanes` | Only lanes that must **not see** some folders (a benchmark, an answer key): `{"<Lane>": {"deny": ["<folder>"], "allow": [], "reviewers": []}}` |
| `stories` | Per-story exceptions that override the lane, e.g. one story allowed to read one file |
| `gates` | Mechanically checkable gates from the design: "nothing under `<path>` until `<file>` is committed" |
| `format` | Path prefix → formatter command run from that folder, e.g. `{"backend/": "uv run ruff format {file}"}` (from the stack). The plugin's formatter hook uses it; leave it empty to format nothing |
| `cost_cap_usd` | The most a worker may spend on paid calls without asking (from the design's constraints) |
| `isolation` | For lanes with a deny list: the project's own isolation test command (`test`), the design section that states the rules (`design_section`), and folders that must never be tracked (`private`). The `lane-auditor` reads it |
| `decisions.reserved` | Decision numbers the backlog reserves for specific stories, e.g. `{"003": "X1 model choice"}` |
| `max_review_stories` | How many `mixed`/`human` stories `status` may put in one launch set (default 2) |
| `docs` | `{"max_bytes": 20000, "exclude": []}`: blocks loading a `.md` file whole past `max_bytes` (the `doc-reader` agent or a search-and-range read is the way around it), so a growing backlog or design doc never fills an agent's context |

Find `lanes` and `gates` candidates in the design's Gates and Data sections and the backlog's gate stories.
Leave them empty if there are none or the user passed `--no-guards`. The plugin's hooks do nothing without them.

## 3. Write

- `.claude/foreman.json` from the facts; `${CLAUDE_PLUGIN_ROOT}/templates/foreman.example.json`
  shows the shape.
- `.claude/settings.json`, merged with `jq`, keeping everything already there:
  - `worktree.baseRef: "head"`, so worktrees branch from the local HEAD.
  - Permissions for the helper go in `.claude/settings.local.json` (per machine, not committed): the resolved
    plugin path holds the user's home folder and, for a cached plugin, its version. Show the diff first.
- `.gitignore`: `.claude/worktrees/` and `.claude/settings.local.json`, if missing.
- **One copy of the checks:** once `checks` is written, replace the commands in the backlog's *Global rules › Checks*
  line, and any copy in `CLAUDE.md`, with a pointer: "the `checks` in `.claude/foreman.json`". The config
  is then the only list, and the one the workers, the verifier and `story-finish` run.
- `CLAUDE.md`: append `${CLAUDE_PLUGIN_ROOT}/templates/claude-md-section.md`, plus the project's own rules for
  shared resources (for example "create migrations only with `<tool> migration new`"). If `CLAUDE.md` doesn't exist,
  create a short one that points to `docs/DESIGN.md` and `docs/BACKLOG.md`.

Then run the **guardrails** skill: it turns the design's *Rules and enforcement* section (and the decisions) into
built-in hook config, project hooks with tests, scoped `.claude/rules/*.md`, reviewer checks and CLAUDE.md lines,
and records each in the config's `guardrails` registry.

## 4. Verify

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py check
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py plan
bash ${CLAUDE_PLUGIN_ROOT}/hooks/test-guards.sh      # only if lanes or gates are configured
bash ${CLAUDE_PLUGIN_ROOT}/hooks/test-doc-guard.sh   # only if docs is configured
jq empty .claude/settings.json .claude/foreman.json
```

Also run one live check per gate: send a sample Write to the gated path through `gate.sh`; it must exit 2 before
the required file is committed. New settings may need a Claude Code restart; tell the user.

## 5. Hand over

List what was written, then go back to `next` (without asking), which merges the planning branch with the user's
go-ahead. The loop: `/foreman:status` shows what can run, `/foreman:story-start <IDs>`
launches workers, `/foreman:story-finish <ID>` reviews and merges; `/foreman:next` always picks the
right step. Offer to commit. The first backlog story is usually `Solo` (the scaffold), since every worktree
branches from it.
