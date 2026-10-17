# 003 — Build engine: hybrid (skills with the user, one Workflow for the unattended build)

Date: 2026-10-17 · Status: decided by the user

## Decision
- **Skills** (`plan`, `review`, `quick`) handle everything the user takes part in, plus judgement between runs.
- **One plugin workflow** (`workflows/build.js`, run as `/<plugin>:build`) builds the ready stories unattended. The
  steps are load → prepare → implement → check → review → judge → fix (≤ 2) → outcome. The full spec is in
  `docs/research/build-engine.md` § "Option C in detail".

The record also settles three points that were going to be separate decisions:
- **Review policy:** a confidence threshold of 80. The panel depends on the track: Quick gets 1 reviewer, Story gets
  a spec reviewer plus a quality reviewer, and any risky path adds a security reviewer. There are **at most 2 fix
  rounds**, then the story goes to BLOCKED. Fix rounds use a fresh implementer and a scoped re-review.
- **WIP limit:** at most 3 stories in progress at once inside a build run.
- **Model per step:** Haiku for load, prepare and check. Sonnet for implementing, reviewing and judging. Opus only
  for complex or risky implementations. A fix in round 2 moves up one tier.

## Options compared
The full comparison is in `docs/research/build-engine.md`.
- A, Workflow everywhere: the strongest control, but weak on judgement calls, and new and unproven.
- B, superpowers-style skill controller: the proven mainstream, but its caps and stuck-agent detection depend on
  the model following instructions, which foreman's failures 2 and 3 show is the weak point.
- C, hybrid (chosen): caps sit in code where drift hurts, and judgement sits in skills and a judge agent.

## Consequences
- **The first backlog story is a spike.** It must prove that a plugin workflow can run the plugin's named agents and
  run them in a worktree the script created.
- **Fallback:** the same steps run as plain subagents driven by the `build` skill. Files and scripts stay the same.
- **Cost:** about the same worker cost as B. Main-chat cost is about 1–2k tokens per build run.
