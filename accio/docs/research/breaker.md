# Breaker agent (boggart): prior art

Date: 2026-10-20. This is the input to a future decision on `boggart`.

## The question
Every check in a brew run today measures a story against its own Definition of Done (DoD). Nobody runs the feature
against inputs the DoD never named. What do published systems, papers and testing practice say about an agent whose
only job is to break the feature, and how should `boggart` work so its breaks are real, in scope and cheap?

## Short answer
- **Copy "no repro, no break", and make a script check it.** A break counts only when a script runs boggart's test
  and sees it fail on the story's head, for the reason boggart claims. Agentless, Otter++, SWT-bench and Meta's
  catching tests all keep only tests that actually fail on the code under test. When a test that used to pass on the
  base fails on the story's head, that is the strongest signal of all.
- **Expect most raw breaks to be wrong, so a break never starts a fix round by itself.** Of the bug reports from
  Anthropic's property-testing agent, 56% were valid. At Meta, 8 of 41 candidate catches were real. curl's confirmed
  rate fell below 5% once AI reports arrived. Rule 2 (an out-of-DoD break becomes a note or a backlog story) fits
  this evidence.
- **Ground every expected behaviour in a written claim.** That means the DoD, the story's Context, a docstring, or
  how callers use the code. Never use what boggart merely thinks is true. The two biggest sources of false breaks
  are ambiguous intent and inputs that callers already reject. Also, LLM-written assertions tend to copy what the
  code does, not what it should do.
- **Use a method checklist, not a persona.** List the change's risks first, as Meta's intent-aware workflow does,
  then attack them with Hendrickson's cheat sheet (boundaries, 0/1/many, interruptions, sequences), Bach's product
  elements (SFDIPOT) and property patterns (round trips, invariants, metamorphic relations).
- **Keep boggart separate and fresh.** In AgentCoder, tests from a separate test designer were correct 87.8% of the
  time. Tests written by the agent that also wrote the code were correct 61.0% of the time. Claude Code's own
  guidance is to let a fresh agent try to refute the result.
- **Plan to tune it against logs.** Anthropic found that "out of the box, Claude is a poor QA agent": it found real
  problems and then approved the work anyway. Claude Code's docs warn of the opposite: a reviewer that is asked
  for gaps reports some even when the work is sound. Give boggart a short eval set of known breaks and known
  non-breaks.
- **The budget looks right if it stays narrow.** In Anthropic's harness, one QA round cost $3.24 against $71.08 for
  the build round. Anthropic's property-testing agent cost $5.87 per module on Opus 4.1. Cap boggart at a few
  charters and a few properties per story.
- **Avoid:** editing code, broad "test everything" charters, side effects outside the scratch folder, and treating
  "found nothing" as proof.

## 1. Adversarial and tester agents for code

