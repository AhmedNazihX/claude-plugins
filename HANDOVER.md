# Handover — 2026-09-30

Where the plugin work stands, for the next session (the trial session in a throwaway trial repo, or a session
opened in this repo). The capstone below is an earlier private project whose older copies of these skills were ported.

## State

- **This repo** (a local clone, not pushed yet) is the `nazihx` marketplace with
  two plugins:
  - `story-workflow` **0.3.5**: skills `next`, `kickoff`, `work-breakdown`, `setup`, `guardrails`, `status`,
    `story-start`, `story-finish`, `decision`, `handover`; agents `story-worker`, `dod-verifier`, `diff-reviewer`,
    `security-reviewer`, `backlog-reviewer`, `lane-auditor`, `test-auditor`; hooks `gate.sh`, `lane-guard.sh`,
    `worker-guard.sh` (PreToolUse), `format.sh` (PostToolUse); `scripts/backlog.py`. Depends on `git-guardrails`.
  - `git-guardrails` **0.2.1**: `block-dangerous-git.sh` and `block-secrets.sh` as plugin hooks.
- **Installed** at user scope (`claude plugin install story-workflow@nazihx`); the dependency installed itself.
- **Global guards removed** from the user settings (only the two `block-*.sh` PreToolUse entries; a backup was
  kept). The old scripts are still in `~/.claude/hooks/`, unused; delete them once the plugin guards are confirmed
  live.
- **Old user-level skills archived** (2026-09-30): `story-workflow` (installer), `work-breakdown` and
  `git-guardrails` (installer). The global `backlog-reviewer` agent now calls this repo's
  `story-workflow/scripts/backlog.py`.
- **Plugin files load straight from this repo** (local marketplace): an edit takes effect after `/reload-plugins`.
- **Tests, all passing:** `python3 -m unittest discover -s story-workflow/tests` (39),
  `bash story-workflow/hooks/test-guards.sh` (81), `bash story-workflow/hooks/test-format.sh` (8),
  `bash git-guardrails/tests/test-guards.sh` (55), `claude plugin validate` on `.`, `story-workflow`, `git-guardrails`.
- `docs/story-workflow-merge-plan.md` records what was ported from the capstone and what is left.

## The end-to-end trial (checklist)

In a fresh session in the trial repo: `claude`, then `/story-workflow:next`. The repo holds one
committed `intention.md` (a reading-list CLI, two weekends, parallel agents welcome). Check:

1. `next` picks `kickoff`; questions come **one at a time**, each with a recommendation.
2. `docs/DESIGN.md` gets every heading, including *Rules and enforcement*; the stress-test step runs before approval.
3. After approval, `next` → `work-breakdown` → `backlog-reviewer` (then `Reviewed:` line) → `setup`.
4. `setup` writes `.claude/story-workflow.json` (with `format`), and `guardrails` produces at least one scoped rule or
   project hook with a test, recorded in the `guardrails` registry.
5. A `git push` asks first (the `git-guardrails` hooks are live); `cat .env` is blocked; `jq '.key'` is not.
6. `status` → `story-start` → a worker in a worktree → `story-finish` runs its reviews without asking, and hands
   follow-ups over as `**From <ID> (merged):**` notes.

Write down each thing that looks off and fix it in this repo; bump the version and reinstall
(`claude plugin install story-workflow@nazihx` again, or `/plugin` to update).

## Since this handover was first written

- A fresh review found 1 critical and 8 major issues; all are fixed and covered by tests (0.2.1). The top block
  of additions is in 0.3.0: `backlog.py note/set-deps/add`, the worker guard, the `handover` skill and the
  `test-auditor` agent. See `docs/story-workflow-merge-plan.md` § 6c.
- **End-to-end trial** (a throwaway trial repo, 2026-09-30): kickoff → work-breakdown → backlog review →
  setup (with guardrails: 8 rules, a scoped rule, a gate) → story F1 through story-start and story-finish (DoD,
  diff review, test audit, two fix rounds, merge on the user's go-ahead, tick, hand-over notes). Findings fixed in
  0.3.1–0.3.2: steps now run back to back; one copy of the check commands; `next` defers to a project's own copy.
- **Second review** (0.3.3): 5 major findings fixed and tested (worker guard bypasses, note injection, set-deps on
  sub-stories, test-auditor baseline). The SubagentStop reminder was **removed**: its additionalContext reached
  only the worker's transcript, never the parent (the earlier claim that it worked was wrong).
- **0.3.4:** the `security-reviewer` agent, run on every story by default.
- **Trial, stories** (0.3.4–0.3.5): S1 went through two fix rounds with a security review, then merged. C6 was
  split into C6a and C6b with `backlog.py`. S2 and C6a ran in parallel, the first live run of two stories at once.
  Findings fixed in 0.3.5: the worker guard no longer blocks the orchestrator's merge when its shell is left in a
  worktree (the guard applies to subagents only), `story-finish` runs git from the main checkout, and a security
  fix is re-checked by the `security-reviewer`. See `docs/story-workflow-merge-plan.md` § 6e.
- **Not yet covered live:** a lane with a deny list (sparse checkout, CLAUDE_PROJECT_DIR inside a worktree).

## Still open

- Needs the user: pushing this repo to its public GitHub remote; deleting `~/.claude/hooks/block-*.sh` (unused
  since the plugin guards are live); version tags (`story-workflow--v0.3.5`, `git-guardrails--v0.2.1`).
- A `WorktreeCreate` hook that applies a lane's sparse checkout itself (removes the manual `!` step): its input and
  contract are undocumented (checked 2026-09-30); prototype with `claude --debug`, keep the manual path as fallback.
- Evals with `claude plugin eval` for `next`, `status`, `story-start`, `kickoff`; the suggestion list (replan,
  SessionStart status, PreCompact reminder, cost totals, rule templates, adopt). (docs/story-workflow-merge-plan.md § 7)
- After the capstone: move the capstone onto the plugin (delete its `.claude/` copies, keep its own `case` and
  `eval` skills, `isolation-auditor` and rules).

## Gotchas learned

- Plugin agents ignore `hooks`, `permissionMode` and `mcpServers` frontmatter; `isolation: worktree` works.
- A plugin can't set project settings (`worktree.baseRef`, permissions): `setup` writes them into the project.
- Quote `"${CLAUDE_PLUGIN_ROOT}/…"` in hook commands (validate warns otherwise).
- The capstone's `ruff-format.sh` hook reformats any edited `.py`, including files in this repo when edited from the
  capstone session; edit this repo from a session opened here.
- Several `!` commands pasted together run the later ones as shell negation: give the user one line joined with `&&`.
