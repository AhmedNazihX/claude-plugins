---
name: kickoff
description: Turns an idea into a design a backlog can be built from. Reads whatever intent exists (an intention.md, project.md, README, brief or an existing codebase), interviews the user one question at a time for what is missing, decides the tech stack with them (recorded as decision records), and writes docs/DESIGN.md, the source of truth that work-breakdown turns into stories. Use at the very start of a project or a large feature, when there is no design document yet, or when the user says "start a project", "plan this", "what should we build", or describes an idea.
argument-hint: "[path to an intent or brief file]"
---

# Kickoff: intent → design

The output is **`docs/DESIGN.md`**: one document a fresh session can read to know what gets built, for whom, with
which stack, under which constraints, and how "done" is proven. Every later step reads it: `work-breakdown` turns
it into `docs/BACKLOG.md`, and every story's Context points into it. Write it so those steps have nothing to guess.

Rules for the whole skill:
- **One question at a time**, each with your recommended answer and the reason. Never a batch.
- **Read before you ask.** Never ask what a file, the repo or a quick look at the docs already answers.
- **The user decides**; you propose. Anything the user hasn't confirmed is marked *assumed* in the design.
- **Check library facts** against current docs (context7, or the library's own site) before recommending a stack.

## 1. Read what exists

- The file in `$ARGUMENTS`, else any of `intention.md`, `INTENT.md`, `project.md`, `PROJECT.md`, `brief*.md`,
  `README.md`, `docs/*.md` at the repo root.
- An existing codebase: languages, frameworks and versions (lockfiles, `pyproject.toml`, `package.json`, `go.mod`,
  `Cargo.toml`), the test and lint setup, CI (`.github/workflows/`), database and migrations, deploy files.
- Any existing `docs/DESIGN.md`: if it exists, this is a revision. Show what you would change and ask.

Summarise back in five lines what you understood, and what you still need.

## 2. Interview for the gaps

Work through these topics in order; skip any the sources already answer. Stop a topic as soon as the design has
what `work-breakdown` needs from it (see the headings in step 4).

1. **Problem and users:** who uses it, what they do today, what changes for them.
2. **Deliverables:** what exists at the end: features, datasets, reports, deployments, documents, a demo. Include
   course or client requirements. And the **non-goals**.
3. **Done and measured:** acceptance criteria per deliverable; any benchmark, target metric or review.
4. **Constraints:** deadline and time budget; team size; whether parallel agents will be used; money for paid
   APIs or hosting (and a per-run cost cap); where it must run.
5. **Data and risk:** what data comes in, personal or confidential data, licences, security, compliance or legal
   review, anything that must be isolated (an answer key, a test set, production credentials).
6. **Gates:** things that must happen before others ("the schema is agreed before the clients", "labels frozen
   before the build"). Ask directly; people rarely volunteer them.
   **Rules:** what the build must always or never do ("no live API calls in tests", "migrations only through the
   tool", "the test set is never visible to the code that is tested"). For each, ask how strict it is: a rule
   with no legitimate exception can become a blocking hook.
7. **Human-only work:** approvals, labelling, accounts, manual extraction, domain review. Who does it, and when.

## 3. Decide the stack

- **An existing codebase:** confirm its stack; ask only about additions (a database, a queue, a frontend).
- **A new project:** for each layer that matters (language and runtime, framework, data store, frontend, hosting,
  model provider if any), propose 2–3 options in a short table: fit to the constraints, maturity, cost, what the
  team knows, lock-in. Recommend one and say why. Check each recommended library's current version and API
  against its docs.
- Record every real choice with the **decision** skill (`docs/decisions/NNN-<slug>.md`): the options, what was
  compared, the choice. Obvious defaults need no record; say "default" in the design instead.
- Name what the first week must prove (model quality, a library's fit, cost per run): these become early
  experiment stories with a decision record as their output.

## 4. Write `docs/DESIGN.md`

Use these headings, in this order. `work-breakdown` extracts exactly these facts, so keep each one explicit:

```markdown
# <Project name>: design

- **Status:** draft | approved (<date>)
- **Sources:** <the intent files read, the interview date>

## Problem and users
## Deliverables            (each with its acceptance criteria)
## Non-goals
## Stack                   (layer → choice → decision record or "default")
## Architecture            (components, data flow, the contracts between them: schemas, APIs, file formats)
## Data, security and compliance
## Gates                   (X before Y, and how it can be checked mechanically, if it can)
## Shared resources        (database schema, lockfiles, generated clients, a paid API budget, a dev server)
## Human-only work         (who, what, roughly when)
## Early experiments       (what week one must prove, and the decision each one feeds)
## Rules and enforcement   (each rule the build must keep: source, and how it will be enforced — hook, test/CI,
                           reviewer, scoped rule or CLAUDE.md; the guardrails skill sets these up)
## Evaluation              (how each acceptance criterion is measured)
## Constraints             (deadline, team, budget, cost cap, parallel agents yes/no)
## Risks and open questions
```

Mark every unconfirmed statement *(assumed)*. Keep it as short as the project allows: a small tool may fit on two
pages.

## 5. Stress-test the draft

Before asking for approval, test the draft the way a sceptical reviewer would. The method comes from the
`grilling` skill (Matt Pocock's skills collection, MIT), adapted to one question at a time:

1. **Map the design tree.** Every decision in the draft (a stack choice, a gate, an acceptance criterion, a
   constraint) is a node; the decisions that only make sense once it is settled hang off it.
2. **Walk the frontier.** The frontier is every decision whose parents are settled. Pick the one whose answer
   would change the most of the design, and ask it: **one question**, with your recommended answer and the reason.
   Good questions attack: "what happens when …", "how will you know …", "what if this is 10× bigger, or never
   arrives", "who approves this, and when", "what would make you drop this deliverable".
3. **Update the draft** after each answer: fix the section, drop what the answer made moot, add what it opened,
   and record any real choice as a decision.
4. **Stop** when the frontier holds only questions whose answer wouldn't change a deliverable, a gate, the stack or
   the order of work, or when the user says it's enough. List what you didn't ask under *Risks and open questions*.

## 6. Approve, then hand over

Show the design section by section, not all at once, and fix what the user corrects. When they approve, set
`Status: approved (<date>)`, commit it with the decision records on the planning branch (`planning/<yyyy-mm-dd>`, see `next`),
and hand over:

- **Next:** `work-breakdown` (`/story-workflow:work-breakdown docs/DESIGN.md`) builds `docs/BACKLOG.md` and
  `docs/LAYOUT.md`; then the `story-workflow:backlog-reviewer` agent critiques it; then `setup` installs the workflow config.
- If `next` started this skill, go back to `next` and continue without asking; otherwise offer
  `/story-workflow:next`, which picks the right step from the files that exist.
