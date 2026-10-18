# Decision record format

Every record has these parts, in this order. `accio-vow record` refuses a record without the four `##` sections.
Take every word from the conversation: the example below shows the shape only, never its content.

```markdown
# 014 — Postmark for transactional email

Date: 2026-10-18 · Status: decided by the user (option B of two)

## What was decided
Which service sends the app's emails (sign-up, password reset). It was the user's to decide because it is a paid
service and sets how fast emails arrive.

## Options
| Option | What it looks like | Pros | Cons | Cost |
|---|---|---|---|---|
| Amazon SES | the app calls AWS to send | cheapest per email | setup takes a domain review of about a day | $0.10 per 1,000 emails (AWS price list) |
| Postmark | the app calls Postmark's API | delivery in seconds; templates in a web page | costs more at volume | $15/month for 10,000 emails (Postmark price list) |

## Decision
Postmark. "I don't want reset emails to land in spam."

## Why
Password reset emails must arrive fast and reliably, and the volume is small, so the higher price per email costs
little.

## Consequences
The app needs a Postmark key in its settings.
```

- The number in the heading matches the file name (`014-postmark-for-transactional-email.md`).
- `Status` names who decided: `decided by the user`, or `decided by the user (option B of two)`.
- Costs: one kind per cell (money, time, risk), never summed, each with its source when you have one; when the
  user gave the figure, the source is "user's figure". Say plainly when an option's benefit is small.
- `## Consequences` is optional: only what the conversation said changes, or would make you revisit it. Leave the
  section out rather than guess.
