# What could make accio better

Date: 2026-10-20. Inputs: `docs/DESIGN.md`, `docs/BACKLOG.md`, decisions 001–013, accio's own `.accio/` records
(7 iterations, 20 stories, `run/ledger.tsv`), git history, the code, a scan of new prior art, and the Claude Code
docs at version 2.1.304 (the current release; changelog entry of 2026-10-19).

This builds on `analysis.md` (2026-10-17) and does not repeat it. Adversarial testing (a "breaker" agent) is out of
scope; `breaker.md` covers it.

## The question

accio v1 works: it has built and merged 20 of its own stories. What has gone wrong or stayed open while using it,
what have comparable tools learned since the last scan, and which Claude Code features could cut its token cost,
its stops for the user, or its failures?

## Short answer

Ranked by value for effort. "Stop" means the user has to answer something before work goes on.

1. **Send failed checks into the fix rounds, instead of asking the user.** Today a failed check ends the story at
   once with "Should it be fixed and built again?" (`workflows/brew.js:220-235`). Only review findings get fix
   rounds. Every answer on record was "yes, build again" (`.accio/stories/S-001.md:59`, `S-008.md:31`,
   `S-012.md:26`). So it is a stop with no real decision, against decision 004 (`.accio/decisions/004-…md:28-30`).
   Effort: small to medium. Effect: about one stop, one extra `brew` and one extra `owl` saved per failed check
   (7 of 20 stories blocked at least once). Adds at most 2 fix rounds of tokens per failing story.
2. **Stop blocking on accio's own machinery.** 5 of those 7 blocks were caused by accio, not by the story's code:
   - a parallel build's `run/<ID>/base` counted as "main changed" (`S-002.md:39`, `S-005.md:26`, `S-010.md:26`,
     `S-012.md:26`)
   - a file list too narrow for the story's own eval files (`S-008.md:29-31`)
   - a test runner missing from the agents' allow list (`S-017.md:50`)
   Make a "machinery" failure class: retry it once on its own, and widen the boundary to the story's own test,
   eval and fixture folders. Effort: medium. Effect: fewer stops and rebuilds; each rebuild is a whole story's tokens.
3. **Fix lost iteration outcomes.** A second `owl` pass replaces the iteration's Outcome table instead of adding
   to it (`bin/accio_lib/owl.py:206-208`). Iteration 5 lost its S-018 and S-019 "merged" rows (commit `dc7dbff`),
   and iteration 2 shows no outcome for S-002, S-012 or S-013 (`.accio/iterations/2.md:14-19`). Every future
   retro reads these files. Effort: small. Effect: correct records; no token change.
