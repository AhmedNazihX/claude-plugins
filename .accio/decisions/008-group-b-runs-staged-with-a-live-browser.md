# 008 — Group B runs staged, with a live browser for mad-eye

Date: 2026-10-20 · Status: decided by the user (C, of 3 options)

## What was decided
Where the two new reviewers sit in a story's build, and how mad-eye (the UI reviewer) reaches a browser. boggart
is the breaker agent: it writes small tests that try to make the story's code fail. mad-eye looks at the running
app and saves screenshots. It was the user's to decide because it trades build time and tokens against how fresh
boggart's breaks are and how much mad-eye can do.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| A. Staged | checks fixed first, then the reviewers, then boggart, then mad-eye; mad-eye writes a Playwright test that an accio script runs | boggart only attacks reviewed code; no tokens spent on stories that fail review; no browser tools needed | slowest; a late break may find no fix round left; mad-eye can't click through steps |
| B. One panel | after the checks, the reviewers, boggart and mad-eye start at once; one combined fix | fastest; a break always has both fix rounds | boggart attacks code the fixes then change; up to 15 agents at once with 3 stories in parallel |
| C. Live browser | A's order, but mad-eye drives the running app through the user's Playwright MCP server (MCP: the protocol Claude Code uses to talk to tool servers) | mad-eye can click, type and log in, so it suits screens that need steps | rests on two things the docs don't promise; needs the browser server in each repo; curfew must allow browser tools |

Costs:
- A, tokens: boggart about 50–100k a story, only on reviewed code (`breaker.md`, unmeasured); mad-eye 30–60k on UI stories (user's figure)
- B, tokens: the same per agent, but also spent on stories that later fail review (unmeasured)
- C, tokens: boggart as A; mad-eye likely above 60k, since each page snapshot enters its context (wandmaker's judgement)
- A, time to build: about 9–10 stories, one by-hand spike (wandmaker's estimate)
- B, time to build: about 9–10 stories (wandmaker's estimate)
- C, time to build: about 10–11 stories, two by-hand spikes of 30–60 min each (wandmaker's estimate)
- C, risk: high until the spikes pass; widens curfew (security)

## Decision
C, live browser. "so it can mimik a user correctly"

## Why
mad-eye should check a screen the way a user reaches and uses it, clicking and typing through the steps, which a
script-run test written blind (A) can't do.

## Consequences
Spikes S-M2 (does a workflow agent get the session's MCP tools?) and S-M3 (what happens when an agent names an MCP
server the session lacks?) come first; if S-M2 fails, mad-eye goes back to wand with A as the fallback. curfew lets
only mad-eye use a fixed list of browser tools, only on the preview's address and its own screenshot folder. A repo
without the Playwright MCP server gets a logged skip.
