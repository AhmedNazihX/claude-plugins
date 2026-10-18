# Decision record format

Every record has these parts, in this order. `accio-vow record` refuses a record without the four `##` sections or
with one left empty. Take every word from the conversation: the example below shows the shape only, never its
content.

```markdown
# 014 — Postmark for transactional email

Date: 2026-10-18 · Status: decided by the user (Postmark, of two options)

## What was decided
Which service sends the app's emails (sign-up, password reset). It was the user's to decide because it is a paid
service and sets how fast emails arrive.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| Amazon SES | the app calls AWS to send | cheapest per email | a domain review before the first email |
| Postmark | the app calls Postmark's API | delivery in seconds; templates in a web page | costs more at volume |

Costs:
- Amazon SES, money: $0.10 per 1,000 emails (AWS price list)
- Amazon SES, time: about a day for the domain review (user's figure)
- Postmark, money: $15/month for 10,000 emails (Postmark price list)

## Decision
Postmark. "I don't want reset emails to land in spam."

## Why
Password reset emails must arrive fast and reliably, and the volume is small, so the higher price per email costs
little.

## Consequences
The app needs a Postmark key in its settings.
```

- The first line is exactly `# NNN — <title>`: the three-digit number from the file name (`014`, not `14`), then an
  em dash (—).
- `Status` names who decided and what: `decided by the user (<option>, of <n> options)`, or `decided by the user
  (accepted the recommendation)`.
- Costs and savings: one line per option and kind (money, time, interruptions, quality, risk), never summed, each
  with its source; a figure the user gave is the "user's figure". Something not discussed is `not discussed`. Say
  plainly when an option's benefit is small.
- `## Consequences` is optional: only what the conversation said changes, or would make you revisit it. Leave the
  section out rather than guess.
