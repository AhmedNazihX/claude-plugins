# Prompt audit: what accio tells its models

Date: 2026-10-20. Proposals only: no audited file was changed.

## The question

Do the words accio hands to models (agent and skill files, briefs, brew's prompts, hook messages) make each model do
the right thing, cheaply? Where do they not, and what should change?

## Short answer: the top 10 changes, by impact

1. **Give the fix-round builder its story's limits.** `bin/accio_lib/templates/fix-brief.md:1-16` has no Definition
   of Done (DoD), no list of files it may change and no checks. `agents/house-elf.md:23` says "Read only your
   brief". A fix that touches a file outside the story fails prefect's boundary check and blocks the story.
2. **Stop telling the builder to run a rebase it may not run.** `bin/accio_lib/brief.py:125-143` writes "Run
   `git -C … rebase --onto …`" into the brief. curfew allows `git rebase` only with `--continue`, `--abort` or
   `--skip` (`bin/accio_lib/bashpolicy.py:317-318`). DESIGN § 12.3 (`docs/DESIGN.md:636`) promises house-elf resolves
   the conflict. It can't.
3. **Narrow wand's trigger.** `skills/wand/SKILL.md:4` fires on "I want to build …" and "build a tool/app/service
   that …" "in a git repo", and its step 1 (`:17-19`) creates `.accio/` and installs git hooks. A plain coding
   request in any repo can set accio up without being asked.
4. **Make "/accio is driving" a fact, not a guess.** Four skills change behaviour "when the accio conductor skill was
   loaded earlier in this chat and has not finished" (`skills/owl/SKILL.md:77-80`, `prophecy:85-97`, `sort:63-65`,
   `wand:78-80`). In that mode owl accepts every READY story without asking. A user who typed `/accio` earlier and
   then types `/accio:owl` by hand can lose the review. Pass an argument from the conductor instead.
5. **Tell prefect how to get the ledger key at step 7.** `agents/prefect.md:22-24` says `accio-ledger record <ID>
   <key> pass`, but step 7 is a fresh agent and the key was printed in step 3 by a different one. Neither the body
   nor brew's prompt (`workflows/brew.js:162-166`) says to compute it again.
6. **Stop any portkey step from releasing the run lock.** `agents/portkey.md:36`: "At the end of a build, whatever
   happened, `accio-board unlock` releases the lock." Every portkey call (prepare, review package, fix brief) reads
   this. One that fails in the middle of a build may unlock while other stories still run.
7. **Tell the builder which commands it may run.** `agents/house-elf.md:16-20` only says a denied command "comes back
   with the reason". curfew denies `$(…)` (`bashpolicy.py:121-122`), which is how Claude Code usually writes a
   commit message. The brief also lists all 12 accio scripts (`templates/brief.md:29-30`), though it may run 2.
   Each wrong guess costs a turn out of 150.
8. **Trim the descriptions to the 2k budget.** `claude plugin details accio` now gives ~2,147 tokens always on
   (target ~2k, DESIGN § 8.5, `docs/DESIGN.md:513`). README says 1,900 (`README.md:92`). Skill descriptions explain
   the mechanism ("the score sets each track…") instead of the trigger. In this session, `accio:map` and
   `accio:vow` showed with no description at all: Claude Code drops descriptions when the listing overflows.
9. **Say "not for general use" in the build agents' descriptions.** professor, auror, examiner and house-elf are
   listed to the main chat as "reviews one story's diff for correctness bugs…". The main chat may send "review my
   code" to `accio:professor`, which expects a review package that doesn't exist.
10. **Plan for the skill's tool grant ending at the user's reply.** Claude Code docs: an `allowed-tools` grant
    "clears when you send your next message". owl, prophecy, wand and sort ask the user a question, then run more
    scripts. After the answer, each script asks for permission, and the skills' "so your permissions match it"
    (`skills/owl/SKILL.md:12`) no longer holds. Not tested here; evals run with `--allow-tools`.

## Description budget

Words are `description` plus `when_to_use`. Tokens are from `claude plugin details accio` (2026-10-20, rounded).