4. **Make the script-only agents cheaper.** `portkey` and `prefect` (Haiku) only run accio's scripts, since
   workflow scripts have no shell (`DESIGN.md:157`). Give them `effort: low` and `omitClaudeMd: true`, and the same
   for `howler` and `librarian`. Both fields are documented
   ([sub-agents](https://code.claude.com/docs/en/sub-agents)); accio uses neither. The user's global rules and
   CLAUDE.md load into every one of these calls, several per story. Effort: small. Effect: fewer tokens and less
   time on every script call. *How much is not measured.*
5. **Inline the board into the skills with `` !`command` ``.** Skills can run a command and put its output into
   the skill text before the model reads it
   ([skills](https://code.claude.com/docs/en/skills)). `/accio` would get `accio-board next --json` already
   filled in (`skills/accio/SKILL.md:15`), and the same goes for `map`, `prophecy` and `owl`. Effort: small.
   Effect: one tool turn saved per loop, and the step the model reads is always fresh.
6. **Log why each finding and each block ended.** At `owl`, record for each review finding whether it was fixed or
   dismissed, and for each block whether the cause was the code or accio. Cursor counts a finding as real only if it
   was fixed by merge time ([Bugbot](https://cursor.com/blog/bugbot-learning): 52% at first). accio's budgets are
   guesses (`DESIGN.md:598`) and its reviewers' false-positive rate is unknown. Effort: small to medium. Effect: the
   data for items 7 and 2, for about 1 line per finding.
7. **A small evidence-only retro (`pensieve` lite).** Read the logs from item 6, `accio-cost` and the iteration
   files, then add short sourced rules to one playbook file, one item at a time, never by rewriting it. This pattern
   comes from ACE ([arXiv 2510.04618](https://arxiv.org/html/2510.04618)), Devin's memory
   ([docs](https://docs.devin.ai/product-guides/memory.md)) and OpenAI's Codex retro recipe
   ([cookbook](https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex)).
   `pensieve` is v2 (`DESIGN.md:220-224`). Effort: medium. Effect: one Sonnet agent per iteration; it should lower
   repeat findings over time.
8. **Batch small stories of the same shape into one build.** superpowers v6.3 does this: "Small same-shape tasks
   batch into one dispatch, cutting subagent cost sharply"
   ([release](https://github.com/obra/superpowers/releases/tag/v6.3.0)). A Quick story in accio still costs about
   5 agent calls: prepare, implement, check, review and outcome (`DESIGN.md:143-152`). Effort: medium. Effect:
   fewer agent calls on doc and typo stories such as S-019.
9. **Decide the ceremony after looking at the change.** BMAD v6.12: "Build decides how much ceremony a change needs
   after investigating it, not before"
   ([release](https://github.com/bmad-code-org/BMAD-METHOD/releases/tag/v6.12.0)). accio sets the track from a
   score before any code exists (`DESIGN.md:118-121`). Let `prefect` re-score from the real diff: a docs-only diff
   drops to one reviewer. Effort: small. Effect: fewer reviewer calls; risky paths still force the full panel.
10. **One goal check per iteration, after the merge.** It would be read-only and could only append. It compares the
    merged result with the design's outcome answer (decision 011) and adds missed work as new backlog stories. Spec
    Kit's `converge` does this ("its only possible write is adding tasks",
    [docs](https://github.github.io/spec-kit/reference/agentic-sdd.html)). MAST found that checking against the
    high-level goal gave "+15.6%" ([arXiv 2503.13657](https://arxiv.org/abs/2503.13657)). Effort: medium.
    Effect: one Sonnet agent per iteration; it catches stories that pass their DoD but miss the point.
11. **Make guard hooks fail closed with `onFailure: "block"`.** If a hook cannot run at all (a missing `python3`,
    an import error, a timeout), the tool call goes ahead. For `curfew` that means an agent can meet a permission
    prompt, which hangs the run (`DESIGN.md:154-156`). `curfew` already denies on a caught exception
    (`hooks/curfew.py:148`); this covers the cases before that point
    ([hooks](https://code.claude.com/docs/en/hooks), v2.1.295 and later). Effort: small. Effect: closes a hang path.
12. **Fix the stale always-on text.** The plugin description and the README still say accio asks "only at two
    checkpoints" (`.claude-plugin/plugin.json:4`, `README.md:4`). Since decision 004 it stops only for real
    decisions. The description is in every session's context and steers when the skills trigger. `BACKLOG.md:74`
    and `:519` say CI has never run, but it has (`.accio/stories/S-004.md:27`). Effort: small. Effect: clarity.

## Internal pain points

| # | What | Evidence |
|---|---|---|
| 1 | A failed check asks the user instead of fixing; every answer was "yes, build again" | `workflows/brew.js:220-235`; `.accio/stories/S-001.md:59`, `S-008.md:31`, `S-012.md:26` |
| 2 | Parallel builds tripped each other's main-checkout snapshot, 4 false blocks; parallel builds were switched off for a while | `S-002.md:39`, `S-005.md:26`, `S-010.md:26`, `S-012.md:26`; commits `e11f5f0`, `165ca6b` |
| 3 | The boundary check blocked files the story needed (its own eval folder) | `S-008.md:29-31` |
| 4 | The allow list blocked the project's own test runner | `S-017.md:50`; risk named at `DESIGN.md:592` |
| 5 | The DoD-tag check is a grep: tags built in a loop (`f"S-001/{line}"`) look untagged | `S-001.md:59` |
| 6 | The relayed starting message made `prefect` refuse its step, so the board never updated | `.accio/stories/S-020.md:13` |
| 7 | `howler` lost turns on `&&` chains and `git -C`, which curfew denies | `S-020.md:21` |
| 8 | A second `owl` pass overwrites the iteration's Outcome table | `bin/accio_lib/owl.py:206-208`; commit `dc7dbff`; `.accio/iterations/2.md:14-19` |
| 9 | No real token usage from the build: `agent()` reports none; the only hard stop is `maxTurns` per agent | `DESIGN.md:516-523`; `BACKLOG.md:168-169`, `:401` |
| 10 | Budgets are guesses, and the plan to tune them after two iterations has not happened after seven | `DESIGN.md:598` |
| 11 | The conductor loop follows a prompt, so it may stop early; "revisit with option B" | `.accio/decisions/003-…md:15`, `:43` |
| 12 | A bare "continue" can't start a build; only the user's own words opt in | `.accio/stories/S-014.md:23-29`; `skills/accio/SKILL.md:22-24` |
| 13 | All checks share one 9-minute budget; the suite took 256 s inside a story | `BACKLOG.md:350`; `S-017.md:50` |
| 14 | A DoD line taking `house-elf` over 30 minutes with no checkpoint lets the run lock go stale | `BACKLOG.md:395` |
| 15 | Known gaps in the early-warning shell parser, kept as notes on purpose | `BACKLOG.md:254-258` (decision 004) |
| 16 | No retro, no flow metrics, and the iteration files hold only two tables | `DESIGN.md:220-224`; `.accio/iterations/*.md` |
| 17 | No fallback build when workflows are off | decision 012; `BACKLOG.md:521-527` |
| 18 | The live run of `owl` starting `howler` from inside the skill is still open | `BACKLOG.md:48`, `:541` |
| 19 | Stale text: "two checkpoints"; "CI never ran" | `.claude-plugin/plugin.json:4`; `README.md:4`; `BACKLOG.md:74`, `:519` |
| 20 | Skills cached per session slow down dogfooding | `DESIGN.md:600` |

The ledger agrees: 11 of 30 recorded check runs failed (`.accio/run/ledger.tsv`). It is git-ignored, so it is
local evidence only.

## Prior art (new since 2026-10-17, or missed)

- **obra/superpowers v6.2–v7.0** (Jul–Oct 2026). The controller makes "a recorded ruling" on non-destructive
  conflicts and goes on, because "one donated session had sat blocked for almost nine hours". Same-shape tasks are
  batched. "The project's suite defines green, not just your test file": sessions ran only the named file "in 11 of
  12 probe runs". The controller can run as a nested mid-tier subagent for "about half the cost and wall clock".
  *Take:* items 1, 8, and run the full suite in the check. [releases](https://github.com/obra/superpowers/releases)
- **BMAD v6.10–v6.12** (Jul–Oct 2026). Ceremony is chosen after investigating, and simple changes get "a
  two-section spec". The Edge Case Hunter flags diffs "that special-case some members of a fixed set"; its catch
  rate rose 50–100% for 19% more tokens. *Take:* item 9; add the named-set check to `professor`'s checklist.
  [releases](https://github.com/bmad-code-org/BMAD-METHOD/releases)
- **GitHub Spec Kit v1.1–v1.2** (Oct 2026). `/speckit.converge` is append-only; YAML workflows can be resumed.
  *Take:* item 10. [agentic SDD](https://github.github.io/spec-kit/reference/agentic-sdd.html),
  [workflows](https://github.github.io/spec-kit/reference/workflows.html)
- **Kiro, spec correctness.** It turns EARS requirements into property-based tests, and when one fails it offers
  to fix "the spec, implementation, or test itself". A solver-based analysis asks each ambiguity as "a simple
  two-option question". *Take:* `quill` marks DoD lines that state a general rule, and those need a property test;
  a failing one asks the three-way question. [correctness](https://kiro.dev/docs/specs/correctness/),
  [deep spec analysis](https://kiro.dev/blog/deep-spec-analysis/)
- **Anthropic, "Harness design for long-running application development"** (2026). The generator and the evaluator
  "negotiated a sprint contract" on what done means before coding, and "every component in a harness encodes an
  assumption about what the model can't do on its own". *Take:* re-test every few model releases whether each
  agent is still needed. [post](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- **Anthropic, "Building a C compiler with a team of parallel Claudes"** (2026). Agents lock a task "by writing a
  text file to current_tasks/". Test output is kept short, and a fast mode runs a sample. *Take:* checks print
  one `ERROR <reason>` line and keep the rest in a file (helps item 2 and pain point 13).
  [post](https://www.anthropic.com/engineering/building-c-compiler)
- **Anthropic, "Demystifying evals for AI agents"** (2026). "20-50 simple tasks drawn from real failures is a great
  start", and "grade what the agent produced, not the path it took". *Take:* turn the 7 blocked builds into eval
  cases. [post](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- **Anthropic, multi-agent research system.** "Multi-agent systems use about 15× more tokens than chats"; effort
  should scale with the task. *Take:* items 8 and 9.
  [post](https://www.anthropic.com/engineering/multi-agent-research-system)
- **Anthropic, Claude Code auto mode.** A classifier approves or blocks each action, and users approve "93% of
  permission prompts". *Take:* see "Ideas dropped". [post](https://www.anthropic.com/engineering/claude-code-auto-mode)
- **OpenAI Codex ExecPlans.** A living plan with `Progress`, `Surprises & Discoveries`, `Decision Log` and
  `Outcomes & Retrospective` sections. *Take:* add "Surprises" and "Decisions" lines to `build-report.md`; the
  retro reads them. [cookbook](https://developers.openai.com/cookbook/articles/codex_exec_plans)
- **OpenAI Codex code review.** The public review prompt says "pre-existing bugs should not be flagged" and asks
  the reviewer to name the code that is "provably affected". *Take:* add both rules to `professor`'s known false
  positives. [review_prompt.md](https://github.com/openai/codex/blob/main/codex-rs/core/review_prompt.md)
- **OpenAI cookbook, iterating workflows with Codex.** The retro takes no plan or claim as proof, and each fix
  gets one owner. *Unconfirmed wording* (read through a summarising tool). *Take:* item 7.
  [cookbook](https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex)
- **Cursor Bugbot.** It measures a resolution rate, and turns feedback and missed bugs into rules it promotes or
  disables. *Take:* item 6, and later item 7. [learning](https://cursor.com/blog/bugbot-learning)
- **Devin.** Memory is one-line notes, each linked to its session, and a daily pass merges and prunes them.
  "Dynamic Workflows" make "the orchestration itself code". *Take:* item 7; and the Stop-hook conductor (under
  "Ideas considered and dropped") if `/accio` is seen to stop early. [memory](https://docs.devin.ai/product-guides/memory.md),
  [dynamic workflows](https://docs.devin.ai/work-with-devin/dynamic-workflows.md)
- **Factory Missions.** "total runs ≈ #features + 2 * #milestones … a floor rather than a ceiling", and validators
  run at each milestone. *Take:* show an agent-call estimate at `prophecy` (stories × (prepare + build + check +
  reviewers + outcome)). [planning](https://docs.factory.com/missions/planning)
- **Cline Focus Chain; Amp.** Cline re-injects the todo list every six messages. Amp removed its manual handoff
  because "compaction is in". *Take:* don't build context handoffs; compaction is enough for the conductor.
  [Cline](https://cline.bot/blog/cline-v3-25), [Amp](https://ampcode.com/news/neo)
- **Meta ACH, mutation-guided tests** (FSE 2025). It writes tests aimed at specific mutants and screens out
  mutants that don't change behaviour. *Take:* put each surviving mutant's line in the fix brief; let `examiner`
  mark an equivalent mutant so it doesn't block. [arXiv 2501.12862](https://arxiv.org/abs/2501.12862)
- **MAST, "Why Do Multi-Agent LLM Systems Fail?"** (NeurIPS 2025). It lists 14 failure modes; many verifiers do
  "only superficial checks". *Take:* item 10. [arXiv 2503.13657](https://arxiv.org/abs/2503.13657)
- **ACE, DGM, SICA** (2025). These systems improve their own context or code, then test the change. ACE warns of
  "context collapse" from rewriting, and adds to its playbook item by item. *Take:* item 7 adds rules one at a
  time. [ACE](https://arxiv.org/html/2510.04618), [DGM](https://arxiv.org/abs/2505.22954),
  [SICA](https://arxiv.org/abs/2504.15228)
- Not covered: Aider, Roo Code and Cursor plan mode; nothing new and concrete was found for 2026.

## Platform features not yet used

All checked in the docs on 2026-10-20 (Claude Code 2.1.304).

| Feature | What it gives accio | Doc |
|---|---|---|
| Subagent `effort` | `low` for `portkey`, `prefect`, `howler`, `librarian` (item 4) | [sub-agents](https://code.claude.com/docs/en/sub-agents) |
| Subagent `omitClaudeMd` | agents whose brief carries everything skip the CLAUDE.md files (item 4); keep them for `house-elf` and `professor`, which need project rules | [sub-agents](https://code.claude.com/docs/en/sub-agents) |
| Subagent `autoCompactWindow` | caps `house-elf`'s context on long stories | [sub-agents](https://code.claude.com/docs/en/sub-agents) |
| Skill `` !`command` `` injection | fresh board state with no tool turn (item 5) | [skills](https://code.claude.com/docs/en/skills) |
| Skill `disallowed-tools` | e.g. no `AskUserQuestion` in steps that must not ask when `/accio` drives | [skills](https://code.claude.com/docs/en/skills) |
| Hook `onFailure: "block"` | guards fail closed (item 11) | [hooks](https://code.claude.com/docs/en/hooks) |
| `Workflow(<name>)` allow rule | `accio-hooks verify` can check for `Workflow(accio:brew)` and say how to add it, so no run asks for approval | [workflows](https://code.claude.com/docs/en/workflows) |
| Usage-limit pause in workflows | a run that hits the usage limit now pauses instead of failing agents (v2.1.271 and later, interactive only); update `DESIGN.md` § 12.6 | [workflows](https://code.claude.com/docs/en/workflows) |
| Same-prefix cache stagger | parallel agents with the same model, type, tools and schema share one cache prefix; keep the reviewers' options alike to benefit | [workflows](https://code.claude.com/docs/en/workflows) |
| OpenTelemetry `workflow.run_id` | each API request is tagged with its workflow run, so a run's cost can be rebuilt; it needs an exporter the user sets up | [monitoring-usage](https://code.claude.com/docs/en/monitoring-usage) |
| `/usage` attribution | usage split by skills, subagents and plugins, for a quick check of `accio-cost` | [costs](https://code.claude.com/docs/en/costs) |
| `maxTurns` partial output | the Agent tool now returns a capped agent's output marked partial and can resume it; inside a workflow with a `schema` it still throws (spike S-001, finding 16), so this helps `reparo` and `howler`, not `brew` | [sub-agents](https://code.claude.com/docs/en/sub-agents) |
| Hook events `SubagentStart` (with `additionalContext`), `PostToolUseFailure`, `PermissionDenied`, `StopFailure` | e.g. inject the shared "starting message is the opt-in" paragraph (S-020) once instead of in 7 agent files. *Whether `SubagentStart` fires for workflow agents is not documented: a spike first* | [hooks](https://code.claude.com/docs/en/hooks) |
| Mods (`tool.check`, `agent.spawn`) | a plugin can ship an in-process JS module that decides tool calls after the hooks. It could replace `curfew`'s Python process on every tool call. Large rewrite; later | [mods reference](https://code.claude.com/docs/en/plugins/mods/reference) |
| Per-agent `effort` in `agent()` options | documented only in the bundled `/workflow-authoring` skill, not on the docs page. *Treat as unconfirmed*; use frontmatter `effort` instead | bundled skill |

Already ruled out, or not useful: agent teams are experimental and off by default
([agent-teams](https://code.claude.com/docs/en/agent-teams)); a plugin `settings.json` honours only `agent` and
`subagentStatusLine`, so it can't ship allow rules ([components](https://code.claude.com/docs/en/plugins/components));
plugins can't ship `.claude/rules` (no doc says so); `--max-budget-usd` works only in print mode
([cli-reference](https://code.claude.com/docs/en/cli-reference)); Channels and Routines are research previews.

## Ideas considered and dropped

| Idea | Why dropped |
|---|---|
| Recommend auto mode instead of growing `curfew`'s allow list | A classifier is a judgement, and P6 wants effects guarded by code (`DESIGN.md:65`). Also, a settings `ask` rule still freezes a workflow agent (spike S-015). `curfew` stays; item 2 fixes its narrow first list |
| Agent teams for parallel stories | Experimental; peer sessions are the "swarm" that non-goal 1 rules out (`DESIGN.md:42`) |
| A sprint contract: the reviewer approves a test plan before coding | One more agent call per story. accio's EARS DoD with one tagged test per line already fixes "done" before coding (`DESIGN.md:115-116`) |
| Move the conductor into a Stop-hook loop now (decision 003, option B) | No evidence yet that `/accio` stops early. Keep it as the planned fallback (`.accio/decisions/003-…md:43`), and log early stops via item 6 first |
| OpenTelemetry as accio's cost source | It needs a collector the user runs, which comes close to "no hosted services" (`DESIGN.md:43`). Transcripts already give usage to `accio-cost` |
| Resume the same implementer in fix rounds (superpowers does) | The 5-minute subagent cache makes a cold resume costly (`DESIGN.md:511-512`) |
| Context handoffs between steps | Amp removed them because compaction works; P8 already keeps state on disk |
| A weekly `telescope` routine | Routines are a research preview; decision 008 already defers it to v2 |
| Test-gaming checks (edited tests, `__eq__` overloads, special-cased inputs; ImpossibleBench, [arXiv 2510.20270](https://arxiv.org/abs/2510.20270)) | In scope for the breaker research (`breaker.md`), not here |

## Sources

Internal: `docs/DESIGN.md`; `docs/BACKLOG.md`; `docs/decisions/001`–`013`; `docs/research/analysis.md`,
`build-engine.md`, `platform-facts.md`, `spike-s001.md`; `.accio/decisions/001`–`004`; `.accio/iterations/1-7.md`;
`.accio/stories/S-001`–`S-020`; `.accio/run/ledger.tsv`; `workflows/brew.js`; `bin/accio_lib/owl.py`;
`hooks/curfew.py`; `skills/accio/SKILL.md`; `.claude-plugin/plugin.json`; `README.md`; git log (102 commits on
`accio/` and `.accio/`).

Claude Code docs (read 2026-10-20, version 2.1.304):
- https://code.claude.com/docs/en/workflows
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/skills
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/plugins/mods/reference
- https://code.claude.com/docs/en/plugins/components
- https://code.claude.com/docs/en/plugin-evals
- https://code.claude.com/docs/en/monitoring-usage
- https://code.claude.com/docs/en/costs
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/agent-teams
- https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md

Prior art:
- https://github.com/obra/superpowers/releases (v6.2.0–v7.0.0)
- https://github.com/bmad-code-org/BMAD-METHOD/releases (v6.10.0–v6.12.4)
- https://github.github.io/spec-kit/reference/agentic-sdd.html and .../workflows.html
- https://kiro.dev/docs/specs/correctness/ and https://kiro.dev/blog/deep-spec-analysis/
- https://www.anthropic.com/engineering/harness-design-long-running-apps
- https://www.anthropic.com/engineering/building-c-compiler
- https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- https://www.anthropic.com/engineering/multi-agent-research-system
- https://www.anthropic.com/engineering/claude-code-auto-mode
- https://developers.openai.com/cookbook/articles/codex_exec_plans
- https://github.com/openai/codex/blob/main/codex-rs/core/review_prompt.md
- https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex (wording unconfirmed)
- https://cursor.com/blog/bugbot-learning
- https://docs.devin.ai/product-guides/memory.md and https://docs.devin.ai/work-with-devin/dynamic-workflows.md
- https://docs.factory.com/missions/planning
- https://cline.bot/blog/cline-v3-25 and https://ampcode.com/news/neo
- https://arxiv.org/abs/2501.12862 (Meta ACH), https://arxiv.org/abs/2503.13657 (MAST),
  https://arxiv.org/html/2510.04618 (ACE), https://arxiv.org/abs/2505.22954 (DGM),
  https://arxiv.org/abs/2504.15228 (SICA), https://arxiv.org/abs/2510.20270 (ImpossibleBench)
