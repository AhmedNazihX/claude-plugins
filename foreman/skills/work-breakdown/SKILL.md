---
name: work-breakdown
description: Turns a project's design or spec documents into a repo layout (docs/LAYOUT.md) and an execution backlog (docs/BACKLOG.md) of atomic, self-contained stories — each with Deps, Type (agent/human/mixed), Context, Input, Output and a checkable Definition of Done — plus lanes, a computed critical path and parallel waves. Use at the start of a project or big feature, when the user asks to break work down, plan implementation, create a backlog, split a design into tasks/stories/tickets, decide a repo layout, or find what can run in parallel.
argument-hint: "[path to design doc(s)]"
---

# Work breakdown: design documents → backlog

The goal is a backlog in which **any story can be picked up with a fresh context**, by the user or by an agent,
with no loss of quality. Every story names exactly what to read, what to produce, and how to prove it's done.
The dependency graph, not intuition, decides the order and what runs in parallel.

Files in this skill:
- `references/story-format.md`: the story fields, plus good and bad examples. **Read it before drafting stories.**
- `references/backlog-template.md`: the skeleton for `docs/BACKLOG.md`.
- `references/layout-template.md`: the skeleton for `docs/LAYOUT.md`, the repo layout every Output path must fit.
- `${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py` (the plugin's helper): `check` (validates the backlog), `plan` (computes the critical path and waves), `status`, `show`, `deps`, `info`, `tick` and `graph`. It uses only the Python standard library.

If plan mode is on, build the backlog in the plan file. Its first story (`F0`) copies it to `docs/BACKLOG.md`
once the plan is approved.

## 1. Read everything, then extract the facts that shape the plan

Read every design document in full: `$ARGUMENTS`, else `docs/DESIGN.md` (written by the `kickoff` skill), else
the design and spec files in the repo. If there is no design at all, stop and offer `kickoff`. A design document can
be long: if a configured `docs` guard (`.claude/foreman.json`) would block a whole over-limit `.md` file, read it in
consecutive ranges (offset/limit) under the guard's limit, the way `backlog-reviewer` reads a long backlog, rather
than stopping at the first relevant passage. Then list:

- **Deliverables:** what exists at the end, as features, datasets, reports, deployments and documents. Include
  course or client requirements such as a README, a demo or a presentation.
- **Gates:** things the design says must happen *before* others. Look for them hard. Designs often hide them in
  prose: "labels are frozen before the build", "the schema is agreed before the clients", "the split is committed
  before the engine exists", "legal review before launch". Each gate becomes a story that others depend on, and
  if it can be checked mechanically, it becomes a hook or CI check later.
- **Contracts:** shared interfaces that many stories consume, such as result schemas, API types, database schemas
  and file formats. Build them early, as their own stories.
- **Shared resources:** things parallel work can collide on: a database schema or migrations, a lockfile,
  generated clients, a single dev server, a paid API budget. Tag every story that changes one (`Resource:`).
- **Human-only work:** judgement, approvals, manual data extraction, accounts, external tools, and legal or domain
  review. These stories are `human` or `mixed`, and they often sit on the critical path, so start them early.
- **Early experiments:** anything the design says to validate in the first week (model choice, library fit,
  cost). Put them early, with a decision record as their output.
- **Unknowns** that change the plan, such as a deadline, the team size, or whether parallel agents will be used.

**Questions:** ask only the ones whose answers change the plan, **one at a time**. The deadline is usually the
first one, because it sets how much of the scope fits. Anything with a sensible default, don't ask about: pick
the default and say so.

## 2. Shape the phases

A good default order, which you should adapt to the design:
1. **Foundations:** the scaffold, CI, contracts, database setup, API clients.
2. **Gates and data:** anything that must be frozen or committed before the build (test sets, labels, splits, fixtures).
3. **Core capability,** in the order the design's own flow implies.
4. **Evaluation and quality harness,** which can usually start early, against stubs.
5. **Product surfaces:** UI, API, integrations. These are views on the core.
6. **Wrap-up:** final runs, documentation, the demo, and a freshness check on anything time-sensitive.
7. **Stretch:** locked until the core is evaluated.

## 3. Fix the repo layout before drafting stories

Stories name exact Output paths, so decide where things live **first**. Otherwise each story invents its own
paths: scripts land in data folders, the same idea gets two package names, and relative paths are ambiguous.

1. Draft `docs/LAYOUT.md` from `references/layout-template.md`. For an existing codebase, start from the tree
   that's already there and follow its conventions. For a new project, derive the layout from the design's tech stack.
2. Include the tree down to key files; for each path, the story that creates it and any rule that applies
   (gitignored, generated, gated, or a folder a lane must never read); and the placement rules. Examples of placement
   rules: where scripts go (usually CLI subcommands inside the package, not loose files), where tests go, how data is
   kept apart from code, and how generated files are named.
3. **Separate data from code** wherever a lane or gate must fence data off, such as test answer keys, private
   datasets or raw downloads. A folder that holds only data can be excluded with a sparse checkout and guarded by a
   hook. A folder that mixes data and code can't.
4. Settle naming questions now, and ask the user if the answer changes the structure: for example, the package
   name, or where evaluation scripts live. Avoid names that clash, such as a code package called `docs/` next to the
   repo's `docs/` folder.
5. `CLAUDE.md` gets a short summary of the layout and a link to `docs/LAYOUT.md`. For the checks it points to the
   backlog's *Global rules* ("the checks are listed there"): never copy the commands into CLAUDE.md or a story,
   so there is one list to change.

## 4. Draft the stories

Follow `references/story-format.md`. The key rules:
- **Atomic:** one session, one branch, one reviewable diff. If the DoD needs "and" across two subsystems, split it.
  If a story would take more than about a day, split it. Group siblings that are truly parallel (`B5a–e`).
- **Self-contained:** *Context* names the exact design-doc sections to read, *Input* the exact files, *Output*
  the exact files or paths. Nothing outside these may be needed.
- **Paths fit the layout:** every Output path is written in full, from the repo root or the package root the
  layout names, and sits where `docs/LAYOUT.md` puts it. If a story needs a new folder, add it to the layout now,
  with the story's ID.
- **Checkable DoD:** commands, tests, counts, or "the user approved X". Never "works well" or "is clean".
- **Honest typing:** `agent` only if an agent can finish it alone. Anything that needs the user's judgement or approval is `mixed` or `human`.
- **Deps name story IDs.** Conditions that can't be expressed as a story (for example "run in week 9") are written as text. The script treats them as manual checks.
- **Deps cover the DoD's inputs.** If a DoD or Input needs another story's output (a case set, a file, a decision), that story is a dep, even when the code could be written without it. `check` warns when a DoD names an open story or a path another open story creates that isn't in the Deps: fix each warning or say why it's fine.
- **Tags:** `Solo` for stories that everything else waits on, such as the scaffold. `Resource: <name>` for shared-resource changes (`check` warns when a story mentions a migration or a lockfile without one). `Size: S/M/L`. `Lane: <name>`.

## 5. Write the backlog and let the script compute the structure

1. Write `docs/BACKLOG.md` from `references/backlog-template.md`. Fill in the Context section: why the backlog
   exists, the gates, and how to use it.
2. Run the checks, and fix the backlog until `check` reports OK:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py check
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py plan
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py graph
   ```
   If you're writing a plan file instead of `docs/BACKLOG.md`, add `--file <path>`.
   Once the file exists, change stories with the helper rather than `sed` or a script: `note <ID> "<text>"` adds a
   line to a story, `set-deps <ID> "<deps>"` replaces its Deps, `add --after <ID>` inserts a story (entry on
   stdin). Each refuses a write that would create a cycle or a duplicate ID. Rewrite a story's own fields with
   the file tools.
3. Paste the computed critical path (from `graph`) and waves (from `plan`) into the backlog.
   **Never draw them by hand.** A hand-drawn path drifts from the deps. Re-run the script after every change to the deps.
4. Sanity-check the result. If the critical path runs through a `human` story, flag it to the user: their time is the
   bottleneck. If one wave is very wide and the rest are thin, check for missing deps.

## 6. Independent review

Launch the `foreman:backlog-reviewer` agent on the draft, and give it the design-doc paths and `docs/LAYOUT.md`. It reads everything with fresh
eyes and reports stories that aren't atomic, DoDs that can't be checked, missing deps, hidden shared resources,
gates missing from the design, and coverage gaps. Fix what holds up, re-run `check` and `plan`, and list anything
you deliberately didn't change, with the reason. Then add `Reviewed: <date>` on its own line under the backlog's
title: the `next` skill uses it to know the review is done.

## 7. Hand over

Show the user a compact summary:
- The phase list with story counts.
- The critical path.
- The first two waves.
- The stories that need the user (`human` and `mixed`), with the earliest ones first.
- Anything uncertain.

Then the next step. If `next` started this skill, go back to `next` and continue (it runs `setup` without asking;
setup shows its settings diff). Otherwise:
- If the user wants parallel agents to run the stories, offer the **`setup`** skill. It writes the workflow
  config for this repo; `/foreman:status`, `story-start` and `story-finish` then run the stories.
- Otherwise, tell them to start with the first wave.
