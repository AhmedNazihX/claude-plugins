# 010 — agent_allow entries match the whole command

Date: 2026-10-20 · Status: decided by the user (accepted the recommendation)

## What was decided
How an entry in `.accio/config.json`'s `agent_allow` list (extra commands accio's agents may run) matches a
command. Today it matches the start, so any arguments added after it pass too; the 2026-10-20 commit security review
flagged that a builder could append arguments to the two `claude` entries. It was the user's to decide because
tightening it could break a setting in another repo.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| Exact match | `claude plugin validate accio` passes; the same with `--some-flag` added is denied | closes the hole; one rule | settings in other repos that relied on the start match stop working until the full command is added at owl |
| Keep the start match | anything after an entry passes, as today | nothing changes | a builder can still append arguments |
| Two lists | the start-match list stays; a new `agent_allow_exact` list holds strict entries | strict where wanted | two rules to remember; easy to put an entry on the wrong list |

Costs:
- Exact match, risk: none in this repo (both entries are full commands; owl writes commands as typed); other repos not checked
- Keep the start match, risk: a builder appends arguments to an allowed command
- Exact match, tokens: one small story, security track
- Two lists, tokens: one small story plus docs

## Decision
Exact match.

## Why
The start match is the hole the security review found, and one rule is easier to trust than two; a repo that breaks
is fixed with one line at owl.

## Consequences
Listed checks (`checks` in config.json) and allow-once entries: checks keep the start match, because they need extra
arguments such as a test file; allow-once entries become exact too. `bashpolicy.py:13` and `BACKLOG.md:300` are
updated.
