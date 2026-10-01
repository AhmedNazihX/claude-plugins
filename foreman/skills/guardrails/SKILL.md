---
name: guardrails
description: Turns the project's rules into enforcement — reads the "Rules and enforcement" section of docs/DESIGN.md (and decision records), then for each rule sets up the strongest fitting mechanism (a built-in config-driven hook, a project hook with a test, a CI check or test, a reviewer agent, a path-scoped .claude/rules file, or a CLAUDE.md line) and records it in the guardrails registry in .claude/foreman.json. Use during setup, whenever a decision adds or changes a rule, or when the user asks to enforce, add or check a project rule.
argument-hint: "[rule or decision to add]"
---

# Guardrails: rules → enforcement

A rule the design states but nothing enforces is a wish. This skill gives every rule a mechanism, as strong as the
rule allows, and keeps a registry so none is forgotten.

## 1. Collect the rules

- `docs/DESIGN.md` › **Rules and enforcement** (written by `kickoff`), plus rules stated elsewhere in the design:
  Gates, Shared resources, Data, security and compliance, Stack. Read these sections yourself. Only when the
  document is long enough that a configured `docs` guard would block reading it whole, ask `foreman:doc-reader`
  to locate the sections first, then read each one's line range yourself — don't hand the rule extraction itself
  to `doc-reader`, or a rule it judges not worth quoting never reaches the registry.
- `docs/decisions/*.md`: a decision whose Consequences say "always", "never", "only", "before" or "must". Decision
  records are usually short enough to read in full, directly. Only for an unusually large decision log, ask
  `foreman:doc-reader` to locate the rule-bearing Consequences first, then read each one yourself.
- `CLAUDE.md` rules that have no mechanism yet, and `$ARGUMENTS` if the user names one. `CLAUDE.md` is usually
  short enough to read directly.
- The registry: `.claude/foreman.json` › `guardrails` (what exists already).

List each rule in one line with its source (design section or decision number).

## 2. Pick the strongest mechanism that fits

Go down this list and take the first that can express the rule. Several can apply: a hook plus a reviewer is
normal for anything that matters.

| Strength | Mechanism | Fits a rule that … | How |
| --- | --- | --- | --- |
| 1 | **Built-in hook** (plugin, config only) | says "nothing under X until Y is committed", "lane L never sees folder F", "format files under P with command C", "no `.md` file is loaded whole past N bytes" | add to `gates`, `lanes`/`stories`, `format`, or `docs` in the config |
| 2 | **Project hook** | is mechanical but not built in: "no live API calls in tests", "migrations only via `<tool> migration new`", "never edit generated file G" | write `.claude/hooks/<name>.sh` from `${CLAUDE_PLUGIN_ROOT}/templates/project-hook.sh`, add a case to `.claude/hooks/test-hooks.sh`, register it in `.claude/settings.json` (show the diff) |
| 3 | **Test or CI check** | can be checked on the code or data after the fact: an isolation test, a licence check, a schema check | add the test in the project's test tree (a story, if it's real work) and the CI job |
| 4 | **Reviewer agent** | needs judgement: "no benchmark wording in prompts", "every citation quotes the source" | a checklist item for `foreman:lane-auditor`, `foreman:diff-reviewer` or `foreman:security-reviewer`, or a project agent in `.claude/agents/<name>.md` added to `reviewers` or `lanes.<lane>.reviewers` |
| 5 | **Scoped rule** | is guidance for one area of the code: tooling, style, API conventions, security for the frontend | `.claude/rules/<area>.md` with `paths:` globs in its frontmatter, so it loads only when Claude reads matching files |
| 6 | **CLAUDE.md line** | applies everywhere and fits in one line | append to the project's global rules |

Keep scoped rules short (a screen at most), concrete, and pointing to their decision record. Don't restate what the
code or a linter already enforces. A hook blocks: be sure the rule has no legitimate exception before choosing one,
or give the exception a way through (an `allow` entry, a story exception).

## 3. Write, then prove it works

- For each hook: a test that it **blocks** the case the rule forbids and **passes** a legitimate near-miss (the
  near-miss catches false positives: the reason the secrets guard once blocked `jq '.key'`). Run the hook tests.
- For built-ins: `bash ${CLAUDE_PLUGIN_ROOT}/hooks/test-guards.sh`, then one live sample through the real config.
- For a test or CI check: run it once and show it passing, and failing on a planted violation.
- For scoped rules: check each `paths:` glob matches at least one existing or planned file (`docs/LAYOUT.md`).

## 4. Record it

Add or update one entry per rule in `.claude/foreman.json` › `guardrails`:

```json
{"rule": "Benchmark files are never read by corpus code", "source": "DESIGN.md › Data; decision 012",
 "enforced_by": ["lanes.Corpus", "foreman:lane-auditor", "backend/tests/test_isolation.py"]}
```

A rule with an empty `enforced_by` is allowed only if the user decided so; say so in a `note`.

## 5. Hand over

Show the table of rules → mechanisms, what was written, and the test results, then offer to commit them with the
config (on a story branch or the planning branch, not directly on the base branch). When a later decision changes a rule, run this skill again for that rule only: update the rule, its
mechanism and its test together.