**AgentCoder** ([Huang et al., 2023](https://arxiv.org/abs/2312.13010)) splits the work across three agents: a
programmer, a *test designer* and a *test executor*. The test designer writes tests without seeing the code,
because "the tests designed by the same agent that generates the code can be biased by the code and lose
objectivity" ([paper § 4.7](https://arxiv.org/html/2312.13010)). Measured: tests from the separate designer were
correct 87.8% / 89.9% of the time on HumanEval / MBPP, against 61.0% / 51.8% when one agent wrote both. Line
coverage was 87.5% against 72.5% on HumanEval. Pass@1 (solved on the first try) reached 96.3% on HumanEval.
*For boggart:* do not let boggart see `house-elf`'s reasoning or build report. Give it the story, the DoD and the
diff. Keeping it separate is the main lever.

**MetaGPT** ([Hong et al., 2023](https://arxiv.org/abs/2308.00352)) has a QA Engineer who "formulates test cases to
enforce stringent code quality". Its executable feedback loop runs the tests, debugs, and stops after three retries
([paper § 3.3](https://arxiv.org/html/2308.00352)). Measured: +4.2% pass@1 on HumanEval and +5.4% on MBPP, and
human revision cost on its SoftwareDev set fell from 2.25 to 0.83. *For boggart:* running the tests is what helped,
and the retry cap is fixed. Copy both.

**ChatDev** ([Qian et al., ACL 2024](https://arxiv.org/abs/2307.07924)) splits testing into code review (static) and
system testing (dynamic), with a tester agent that runs the code. The most frequent dynamic error was
`ModuleNotFound` (45.76%), and the most common review issue was "Method Not Implemented" (34.85%)
([paper](https://arxiv.org/html/2307.07924)). *For boggart:* a tester left without a method mostly finds shallow
breakage. accio's checks already catch that. Boggart needs a method that reaches past it.

**MapCoder** ([Islam et al., ACL 2024](https://arxiv.org/abs/2405.11403)) avoids generated tests on purpose. Its
debugging agent uses "only the sample I/O", because "incorrect test cases can lead to erroneous code"
([paper](https://arxiv.org/html/2405.11403)). It reached 93.9% pass@1 on HumanEval. *For boggart:* this is why
boggart's tests must never feed straight into a fix round. A wrong test drives a wrong fix.

**SWE-agent** tells the model to "create a script to reproduce the error and execute it … to confirm the error"
before editing, and to rerun it after the fix
([default config](https://github.com/SWE-agent/SWE-agent/blob/main/config/default.yaml)). **SWT-bench**
([Mündler et al., 2024](https://arxiv.org/abs/2406.12952)) measures whether agents can turn an issue into a test that
fails before the fix and passes after it (fail-to-pass). The best agent, SWE-Agent+, managed this on 18.5% of
issues. Agents built for repair beat tools built for test generation. Keeping only fixes whose generated tests are
fail-to-pass or pass-to-pass "more than doubles the precision of SWE-Agent to 47.8%", at about 20% recall
([paper](https://arxiv.org/html/2406.12952)). *For boggart:* a coding agent (Sonnet in Claude Code) is the right
tool for this. Most breaks will not reproduce, and the ones that do are worth a lot.

**Otter** ([Ahmed et al., 2025](https://arxiv.org/abs/2502.05368)) writes tests from an issue before any patch
exists. Rule-based checks fix the model's mistakes: invented file names, invalid actions and missing imports.
Otter++ throws away tests that pass on the old code and prefers a test that fails with an *assertion* over one that
fails with an error ([paper](https://arxiv.org/html/2502.05368)). Measured: 37.0% fail-to-pass with GPT-4o, against
18.7% zero-shot. *For boggart:* the validity script should reject a repro that fails on an import error, a syntax
error or a missing fixture. A real break fails on an assertion or on a crash inside the feature.

**Agentless** ([Xia et al., 2024](https://arxiv.org/abs/2407.01489)) generates reproduction tests, keeps only those
that print "Issue reproduced" on the original code, and uses them to pick a patch. Its own numbers show how noisy
such tests are: of 213 tests that reproduced the issue, only 94 passed on the correct fix
([paper § 5.1.3](https://arxiv.org/html/2407.01489)). *For boggart:* even a test that does fail can encode the wrong
expected behaviour. A failing repro proves "something differs". It does not prove "the code is wrong".

**Meta: Just-in-Time catching tests** ([Becker, Harman et al., FSE 2026](https://arxiv.org/abs/2601.22832)) is the
closest match to boggart. A *catching test* is written to "fail on the proposed changes … but pass on the parent
revision". Its intent-aware workflow first lists the *risks* of the diff (ways the change could go wrong), turns each
into a test, and keeps the tests that fail. Rule-based and LLM assessors then filter false positives, which cut
human review load by 70%. The false-positive patterns include broken infrastructure, brittle mocks, assertions on
private details (call counts, key order), intentional changes, and flaky tests
([paper](https://arxiv.org/html/2601.22832)). Measured: 8 of 41 candidate catches sent to engineers were real
(19.5%), and 4 of those would have caused serious failures. Dismissing a false one "took only a few minutes".
*For boggart:* copy the "list the risks, then test each one" method and the base-versus-head check. Copy the
false-positive patterns into the validity rules. Ask the user a cheap question ("was this intended?") instead of
starting a fix.

**Anthropic, "Building effective agents"** ([2024](https://www.anthropic.com/engineering/building-effective-agents))
describes the *evaluator-optimizer* pattern: one call generates and another evaluates "in a loop". It works best
"when we have clear evaluation criteria". Agents should gain "ground truth" from the environment, "such as tool call
results or code execution". *For boggart:* boggart's "criteria" are claims from the story. Its ground truth is a
command that fails.

**Claude Code best practices** ([docs](https://code.claude.com/docs/en/best-practices)): "a verification subagent …
has a fresh model try to refute the result, so the agent doing the work isn't the one grading it". It also says to
"have Claude show evidence rather than asserting success". And it warns: "A reviewer prompted to find gaps will
usually report some, even when the work is sound … Chasing every finding leads to over-engineering … tests for cases
that can't happen." *For boggart:* this backs both rule 1 (evidence) and rule 2 (do not chase every break).

**Anthropic, harness design for long-running apps**
([Rajasekaran, 2026-03-24](https://www.anthropic.com/engineering/harness-design-long-running-apps)). A QA agent
drove the running app with Playwright and failed a sprint when any criterion fell below its threshold. "Out of the
box, Claude is a poor QA agent": early runs found real issues and then approved the work anyway, and tested
superficially. The author fixed this over several rounds by reading the evaluator's logs and revising its prompt.
Tuning a standalone evaluator to be skeptical "is more tractable than making a generator critical of its own work".
Cost: QA round 1 took 8.8 minutes and $3.24, against 2 hours 7 minutes and $71.08 for build round 1. *For boggart:*
budget for tuning, and keep boggart's verdict mechanical (did the repro fail?) so leniency cannot hide a break.

**Anthropic Frontier Red Team, 0-days** ([Carlini et al., 2026-02-05](https://www.anthropic.com/research/zero-days)).
Claude ran in a VM with fuzzers and debuggers and no custom harness, and found more than 500 high-severity
vulnerabilities. The team "validated every bug extensively before reporting it" and focused on memory bugs, because
crashes and sanitizers make them easy to verify. Claude found bugs by reading git history (a fix that missed one
caller), by searching for risky call patterns, and by reasoning about the algorithm. *For boggart:* pick break types
a machine can verify, and look at the diff's neighbours: a story that fixes one caller may have missed another.

**OpenAI Aardvark / Codex Security** (October 2025) reportedly reproduces each finding in a sandbox before reporting
it, with 92% recall on seeded test repos. *Unconfirmed:* openai.com refused the fetch, so this rests on secondary
coverage ([The Hacker News](https://thehackernews.com/2025/10/openai-unveils-aardvark-gpt-5-agent.html)).

## 2. LLM-driven fuzzing and property-based testing

**OSS-Fuzz-gen** ([Google, 2024-11-20](https://security.googleblog.com/2024/11/leveling-up-fuzzing-finding-more.html);
[repo](https://github.com/google/oss-fuzz-gen)). An LLM writes fuzz targets (small harnesses that feed random input
to a function), fixes compile errors, runs them, and triages crashes. Measured: coverage rose in 272 C/C++ projects
(370k+ new lines covered), and 26 new vulnerabilities were found, including OpenSSL CVE-2024-9143. Every crash is
first sorted into "bug in fuzz driver" or "bug in project". Richer context (types, callers, existing tests) made the
model "less likely … to hallucinate". Triage still needs a human before reporting. *For boggart:* copy the
driver-or-project question. A repro that crashes because of boggart's own setup is not a break.

**Agentic property-based testing** (Anthropic authors: [Maaz, DeVoe, Hatfield-Dodds, Carlini, 2025](https://arxiv.org/abs/2510.09907);
[prompt](https://github.com/mmaaz-git/agentic-pbt/blob/main/hypo.md)). A Claude Code slash command reads a module,
proposes properties, writes Hypothesis tests (Hypothesis is a Python library that generates many inputs and shrinks a
failure to the smallest example), and triages failures. Its rules: "Only test properties that the code is explicitly
claiming to have"; check callers, because "if all callers validate input first, testing unvalidated input is a false
alarm"; prefer "sound but incomplete" input strategies; test "a few high-impact properties". Its triage rubric asks
four things: can you write a minimal standalone repro, is the input realistic, is the property claimed, and does it
matter to users. The agent runs sandboxed and may only run `python` and `pytest`. Measured on 100 packages: 984
reports, 56% valid and 32% worth reporting. The top-ranked 21 were 86% valid. Cost: $54.74 per package, $5.87 per
module, about $9.93 per valid bug, on Opus 4.1 ([paper](https://arxiv.org/html/2510.09907)). The main invalid type
is intent ambiguity, where a design choice looks like a bug. *For boggart:* this is the best template. Copy the
property patterns, the evidence rule, the triage rubric and the report format.

**"Can LLMs write good property-based tests?"** ([Vikram, Lemieux, Sunshine, Padhye, 2023–24](https://arxiv.org/abs/2307.04346)).
The paper scores generated property tests on validity (they run), soundness (they don't fail on correct code) and
*property coverage*, checked by running them against deliberately broken "property mutants". Measured: the best
setup needed about 2.4 samples per valid, sound test, and the best model covered only 21% of documented properties.
*For boggart:* a single draft property test is often wrong. Running it, then shrinking or dropping it, is the normal
path, not a failure.

**Fuzz4All** ([Xia et al., ICSE 2024](https://arxiv.org/abs/2308.04748)) uses an LLM as the input generator for
compilers and solvers in six languages. It found 98 bugs, and 64 were confirmed as previously unknown. **TitanFuzz**
([Deng et al., ISSTA 2023](https://arxiv.org/abs/2212.14834)) fuzzes TensorFlow and PyTorch the same way. It found
65 bugs, 41 of them confirmed new. *For boggart:* LLMs are good at producing *odd but valid* inputs. Have boggart
write the generator (a Hypothesis strategy, a list of nasty strings) and let a tool run thousands of cases, rather
than hand-picking a few.

## 3. Human exploratory testing heuristics

**Test Heuristics Cheat Sheet** (Hendrickson, Lyndsay, Emery, 2006;
[PDF, archived](http://web.archive.org/web/2019id_/http://testobsessed.com/wp-content/uploads/2011/04/testheuristicscheatsheetv1.pdf)).
Variable analysis ("identify anything whose value can change"), boundaries, Goldilocks (too big, too small, just
right), CRUD, follow the data, interruptions (cancel, kill, timeout), starvation, position (beginning, middle, end),
selection (some, none, all), count (0, 1, many), multi-user, flood, dependencies, constraints, sequences
(undo, reverse, simultaneous), and state analysis. Its data attacks list names that are too long, special
characters, leap days, time zones, numbers at 2^15, 2^31 and 2^32, blank, single space, and leading spaces. "It's
all about the variables." *For boggart:* this is a ready checklist that fits on one page.

**Explore It!** ([Hendrickson, 2013](https://pragprog.com/titles/ehxta/explore-it/)) frames each session as a
*charter*. "A good charter offers direction without overspecifying test actions." Charters that are too broad mean
"you won't know how to tell when you're done". Exploring "can reveal opportunities to add new requirements", which
the tester then reviews with stakeholders, and an implicit expectation (such as response time) still counts
([chapter 2 excerpt](https://media.pragprog.com/titles/ehxta/charters.pdf)). The charter template "Explore *target*
with *resources* to discover *information*" is widely attributed to the book. *Unconfirmed:* the free excerpt starts
just after it. *For boggart:* write 2–3 small charters per story. A new requirement found this way becomes a backlog
story, as in the book's example, which is exactly rule 2.

**Heuristic Test Strategy Model** (James Bach; [current v6.3 page](https://www.satisfice.com/download/heuristic-test-strategy-model);
[v5.7 PDF, archived](http://web.archive.org/web/2018id_/http://www.satisfice.com/tools/htsm.pdf)). Product elements,
known as SFDIPOT: **S**tructure, **F**unction (including error handling), **D**ata (cardinality, big/little, noise,
lifecycle), **I**nterfaces, **P**latform, **O**perations (disfavoured and extreme use), **T**ime (fast/slow,
concurrency). "Testers who focus on only a few of these are likely to miss important bugs." *For boggart:* use it to
pick charters, not to cover everything.

**FEW HICCUPPS** (Michael Bolton; [developsense, 2012](https://developsense.com/blog/2012/07/few-hiccupps)) is a list
of *oracles*: ways to recognise a problem. Each one asks whether the product is consistent with something:
Familiarity, Explainability, World, History, Image, Claims, Comparable products, User desires, Product, Purpose, and
Statutes. Oracles are fallible: an inconsistency "suggests a possible problem but doesn't guarantee one". *For
boggart:* only **Claims** (the DoD, docs, Context), **History** (the base behaviour) and **Product** (the same thing
elsewhere in the code) can be checked without a human. Breaks judged by the other oracles go to the review note as
questions, never as failures.

**Principles of Chaos Engineering** ([principlesofchaos.org](https://principlesofchaos.org/)): define a measurable
"steady state", hypothesise that it holds, introduce "real world events", then "try to disprove the hypothesis".
Measure outputs, not internals. "Minimize blast radius." *For boggart:* phrase each attack as "the claimed behaviour
still holds when X happens". Watch outputs, not private details. Keep the blast radius to the scratch folder and the
worktree: no network calls, no shared services, no writes to the main checkout.

## 4. False positives, hallucinated bugs and the oracle problem

The *oracle problem* is knowing what the right answer is. A breaker can easily produce an input. Saying the output
is wrong is the hard part.

| Source | Valid share of what the tool flagged | How it filtered |
|---|---|---|
| Agentic PBT ([arXiv](https://arxiv.org/html/2510.09907)) | 56% valid, 32% worth reporting | evidence rule, triage rubric, ranking, manual review |
| Meta JiT catching ([arXiv](https://arxiv.org/html/2601.22832)) | 8 of 41 (19.5%) | fail-on-diff and pass-on-parent, rule and LLM assessors, ask the engineer |
| Agentless ([arXiv](https://arxiv.org/html/2407.01489)) | 94 of 213 reproducing tests passed on the true fix | must reproduce on the original code; regression tests ranked first |
| SWT-bench ([arXiv](https://arxiv.org/html/2406.12952)) | best agent: 18.5% fail-to-pass | fail-to-pass check |
| Meta TestGen-LLM ([arXiv](https://arxiv.org/abs/2402.09171)) | 75% built, 57% passed reliably, 25% added coverage | build, repeat runs, coverage gain |
| curl bug bounty ([Stenberg](https://daniel.haxx.se/blog/2026/01/26/the-end-of-the-curl-bug-bounty/)) | above 15% confirmed before 2025, below 5% from 2025 | humans; the bounty ended on 2026-01-31 |

- **Hallucinated bugs.** OpenAI's critic models (CriticGPT) caught more bugs than paid contractors, but "can have
  limitations of their own, including hallucinated bugs" that could lead people astray. Human-plus-critic teams
  hallucinated less than the model alone ([McAleese et al., 2024](https://arxiv.org/abs/2407.00215)).
- **Assertions that copy the code.** "LLMs are prone to generate test oracles that capture the actual program
  implementation rather than the expected one." Accuracy dropped about 6–16 points when the code was buggy
  ([Konstantinou, Degiovanni, Papadakis](https://arxiv.org/html/2410.21136v2)). Descriptive names helped. For
  boggart, the expected value must come from the story or the docs, never from running the code first.
- **Flaky tests.** TestGen-LLM keeps only tests that pass on repeated runs, and Meta's assessors treat flakiness as
  a false-positive pattern. Run the repro more than once.
- **Equivalent changes.** Meta's mutation-guided test generator needed a detector for mutants that change nothing
  (precision 0.79 and recall 0.47, rising to 0.95 and 0.96 with simple pre-processing) ([ACH](https://arxiv.org/abs/2501.12862)).
  The same trap applies to boggart: a test that "fails" only because of a harmless difference (key order, float
  noise) is not a break.

## What to avoid

- **Scope creep.** A breaker that finds things outside the DoD can push the builder into "tests for cases that can't
  happen" ([Claude Code docs](https://code.claude.com/docs/en/best-practices)). Meta found that intentional changes
  are a top source of false catches ([JiT](https://arxiv.org/html/2601.22832)). Hendrickson's tester turns a new idea
  into a list item for the analyst, not a change to the current feature
  ([excerpt](https://media.pragprog.com/titles/ehxta/charters.pdf)). Keep rule 2. Only a break that shows a numbered
  DoD line failing should reach `examiner` as a normal finding.
- **False positives.** With a valid share between 5% and 56% in the table above, a break that goes straight into a
  fix round would mostly create work. Require: (a) a test file in the scratch folder, (b) a script that runs it and
  sees it fail on the story's head, (c) a failure on an assertion or a crash inside the feature, not on an
  import or setup error, (d) the same result on a second run, and (e) a written claim it violates, quoted with its
  source. Where the code existed before the story, also run the test on the base: passes there and fails on head
  is a regression, the strongest kind of break.
- **Cost.** Agentic PBT spent $54.74 per *package* on Opus 4.1 with open-ended exploration
  ([arXiv](https://arxiv.org/html/2510.09907)). Boggart works on one story's diff, so it should stay far below that.
  Anthropic's QA round was about 5% of the build round's cost
  ([harness post](https://www.anthropic.com/engineering/harness-design-long-running-apps)). Keep the cost down with
  fixed caps: at most 3 charters, at most about 5 properties, one validity run per repro, and no second pass. Skip
  boggart on docs-only and config-only diffs. The 50–100k Sonnet token guess is plausible but unmeasured. Measure
  it on the first stories.
- **A lenient or noisy breaker.** Both failure modes are documented. Tune boggart against a small eval set: stories
  with a planted out-of-DoD bug, and clean stories it must leave alone.

## Proposed method checklist for boggart

1. **Read the claims.** The story's DoD, Context and outcome; docstrings and comments in the diff; how callers use
   the changed code. Write down each claim with its source. No claim, no attack.
2. **List the risks.** Write 3–6 ways this change could go wrong (Meta's intent-aware step), and pick at most 3 as
   charters: "Explore *the changed function* with *these inputs* to discover *whether claim N still holds*".
3. **Attack each charter** with the cheat sheet and SFDIPOT:
   - Data: boundaries, 0/1/many, empty, blank, very long, unicode, special characters, wrong type, duplicates,
     big numbers (2^31, 2^32), negative numbers, floats and NaN, dates (leap day, time zone, DST).
   - Sequence and state: repeat the call, reverse the order, undo, interrupt halfway (cancel, kill, timeout), call
     twice at once.
   - Environment: missing file, file already exists, read-only file, no network, slow dependency, full disk (only
     where it is safe inside the scratch folder).
   - Properties: round trip, invariant, inverse pair, same result as another path in the product, metamorphic
     relation. Let a tool generate the inputs (Hypothesis, fast-check, proptest) when the project has one.
   - Neighbours: other callers of the changed code, and the same pattern elsewhere (the one-missed-caller bug).
4. **Judge with a written claim only:** Claims, History (the base behaviour) or Product (the same thing elsewhere).
   Anything judged only by "users would expect" becomes a question, not a break.
5. **Triage each failure.** Can it be reproduced with a minimal standalone test? Is the input realistic, and do
   callers allow it? Is the behaviour actually claimed? Does it matter? Is it the code's fault, not the test's
   setup? If any answer is no, refine the test or drop it.
6. **Prove it.** Save the repro test in the scratch folder and hand over its command. The script runs it on head
   (and on base where that makes sense) and records pass or fail. Boggart never edits the story's code.
7. **Report.** For each break: the claim it violates (DoD line or source), the repro command, the observed and
   expected result, and in or out of the DoD. In-DoD breaks go to `examiner`. Out-of-DoD breaks become a review note
   or a backlog story. If nothing broke, list what was tried, so a clean result shows its coverage.

## Sources

- AgentCoder: <https://arxiv.org/abs/2312.13010>, <https://arxiv.org/html/2312.13010>
- MetaGPT: <https://arxiv.org/abs/2308.00352>, <https://arxiv.org/html/2308.00352>
- ChatDev: <https://arxiv.org/abs/2307.07924>, <https://arxiv.org/html/2307.07924>
- MapCoder: <https://arxiv.org/abs/2405.11403>, <https://arxiv.org/html/2405.11403>
- SWE-agent default prompt: <https://github.com/SWE-agent/SWE-agent/blob/main/config/default.yaml>
- SWT-bench: <https://arxiv.org/abs/2406.12952>, <https://arxiv.org/html/2406.12952>
- Otter / TDD-Bench-Verified: <https://arxiv.org/abs/2502.05368>, <https://arxiv.org/html/2502.05368>
- Agentless: <https://arxiv.org/abs/2407.01489>, <https://arxiv.org/html/2407.01489>
- Meta, Just-in-Time catching test generation: <https://arxiv.org/abs/2601.22832>, <https://arxiv.org/html/2601.22832>
- Meta, TestGen-LLM: <https://arxiv.org/abs/2402.09171>
- Meta, mutation-guided test generation (ACH): <https://arxiv.org/abs/2501.12862>
- Anthropic, Building effective agents: <https://www.anthropic.com/engineering/building-effective-agents>
- Claude Code best practices: <https://code.claude.com/docs/en/best-practices>
- Anthropic, harness design for long-running apps: <https://www.anthropic.com/engineering/harness-design-long-running-apps>
- Anthropic, LLM-discovered 0-days: <https://www.anthropic.com/research/zero-days>
- OpenAI, CriticGPT paper: <https://arxiv.org/abs/2407.00215>
- Aardvark (secondary only): <https://thehackernews.com/2025/10/openai-unveils-aardvark-gpt-5-agent.html>
- Google OSS-Fuzz AI fuzzing: <https://security.googleblog.com/2024/11/leveling-up-fuzzing-finding-more.html>, <https://github.com/google/oss-fuzz-gen>
- Agentic property-based testing: <https://arxiv.org/abs/2510.09907>, <https://arxiv.org/html/2510.09907>, <https://github.com/mmaaz-git/agentic-pbt/blob/main/hypo.md>
- Can LLMs write good property-based tests?: <https://arxiv.org/abs/2307.04346>
- Fuzz4All: <https://arxiv.org/abs/2308.04748>
- TitanFuzz: <https://arxiv.org/abs/2212.14834>
- LLM-generated oracles: <https://arxiv.org/abs/2410.21136>, <https://arxiv.org/html/2410.21136v2>
- Test Heuristics Cheat Sheet: <http://web.archive.org/web/2019id_/http://testobsessed.com/wp-content/uploads/2011/04/testheuristicscheatsheetv1.pdf>
- Explore It!: <https://pragprog.com/titles/ehxta/explore-it/>, <https://media.pragprog.com/titles/ehxta/charters.pdf>
- Heuristic Test Strategy Model: <https://www.satisfice.com/download/heuristic-test-strategy-model>, <http://web.archive.org/web/2018id_/http://www.satisfice.com/tools/htsm.pdf>
- FEW HICCUPPS: <https://developsense.com/blog/2012/07/few-hiccupps>
- Principles of Chaos Engineering: <https://principlesofchaos.org/>
- curl bug bounty ending: <https://daniel.haxx.se/blog/2026/01/26/the-end-of-the-curl-bug-bounty/>