| Component | Words | Chars | Tokens | Verdict |
|---|---|---|---|---|
| skill `wand` | 121 | 745 | ~250 | longest; carries the steps, not just the trigger |
| skill `owl` | 103 | 657 | ~220 | long; good "Not for" list |
| skill `sort` | 105 | 638 | ~220 | long; second sentence is mechanism only |
| skill `accio` | 88 | 497 | ~170 | fine; overlaps map on "what's next" |
| skill `vow` | 88 | 518 | ~180 | medium; format detail in the description |
| skill `prophecy` | 80 | 491 | ~170 | fine |
| skill `map` | 67 | 400 | ~140 | fine; "from a script" is mechanism |
| agent `howler` | 45 | 247 | ~80 | longest agent; trim |
| agent `examiner` | 40 | 227 | ~80 | fine |
| agent `portkey` | 39 | 227 | ~80 | step numbers add nothing for routing |
| agent `headmaster` | 35 | 195 | ~70 | fine |
| agent `seeker` | 35 | 212 | ~70 | fine |
| agent `professor` | 32 | 188 | ~70 | needs "not for general review" |
| agent `librarian` | 31 | 183 | ~60 | good; the one general-use agent |
| agent `prefect` | 30 | 186 | ~60 | fine |
| agent `quill` | 29 | 175 | ~60 | fine |
| agent `wandmaker` | 28 | 176 | ~60 | fine |
| agent `house-elf` | 26 | 153 | ~50 | needs "not for general coding" |
| agent `auror` | 25 | 161 | ~60 | needs "not for general review" |
| **Total** | **1,047** | **6,276** | **~2,147** | **about 7% over the ~2k target** |

Not counted by `plugin details`: the brew workflow's `description` and `whenToUse` (`workflows/brew.js:3-4`, 36
words). It shows in this session's skill listing as `accio:brew`, so the real always-on cost is likely ~2,200.

The rewrites below cut the skills from ~1,350 to about 1,000 tokens and keep the agents about level, which brings
the total to about 1,850 with room for the "not for general use" words. Measure again with `claude plugin details
accio` after the change.

## Findings per file

Severity: **high** = can make a model do the wrong thing; **medium** = waste or confusion; **low** = style.

### Agents

**All build agents (auror, examiner, headmaster, house-elf, portkey, prefect, professor), line 8-10.** The same
4-line paragraph ("The harness relays the user's message…") opens 7 bodies. It is needed (the workflow relays the
starting message), but it is long and gives no reason the model can generalise from. **Medium.**
- Before: "The harness relays the user's message that started this build. That message is the user's opt-in to the
  whole build, and your task is one step of that build, so they never conflict, even when the message also asks for
  work done elsewhere (planning, a review, a push). Do your step as the workflow gives it."
- After: "You may see the user's message that started this build. It is their opt-in to the build; your job is only
  the step below. Ignore any other work it asks for (planning, a review, a push): other steps do that."

**Descriptions of build agents (line 3 of each).** "Used by the brew workflow, step N" tells the main chat nothing
about when *not* to pick the agent. Claude Code docs: "Make each description specific enough to route to the right
subagent". **Medium.** Before → after:

