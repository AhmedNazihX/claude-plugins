# 011 — A silent builder waits for spike S-R1 before any retry

Date: 2026-10-20 · Status: decided by the user (accepted the recommendation)

## What was decided
Group B retries accio's helper agents (portkey, prefect, the reviewers, headmaster) once when they give no answer
or an error. The question was whether the builder (house-elf) gets the same retry. Today one signal covers two
events: a stall (20 minutes with no output, maybe a network blip) and a spent turn budget (the builder used twice
the story's budget). A retry likely helps the first and wastes a whole run on the second. It was the user's to
decide because a retry can double a story's biggest cost.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| Wait for spike S-R1 | no builder retry yet; a by-hand test checks whether the build can tell a stall from a spent budget; if so, a later story retries stalls only | no wasted runs | a stalled builder still stops and asks until then |
| Retry now | any silent builder runs once more | fewer stall stops at once | a builder that spent its budget runs again, likely wasted |
| Never retry | a silent builder always stops and asks | simplest | the stall stop stays for good |

Costs:
- Wait, time: spike S-R1, about 30–60 min by hand (wandmaker's estimate)
- Retry now, tokens: up to one extra full builder run per silent story (unmeasured)
- Wait and Never, tokens: no change
- Interruptions: how often builders stall is not recorded yet; the new findings log will count it

## Decision
Wait for spike S-R1.

## Why
How often builders stall is unknown until the log counts it, and a blind retry risks doubling the most expensive
step for little gain.
