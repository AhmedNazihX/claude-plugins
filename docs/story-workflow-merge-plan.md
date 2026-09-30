# Merge plan: templates + an earlier project's copies → the plugin

The plugin starts from the **generic templates** (the `story-workflow` and `work-breakdown` user skills), because
they are config-driven and hold no project text. An earlier private project (called "the capstone" below) has
older, hard-coded copies that carry lessons from real use. This plan lists what to port from the project, file by
file. Nothing here changes the capstone: it keeps its own `.claude/` until the capstone is done.

Status: **draft 0.1.0**. The files in this repo are the templates with paths switched to the plugin
(`${CLAUDE_PLUGIN_ROOT}` for bundled files, `${CLAUDE_PROJECT_DIR}/.claude/story-workflow.json` for the config),
plus three new skills (`kickoff`, `next`, `setup`). The ports below are not done yet.

## 1. `scripts/backlog.py`

**Done in 0.1.1:** resource hints (`check` warning, `info.resource_hints`, a `<tag>?` in `status`), the
"waiting on" line, the DoD-input check (`check` warning, `info.dod_input_gaps`, "ready to build, not to finish" in
`status`), and `tests/test_backlog.py` (23 tests). On the capstone backlog the computed critical path matches its
hand-written one, and `check` flags the E3/E4/E6 gap in the version from before it was fixed by hand.

Base: the generic version (409 lines: `check`, `plan`, `status`, `show`, `deps`, `info`, `tick`, `graph`; computed
critical path and waves; `Size`, `Solo`, `Resource`; `--file`). The project copy (≈270 lines) has a hard-coded
critical path and lane rules, which the generic version replaces with `Lane:` tags and the config.

| Port from the project | How, in the generic version |
| --- | --- |
| `may_change_schema` (a story mentions a migration) and the `migration?` tag in `status` | Generalise: `check` warns when a story's text mentions a shared resource (a configurable word list: `migration`, `lockfile`, …) but has no `Resource:` tag; `info` gets `resource_hints` |
| "next on the path is waiting on X: start those first" in `status` | Add to `status` after the critical-path line |
| — (found by hand in the project) DoD inputs missing from `Deps` | `check` warns when a story's DoD or Context names another story ID, or a path listed in another story's Output, that isn't in its `Deps` |
| Sub-story IDs as deps (`B5b`) | Already supported; add a test |

Also: unit tests in `tests/test_backlog.py` against a fixture backlog (every command, grouped entries, ranges,
manual conditions, cycles, the new warnings).

## 2. Skills

**Done in 0.1.2:** the `status`, `story-start` and `story-finish` ports below, and the `story-worker` and
`dod-verifier` ports in section 3. Done in 0.1.3: `decision` (reserved numbers in the config), `work-breakdown`
(`Reviewed:` line, `docs/DESIGN.md` default), the generic `lane-auditor`.

| Skill | Base | Port from the project and this session |
| --- | --- | --- |
| `status` | template | Unpushed commits (`git log origin/<base>..<base>`) and the latest CI run (`gh run list`); the DoD-input check before recommending a story ("ready to build, not to finish"); name what the next critical-path story waits on; `max_review_stories` from the config; resource hints |
| `story-start` | template | Refuse a story with an unmet DoD input unless the user accepts it; tell Corpus-style (deny-lane) workers' sparse-checkout command to the user as **one** `!` line chained with `&&`; state the worker's cost cap from the config in its prompt; say "run alone" from `Solo` tags, not hard-coded IDs |
| `story-finish` | template | **Automatic review loop:** on a worker's DONE, start `dod-verifier`, the configured reviewers and the lane's reviewers without asking; send one combined fix round back to the worker; re-review the fix commit when a finding was major; ask the user only at the merge. **Handover step:** after `tick`, put every worker follow-up and every reviewer "watch in X" note on the stories they affect. After the merge: run the checks on the base branch, offer to push, and watch the CI run |
| `decision` | project | Move the reserved numbers (001–007 in the capstone) to the config (`decisions.reserved`); keep the template and the "every number has a source" rule |
| `work-breakdown` | user skill | Read `docs/DESIGN.md` by default; add a `Reviewed:` line after the backlog review; tag resources during drafting (the DoD-input rule above) |
| `kickoff`, `next`, `setup` | new | Draft in this repo; test on a throwaway project |

## 3. Agents