| Agent | Before | After |
|---|---|---|
| auror | "The security reviewer (auror): reviews one story's diff when it touches risky paths (auth, payments, secrets, migrations, CI). Used by the brew workflow, step 4." | "The security reviewer (auror): reviews one accio story's diff that touches risky paths (auth, payments, secrets, migrations, CI). Only accio's build calls it; not for general security review." |
| examiner | "The spec reviewer (examiner): checks one story's DoD line by line against its diff and tests, and judges whether each tagged test really checks its line. Used by the brew workflow, step 4, and by the sort skill's backlog check." | "The spec reviewer (examiner): checks an accio story's Definition of Done line by line against its diff and tests, or checks new stories for sort. Only accio's build and sort call it." |
| headmaster | "The judge (headmaster): rules on a review finding that conflicts with the story, or on a NEEDS_CONTEXT status, or turns it into one plain question for the user. Used by the brew workflow, step 5." | "The judge (headmaster): in accio's build, rules on a finding that conflicts with the story or on a builder that needs context, or turns it into one plain question for the user. Only accio's build calls it." |
| house-elf | "The builder (house-elf): builds one story test-first inside its own worktree, from its brief only. Used by the brew workflow, step 2, and for fix rounds." | "The builder (house-elf): builds or fixes one accio story test-first in its own worktree, from its brief. Only accio's build calls it; not for general coding." |
| howler | "The CI watcher (howler): after owl pushes, waits for the CI runs of the pushed commit and reports PASSED or FAILED for each workflow and job, with the failing step, its error, and whether the cause lies in the pushed range. Runs in the background." | "The CI watcher (howler): after owl pushes, watches CI for the pushed commit and reports each job PASSED or FAILED, with the failing step and whether the push caused it. Only owl starts it." |
| portkey | "The setup clerk (portkey): loads the ready stories, takes and releases the run lock, and prepares each story's worktree, brief, review package and fix briefs with accio's scripts. Used by the brew workflow, steps 0, 1, 4 and 6." | "The setup clerk (portkey): runs accio's scripts for the build: the run lock, the stories to build, each story's worktree, brief, review package and fix brief. Only accio's build calls it." |
| prefect | "The checker (prefect): runs the story's checks and accio's scripted checks (boundary, DoD tags, main snapshot, remote), and records the outcome. Used by the brew workflow, steps 3 and 7." | "The checker (prefect): runs a story's checks and accio's scripted checks, and records the outcome on the board. Only accio's build calls it." |
| professor | "The code reviewer (professor): reviews one story's diff for correctness bugs, error handling and code that will be hard to change. Used by the brew workflow, step 4, after the spec review." | "The code reviewer (professor): reviews one accio story's diff for bugs, silent errors and code that will be hard to change. Only accio's build calls it; not for general code review." |
| quill | "The story writer (quill): turns the design into story files in .accio/stories/, splits a story the score flags, and fixes the backlog check's findings. Used by the sort skill." | "The story writer (quill): writes, splits and fixes accio's story files from the design. Only the sort skill calls it." |
| seeker | "The researcher (seeker): checks live documentation and the existing code for the facts a design depends on, each with its source, and treats anything the docs don't mention as unavailable. Used by the wand skill." | "The researcher (seeker): checks the facts a design rests on against live docs and the code, each with its source; what the docs don't mention counts as unavailable. Only the wand skill calls it." |
| wandmaker | "The architect (wandmaker): proposes 2–3 designs for what the user wants, each with its trade-offs, what breaks first, and four depth questions answered. Used by the wand skill." | "The architect (wandmaker): proposes 2–3 designs, each with trade-offs, costs and what breaks first. Only the wand skill calls it." |
| librarian | (keep as is) | It is the one agent meant for general use, and it already says when to use it. |

**`agents/house-elf.md`**
- `:23` "Read only your brief." and `templates/brief.md:3` "Read only this brief; everything you need is here." The
  builder must read code to change it. A literal model may skip the code it should reuse. **Medium.** After: "Take
  your task only from your brief: don't read `.accio/` (the design, other stories). Read whatever code you need."
- `:16-20` The guard's rules are only discovered by being denied. **Medium (top 10, #7).** Add after line 20: "What
  you may run: the brief's checks; read-only tools (`ls`, `cat`, `grep`, `find` …); `mkdir`, `cp`, `mv`, `rm` inside
  the worktree; `git add`, `commit`, `status`, `diff`, `log`, `show`, `restore`; and `accio-board refresh`. The guard
  can't read `$(…)`, backticks or heredocs, so it denies them: commit with `git commit -m '<message>'`. Installing
  packages needs the user's leave at owl: return BLOCKED with `needs override: <command>`."
- `:22-29` No fix-round section, though the same agent does fix rounds (`workflows/brew.js:210-215`). Steps 2 and 4
  talk about DoD lines and "the brief's checks", which the fix brief doesn't have. **High (with #1).** Add: "**In a
  fix round** your brief is a fix brief: fix only its findings, keep to the files and checks in the story's brief it
  names, and commit each fix."
- `:14` vs `:17` The claim must run "on its own", yet "Every Bash command starts with `cd <worktree> &&`". The order
  makes it work, but say "Every later Bash command". **Low.**

