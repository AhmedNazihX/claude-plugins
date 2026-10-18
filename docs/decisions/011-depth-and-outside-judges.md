# 011 — Depth and outside judges (from "How to be more ambitious")

Date: 2026-10-18 · Status: decided by the user ("do all 4")

Source: Felix Rieseberg, *How to be more ambitious: a tutorial for humans with models* (2026-10-13),
<https://felixrieseberg.com/how-to-be-more-ambitious-a-tutorial-for-humans-with-models/>. Its strongest point fits
accio's principle P5: "Do not ask the model to judge itself", ideally a judge that is "a tool the model can run".

## Decision
1. **A scripted test audit moves into v1** (it was a v2 candidate in DESIGN § 7.1). `prefect`'s check script runs
   the project's own mutation tool (for example `mutmut` for Python, Stryker for JS/TS, `cargo-mutants` for Rust),
   limited to the lines the story changed, and re-runs the tagged tests against each mutant. A mutant that no
   tagged test catches points at a weak test and is listed in `weak_tests`; the story gets a finding. No model is
   involved. A project with no mutation tool set up gets "not audited", and `examiner`'s judgement stands as
   before. Evidence: while building S-002..S-013 by hand, breaking one line at a time caught tests that passed for
   the wrong reason in nearly every story.
   *Amended the same day (side-agent review, decided by the user):* the first version reverted the story's whole
   change at once. That is too blunt: reverting a new file makes every test fail to load, which counts as
   "failed", so it would have caught almost none of those weak tests.
   *Contract, decided by the user on 2026-10-18 (option A of three: a config command / accio's own engine / defer):*
   `mutation.command` in `config.json` names the tool's command with `{diff}` where the story's diff file goes.
   The tool mutates only the changed lines (natively, like `cargo mutants --in-diff`, or through a small wrapper
   for Stryker or mutmut) and prints each surviving mutant on its own line starting `file:line`. `weak_tests` lists
   those lines: no tool can tell which DoD line's test should have caught a mutant. accio's own engine stays a v2
   fallback for projects without a tool.
2. **`wandmaker` answers four depth questions for each option:** what would a top professional in this field do;
   what is the rawest material (data, logs, the real system) to work from; which methods and tools the best
   people use; and what, other than the model or the user, would show the result is right. The last answer seeds
   the stories' DoD lines.
3. **Reviewers carry method checklists picked by the story's risk flag** (for example performance, data
   migration, auth and security, accessibility). Each lists what an expert in that area would run or inspect, not
   a voice to write in ("do what a short seller does", not "write like one").
4. **`wand` asks for the outcome behind the request:** "after this ships, what should be true, and how would you
   know?" `quill` copies the answer into each story's Context, so every agent sees the goal behind its story.

## Not adopted, and why
- "Ask for an unreasonable goal" and "keep going, it's solvable": they clash with fixed, testable DoD lines, the
  ≤ 2 fix rounds and the 2× budget stop (P2, DESIGN § 7.1, § 8).
- Higher-altitude goals for build agents: stories stay small on purpose (P1, `accio-score` splits big ones).
- New-knowledge research and simulations: accio builds software stories; the nearest fit is `pensieve` (v2).

## Cost
- Test audit: minutes of extra check time per story, one tagged-test run per mutant on the changed lines (time,
  no tokens); about one story's worth of work inside S-017; needs a mutation tool per language.
- Depth questions: a few thousand more Opus tokens per design; no new questions to the user.
- Checklists: near zero (text inside the existing reviewers).
- Outcome question: one more `wand` interview question, inside a step that already asks questions.