| Agent | Base | Port |
| --- | --- | --- |
| `story-worker` | template | Paid calls: estimate, stay under `cost_cap_usd`, otherwise report NEEDS USER with the estimate and the exact command; report blocked commands as one `!` line; state in the final report whether anything was read before the lane's sparse checkout was set; the outcome-note and follow-ups sections the project's workers used |
| `dod-verifier` | template | Judge each failing test as "caused by the story" or "pre-existing" by running it at the merge base (what caught C5's fixture regression) |
| `diff-reviewer`, `backlog-reviewer` | user agents | Copy as they are; namespaced as `story-workflow:…` |
| lane auditor | — | Generic `lane-auditor` (the capstone's `isolation-auditor` without the benchmark specifics): reads the config's `lanes`, greps the branch for denied paths, and runs the project's own isolation tests if the config names them |
| `security-reviewer` | new (0.3.4) | Reads the design's threat model (*Data, security and compliance*) and the decision records, reviews the story's diff against them, and ranks findings CRITICAL / HIGH / MEDIUM / LOW. In `reviewers` by default, so it runs on every story |

Plugin agents ignore `hooks`, `permissionMode` and `mcpServers` in frontmatter; the worker must not rely on them.
`isolation: worktree` is supported.

## 4. Hooks

- `gate.sh`, `lane-guard.sh`: config path switched to the project; helper path switched to the plugin (done).
- `test-guards.sh`: runs against its own fixture config; check it still finds `backlog.py` under the plugin root.
- **Formatter (done in 0.2.0: `hooks/format.sh`, config `format`, `hooks/test-format.sh`):** the capstone's `ruff-format.sh` reformatted `.claude/scripts/backlog.py` with default settings.
  A generic `format.sh` runs only on paths listed in the config (`format: {"backend/": "uv run ruff format"}`),
  from that directory, so the project's formatter config applies.
- **WorktreeCreate (to try):** a hook can create the worktree itself and print its path. It could set the lane's
  sparse checkout before the worker starts, which removes the manual `!` step. The payload is not documented yet:
  prototype with `claude --debug`, keep the manual path as the fallback.

## 5. Project settings the plugin can't set

Plugin `settings.json` only takes `agent` and `subagentStatusLine`, so `setup` writes `worktree.baseRef: "head"` and
the helper's permission into the project's `.claude/settings.json` (shown as a diff first).

## 6. Evals

`evals/` with `claude plugin eval`: cases for `next` (picks the right step for each file state), `status` (flags a
missing DoD input), `story-start` (refuses a story with unmet deps), `kickoff` (asks one question at a time and
writes every DESIGN heading). Graders: `file_exists`, `regex`, `llm`.

## 6b. Added in 0.2.0

- `git-guardrails` is a sibling plugin in the same marketplace and a dependency (its hooks ship as plugin hooks;
  the key-file false positive on jq field names is fixed and tested).
- `kickoff` has a stress-test step (the `grilling` method, one question at a time) and a *Rules and
  enforcement* section; the new `guardrails` skill turns those rules into hooks, tests, reviewer checks, scoped
  rules and CLAUDE.md lines, recorded in the config's `guardrails` registry.

## 6c. Added in 0.3.0 (after the 2026-09-30 review)

- Review fixes: namespaced agent names; one `planning/<date>` branch that `next` merges; a conflict path in
  `story-finish`; config-change flag; safe undo; decision numbers in parallel; lane guard across every checkout;
  git guard parses subcommands and flags; secrets guard covers Grep, recursive grep, env printing; all guards fail
  closed without jq; `format.sh` uses the merged config and reports failures to Claude.
- `backlog.py note / set-deps / add` (checked writes); `worker-guard.sh`; (`subagent-stop.sh`, removed in 0.3.3:
  SubagentStop's additionalContext never reached the parent session in the trial) (review reminder via
  additionalContext); the `handover` skill; the `test-auditor` agent (mutation check of the DoD's tests).
- **WorktreeCreate: not built.** Its input fields and whether the hook must create the worktree itself are not
  documented (checked 2026-09-30). Prototype in a `claude --debug` session: log the hook's stdin, then decide.
  Until then the worker asks the user for the sparse-checkout command.

## 6d. 0.3.2–0.3.3 (after the end-to-end trial and the second review)

- Trial findings: `next` runs the planning steps back to back; one copy of the check commands (the config);
  `work-breakdown` edits with `backlog.py`; `next` defers to a project's own workflow copy (row 0).
- Second review: worker guard applies in any agent worktree (a detached checkout can't switch it off), covers
  pull, branch -f, update-ref, switch --create, checkout of commits, ignores quoted text, reads merge options,
  judges `git -C` by its target; `note` refuses newlines and fake outcomes, marks sub-story notes; `set-deps`
  refuses sub-stories; writes are atomic, keep CRLF, and re-check the touched story; the test-auditor runs a
  baseline, sets its scratch copy up like the worker's, and always cleans up; `subagent-stop.sh` removed.

## 6e. 0.3.4–0.3.5 (the trial's first stories)

- 0.3.4: the `security-reviewer` agent (section 3), run on every story by default.
- 0.3.5: two `story-finish` fixes. The worker guard applies to subagents only (the hook input's `agent_id`), so the
  orchestrator can merge from a shell left in a worktree; `story-finish` also runs git from the main checkout
  (`git -C <worktree>`, `uv run --directory <worktree>`). A fix that answers a security finding is re-checked by
  the `security-reviewer`, which confirms it is fixed and looks for regressions.
- Trial progress: S1 went through two fix rounds with a security review, then merged. C6 was split into C6a and
  C6b with `backlog.py`. Two stories ran in parallel (S2 and C6a), which the handover had listed as not yet covered live.

## 7. Order of work

1. `backlog.py` merge and its tests.
2. `status`, `story-start`, `story-finish` ports; `story-worker` and `dod-verifier` ports.
3. `kickoff` → `next` → `setup` tried end to end on a throwaway repo.
4. Formatter hook; WorktreeCreate prototype.
5. Evals; tag `story-workflow--v0.2.0`.
6. After the capstone: move the capstone onto the plugin (delete its copies, keep its project-specific skills,
   agents and rules).