**`agents/prefect.md`**
- `:22-24` Step 7 needs `<key>`; a fresh agent has none. **High (#5).** After: "**Step 7, outcome.** First get the
  key as in step 3 (`accio-ledger key .accio/stories/<ID>.md --worktree <worktree> --panel <panel>`). When the
  workflow says READY: `accio-board move <ID> review`, then `accio-ledger record <ID> <key> pass`. …"
- `:28-30` One reply shape for two steps. Step 7's prompt asks for `{"done": true}` (`brew.js:165`). The schema saves
  it, but the body contradicts the prompt. **Low.** After: "Reply with JSON only. Step 3: `{…}` as below. Step 7:
  `{"done": true}`, or `{"error": …}`."
- No `maxTurns` (frontmatter). A Haiku agent that loops is stopped only by the 20-minute stall. **Low.** Add
  `maxTurns: 20`. Same for portkey and librarian.

**`agents/portkey.md`**
- `:36` The unlock line applies to every call. **High (#6).** After: "**Finish (only when the workflow asks you to
  release the lock):** `accio-board unlock`. Never unlock in another step, even after a failure: the workflow
  releases the lock itself."
- `:16` "Pass on any problem it prints." "Pass on" can mean "report" or "skip". The load schema
  (`brew.js:52-59`) has no field for it, so the warning is lost. **Medium.** Either add `"hooks": "<what verify
  printed>"` to the step-0 reply and the schema, or say "Ignore what it prints; owl checks the hooks again."
- `:19` "DESIGN § 12.6" points to accio's own design doc, which is not in the user's repo (or is a different file
  there). **Low.** Replace with the meaning: "(`check` when the branch already has commits, else `prepare`)".

**`agents/headmaster.md`**
- `:25-27` and frontmatter `tools: … Bash`. The body names two commands it "may run" but never asks it to run them.
  An unused tool invites guessing. DESIGN § 4.2 (`docs/DESIGN.md:275`) lists `key/check/record`; curfew allows
  `key/check` (`bin/accio_lib/policy.py:37`); the body forbids `record`. **Medium.** Drop Bash and the ledger
  sentence, or say why it would use them ("run `accio-ledger check` to see whether this exact work already passed").
  Fix DESIGN § 4.2 either way.
- `:18-19` "citing the DoD line or the design section", but brew's prompt names no design path (`brew.js:149`).
  **Low.** Add `.accio/design.md` to the prompt.

**Reviewers: `agents/auror.md`, `examiner.md`, `professor.md`**
- The fix-round paragraph, the ruling rule, the confidence rule and the write-path rule are repeated in all three
  (`auror:19-31`, `examiner:37-48`, `professor:25-36`), again in brew's prompt (`brew.js:258-259`), in the review
  package's scope (`bin/accio_lib/review.py:140-143`) and in the findings template (`references/findings-template.md:3`).
  Six copies drift. **Medium.** Keep them in the review package (it is written per round, so it can say "fix round"
  or not) and in the findings template. Each body keeps only what to look for and its reply line.
- `examiner.md:8-12` In sort's backlog check the build paragraph and "You review one story against its Definition of
  Done … The review package gives …" are wrong: there is no build, no package and many stories. The backlog
  paragraph (`:27-35`) then has to undo three rules. **Medium.** Open with: "You check stories in one of two modes.
  The prompt says which." and give each mode its own short section.
- `examiner.md:24-25` and `brew.js:255-257` say the Quick-track rule twice. **Low.** Keep it in the prompt only.

**`agents/quill.md`**
- Frontmatter `tools: Read, Glob, Grep, Write`. Split and Fix change existing story files, so quill must rewrite each
  whole file with Write. That risks losing `## Review notes` or a `dropped:` key. **Medium.** Add `Edit` (curfew
  already limits Write/Edit to `stories/S-*.md`).
- `:61` A 190-character line with the score's point rules. **Low.** Break into a short list.

**`agents/howler.md`**
- `:22` "retry an empty result a few times". **Low.** Say "up to 3 times".
- `:26-27`, `:41-46` Switches to third person ("howler waits", "the report states"). **Low.** Use "you" throughout.

**`agents/wandmaker.md`**
- `:22` "(decision 011)" means accio's own decision 011. In the user's repo, `.accio/decisions/011-*.md` is one of
  *their* decisions. **Low.** Remove the reference. Same in `references/checklists/README.md:1`.

**`agents/seeker.md`, `agents/librarian.md`**: clear, short, with reasons. No change needed.

### Skills

**Descriptions (before → after).** Put the trigger first, move the mechanism into the body, and add "Not for" where
two skills overlap. Skill authoring best practices: "include both what the Skill does and specific triggers". The
docs cap `description` + `when_to_use` at 1,536 characters each; all are well under. **Medium (#8).**

| Skill | Before (description / when_to_use) | After |
|---|---|---|
| accio | "The conductor (accio): one command that carries the work from wherever the board stands to a pushed, CI-checked result. It reads accio's next step, runs that step's skill in this chat (design, stories, plan, build, review) and repeats, stopping only at real decisions." / "When the user runs /accio, or says "continue", "carry on", "what's next, do it", or "take it from here" in a repo with an .accio/ folder or a design to start from. Not for running one named step by hand (the step skills do that)." | "The conductor (accio): runs accio's next step (design, stories, plan, build, review) in this chat and repeats, stopping only for real decisions." / "When the user types /accio, or says "continue", "carry on" or "take it from here" in a repo with .accio/. Not for one named step (its own skill) or a plain "what's next?" (map)." |
| map | "Board (map): shows accio's board (the stories in each column, from a script, without changing anything), what the last build left stuck, and the next step." / "When the user asks "show the board", "where are we", … or runs /accio:map, in a repo with an .accio/ folder. Not for planning (prophecy), building or reviewing (owl)." | "Board (map): shows accio's board, what the last build left stuck, and the next step. Changes nothing." / "When the user asks "show the board", "where are we", "what's next?", "is the build still running", or types /accio:map, in a repo with .accio/. Not for doing the next step (accio)." |
| owl | "Review (owl): reviews accio's last build with the user. Shows each finished story and each blocked question from one short summary, takes one batch answer (…), merges what was accepted, and records the iteration." / (58 words) | "Review (owl): reviews accio's last build with the user: the finished stories and blocked questions, one batch answer (accept, reject, drop, answers, push), then merges what was accepted." / "When the user says "review the build", "the build finished", "accept/reject/drop S-012", "merge and push the build", or types /accio:owl, in a repo with .accio/. Not for reviewing a code diff or PR, or merging a branch by hand." |
| prophecy | "Plan (prophecy): plans the next accio iteration with the user. Proposes up to 8 buildable stories from .accio/'s backlog, settles their open questions one at a time, and on "go" marks them Ready and commits the plan." / (43 words) | "Plan (prophecy): plans the next accio iteration: up to 8 stories ready to build, their open questions settled one at a time, then on "go" marks them Ready and commits the plan." / "When the user asks "what should we build next", "plan the next iteration/sprint", or types /accio:prophecy, in a repo with .accio/. Not for writing stories (sort) or building (brew)." |
| sort | "Stories (sort): turns accio's design into a backlog of small, testable stories. The quill agent writes the story files, the score sets each track and flags stories to split, a backlog check finds weak stories and quill fixes them, then the stories are committed and the user sees a short summary." / (54 words) | "Stories (sort): turns accio's design (.accio/design.md) into small, testable story files, checks them and commits them." / "When the user asks to "turn the design into stories", "write the backlog", "break the design down", "add stories for the new part of the design", or types /accio:sort. Not for designing (wand) or planning an iteration (prophecy)." |
| vow | "Decision (vow): records a decision the user made as a numbered decision record in .accio/decisions/ (what was decided, the options with their pros, cons and costs, the choice and why) and commits it." / (55 words) | "Decision (vow): writes a decision the user already made as a numbered record in .accio/decisions/ (options, pros, cons, costs, the choice and why) and commits it." / "When the user says "record this decision", "log the decision" or "write an ADR", or types /accio:vow, in a repo with .accio/. Not while wand runs: wand records its own decisions." |
| wand | "Design (wand): designs what to build with the user. Sets accio up, interviews the user one question at a time (every requirement needs an owner; the outcome question is always settled), has seeker check the facts and wandmaker propose 2–3 options, settles the choice, records each decision, then writes and commits .accio/design.md." / "When the user wants to design or start a new project or feature, "plan the architecture", "help me design X", "I want to build …", "build a tool/app/service that …", "write the design", "add a design note for …", or runs /accio:wand, in a git repo. …" | "Design (wand): designs a project or feature with the user, one question at a time, checks the facts, offers 2–3 options, records the decisions and writes .accio/design.md." / "When the user types /accio:wand, or asks accio to "design", "plan the architecture", "write the design" or "add a design note for …". In a repo without .accio/, only when the user clearly asks for accio, since it sets accio up there. Not for writing code now, stories (sort) or planning (prophecy)." |

**`skills/wand/SKILL.md`**
- `:4`, `:17-19` The trigger and the setup together. **High (#3).** Besides the description above, add to step 1:
  "If there is no `.accio/` folder and the user didn't type `/accio:wand` or `/accio`, ask once before setting accio
  up: it adds `.accio/` and git hooks to their repo." That one question is a real decision (DESIGN § 7.3: safety).
- `:32` "`intent.md` at the repo root" is accio's own convention and is never explained. **Low.** Say "a file the user
  wrote about what they want (often `intent.md`)".
- `:60-61` Step 6 reads another skill's SKILL.md (`skills/vow/SKILL.md` steps 3–5). That is a second level of
  reference; the best practices say "Keep references one level deep from SKILL.md". **Low.** Copy the three commands
  into wand's step 6 (they are three lines), keep the format file reference.

**`skills/owl/SKILL.md`, `prophecy/SKILL.md`, `sort/SKILL.md`, `wand/SKILL.md`: the "driving" clause**
- **High (#4).** The model must judge whether the conductor "has not finished". After `wait` (a build running) it
  hasn't, so a hand-typed `/accio:owl` would take the auto-accept path (`owl:79`: "accept all"). Proposal: in
  `skills/accio/SKILL.md:20-21`, load each step skill with the argument `driven` (Skill tool `args`). Claude Code
  appends it as `ARGUMENTS: driven` when the skill has no placeholder (Skills docs, "Pass arguments to skills"). Each
  step skill then says, in one line: "If ARGUMENTS says `driven`, /accio is driving: …". A hand-typed command has no
  such argument, so it keeps every question.
- The same clause is written four times, worded four ways. **Medium.** With the argument, each becomes one line.

**`skills/prophecy/SKILL.md`**
- 97 lines; DESIGN § 4.1 (`docs/DESIGN.md:245`) says "under about 80 lines". **Low.** Move "When /accio drives:
  fewer stops" (`:89-97`) into `references/question-format.md` or the shared file below.
- `:16-18` and `skills/map/SKILL.md:23-25` repeat the workflows-off test word for word. **Low.** Fine to keep (two
  copies, short), or move it into `accio-board plan`/`next` output so no model has to look at its own tool list.

**`skills/accio/SKILL.md`**
- `:10-12` "Run the script … with no variables and no `&&` or `;` chains" gives no reason; owl gives one ("so your
  permissions match it"). **Low.** Add "so the skill's permission rule matches it".
- `:36` "Never say to the user "type" and a step's slash command". Each step skill's ending says "type
  /accio:prophecy" unless the driving clause fires. With #4 fixed this is safe; today it depends on that guess.
  **Low.**

**`skills/owl/SKILL.md`, `prophecy`, `wand`, `sort`: permissions after a question**
- **Medium (#10).** Claude Code docs: the `allowed-tools` grant "clears when you send your next message". Each of
  these skills asks, waits, then runs scripts (`owl` step 3-5, `prophecy` step 6, `wand` step 6, `sort` step 4-5).
  Proposal: test one run without `--allow-tools`. If the prompts appear, either document the allow rules the user
  should add once (DESIGN § 12.1 says accio writes none) or have the skill say "your answer may bring a permission
  prompt for accio's script; allow it". Don't claim the permissions match after a reply.

**`skills/map/SKILL.md`, `skills/vow/SKILL.md`, `skills/sort/SKILL.md`**: clear steps, each failure path named,
reply format given. Only the description changes above.

**Skill references**
- `skills/prophecy/references/question-format.md:3-11` and `skills/wand/references/interview.md:3-9` are the same
  four-part question format (it is also the user's own `decisions.md`). **Low.** One shared
  `references/asking.md`, linked from both skills, keeps them from drifting.
- `skills/owl/references/batch-answer.md`, `skills/vow/references/decision-format.md`,
  `skills/wand/references/design-template.md`: good. Each has a concrete example and says what the script refuses.

### Templates (handed to agents)

**`bin/accio_lib/templates/fix-brief.md`**
- `:1-16` **High (#1).** No DoD, no files, no checks. Before: the "Where you work" list ends at the report line.
  After, add:
  ```
  ## The story's limits
  - Its brief, with the Definition of Done: `$brief_path`
  - Files you may change (plus their tests):
  $files
  - Checks to run before you reply:
  $checks
  ```
  `render_fix` (`bin/accio_lib/brief.py:216-217`) would pass the same `files` and `checks` values as
  `render_brief`.

**`bin/accio_lib/templates/brief.md`**
- `:3` "Read only this brief" (see house-elf above). **Medium.**
- `:12` "Start every Bash command that touches files with `cd …`". curfew applies it to *every* command after the
  claim (`bin/accio_lib/bashpolicy.py:320-334`). The house-elf body has it right; the brief and DESIGN § 4.4
  (`docs/DESIGN.md:293`) and § 3.4 (`:147`) say "that touches files". **Medium.** After: "Start every Bash command
  after the claim with `cd $worktree_q &&`, or use `git -C $worktree_q`."
- `:29-30` "Scripts (absolute paths)" lists all `accio-*` scripts. house-elf may run only `accio-claim` and `accio-board
  refresh` (`policy.py:192-196`). **Medium.** List those two only.

**`bin/accio_lib/brief.py:125-143` (the "Before you start" notes in the brief)**
- **High (#2).** The notes say "run `git -C <wt> rebase --onto <onto> <old>`" or "`… rebase <onto>`". curfew denies
  both for house-elf. Two ways out: (a) let curfew allow exactly the rebase command the brief names (it is known
  when the brief is written), or (b) have portkey's `accio-brief` leave the rebase in progress for house-elf to
  `--continue`, which curfew allows. Until then DESIGN § 12.3 step 2 is not true.

**`bin/accio_lib/templates/review-package.md`**
- `:24-25` "## Method checklists / Checklists: …" says it twice. **Low.** "## Method checklists to apply" then the
  list.
- This package is the right single home for the fix-round, ruling and write-path rules (see Reviewers above).

**`references/findings-template.md`**: clear, with severity meanings and an example. Keep the confidence rule here
only.

### brew.js prompts

- `workflows/brew.js:162-166` (step 7): no key. **High (#5).** Add: "Get the key as in your step 3 first."
- `workflows/brew.js:210-215` (fix round): repeats the fix brief's conflict rule (`fix-brief.md:3-5`). **Low.** Keep
  one copy, in the brief.
- `workflows/brew.js:144-152` (judge): add the design path, `.accio/design.md`. **Low.**
- `workflows/brew.js:254-262` (review): the Quick-track and fix-round sentences repeat the reviewer bodies and the
  package. **Medium** (drift). Keep them in the package only.
- `workflows/brew.js:3-4` (meta): fine, and short. It is not counted by `plugin details`; count it by hand.
- `workflows/brew.js:39-41` (`SILENT`) and `checkQuestion` (`:220-231`): good plain questions for the user, each with
  the cause.

### Hooks

- Block messages (`hooks/protego.py:54-71`, `fidelius.py:156-159`, `curfew.py:122-123`,
  `bin/accio_lib/bashpolicy.py`): each names the guard's role and says "Instead: …". This matches the "helpful error
  messages" advice in "Writing effective tools for agents". No change.
- `hooks/doc_size.py:52-55` tells every caller to "Ask the accio:librarian agent". Build agents have no Agent tool,
  so for them only the second half ("read it by section") works. **Low.** Fine as is: the fallback is in the same
  message.
- `hooks/session_start.py:71-74` The next-step line comes from `nextstep.py` and names the single commands
  (`/accio:prophecy` …), never `/accio`. DESIGN § 7.3 says `/accio` is the one typed command per iteration. **Low.**
  Add "or type /accio to carry on".
- No output style ships (DESIGN § 4.7 lists it for v1.1). Nothing to audit.

## Cross-file issues

**Contradictions**
- Fix rounds: house-elf body assumes DoD and checks (`agents/house-elf.md:24-28`); the fix brief has neither
  (`templates/fix-brief.md`).
- Rebase: DESIGN § 12.3 (`docs/DESIGN.md:636`) and the brief notes (`brief.py:125-143`) vs curfew
  (`bashpolicy.py:317-318`).
- `cd` rule: house-elf body ("every") vs brief, DESIGN § 3.4 and § 4.4 ("that touches files"); the code says every.
- headmaster's ledger commands: DESIGN § 4.2 (`key/check/record`) vs policy (`key/check`) vs body (none needed).
- "Two checkpoints": README (`README.md:3-4`), `plugin.json:4` and DESIGN P3 (`docs/DESIGN.md:62`) vs DESIGN § 7.3
  and the README quick start (`README.md:12-15`): `/accio` stops at the design interview, real questions, failed
  stories, push. The README opening and the plugin description should say "stops only for your decisions".
- Description cost: README `:92` and `evals/README.md:38` say ~1,900; measured ~2,147.
- prefect's reply: body (`agents/prefect.md:28-30`) vs step-7 prompt (`brew.js:165`).

**Duplicated rules that should live in one place**
- Reviewer fix-round, ruling, confidence and write-path rules: six copies (see Reviewers). Home: the review package
  and the findings template.
- The build-opt-in paragraph: seven agents. Shorten it (see Agents); it has to stay in each body, since agents can't
  include a shared file.
- The "driving" clause: four skills. Home: one argument check per skill (#4).
- The four-part question format: prophecy, wand (and the user's rules). Home: one shared reference.
- The workflows-off check: map and prophecy. Small; acceptable.

**Overlaps that can pick the wrong component**
- `accio` vs `map` on "what's next": accio's trigger "what's next, do it" is one comma from map's "what's next". A
  plain question could start work. Fixed by the rewrites (map owns "what's next?", accio says so).
- `wand` vs plain coding: "I want to build …" in any git repo (#3).
- Build agents vs general reviewers: `accio:professor`/`auror`/`examiner` vs the session's other code reviewers (#9).
- `owl` vs `accio` on "the build finished": both are right (accio, when driving, goes to owl), so no change.

**Over-emphasis.** No ALL-CAPS words (MUST, NEVER, CRITICAL) in any audited file. "never" appears 0–6 times per
file, and most come with a reason (for example prefect's "Never run `accio-check <ID> snapshot`: portkey takes the
snapshot before the story"). This already follows the current guidance. Keep it that way when adding the lines
above.

**Plain English.** Mostly good. Terms explained the first time: track, stacked on, spike, design note. Not
explained to the model or user: EARS (quill, examiner), "panel" (prefect, brew), "ledger" (prefect, headmaster),
`intent.md` (wand). Several lines run past 150 characters (`quill.md:61`, `sort/SKILL.md:35`, `wand/SKILL.md:45`,
`howler.md:26`). **Low.**

## Standards used

- Claude Code docs, "Extend Claude with skills": frontmatter fields incl. `when_to_use`; "the combined
  `description` and `when_to_use` text is truncated at 1,536 characters"; "Keep `SKILL.md` under 500 lines"; the
  listing budget "scales at 1% of the model's context window" and "drops descriptions starting with the skills you
  invoke least"; an `allowed-tools` grant "clears when you send your next message"; `$ARGUMENTS` and
  `${CLAUDE_PLUGIN_ROOT}` substitution. https://code.claude.com/docs/en/skills
- Claude Code docs, "Create custom subagents": "Claude uses each subagent's description to decide when to
  delegate"; "Write descriptions that single out one subagent"; "Limit tool access"; subagents don't see the
  parent's conversation; plugin agents ignore `hooks`, `mcpServers`, `permissionMode`; `maxTurns`, `background`.
  https://code.claude.com/docs/en/sub-agents
- Claude Platform docs, "Skill authoring best practices": description says what and when, third person, key terms;
  "Concise is key"; degrees of freedom; references one level deep; consistent terminology; templates and examples
  for output. https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Claude Platform docs, "Prompting best practices": "Add context to improve performance" (explain why, the ellipses
  example); "Tell Claude what to do instead of what not to do"; newer models "may now overtrigger. The fix is to dial
  back any aggressive language". https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Claude Platform docs, "Prompting Claude Haiku 5.5" (portkey, prefect, howler run on Haiku): early stopping in long
  agent prompts; JSON output with tools. https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5
- Anthropic Engineering, "Writing effective tools for agents — with agents" (2025-09-11): avoid overlapping tools;
  describe tools as to a new hire; error messages that "communicate specific and actionable improvements".
  https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic, "Building effective agents" (2024-12-19): simplicity, transparency, "Poka-yoke your tools".
  https://www.anthropic.com/engineering/building-effective-agents
- Measured here: `claude plugin details accio` (accio 0.5.0, 2026-10-20). Read here: curfew's real rules in
  `bin/accio_lib/policy.py` and `bin/accio_lib/bashpolicy.py`.

Unconfirmed: whether a step skill's `allowed-tools` apply while the conductor skill drives it (the docs describe one
invoking turn only), and how often the permission prompts of #10 appear in practice. Both need one real run.
