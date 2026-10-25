#!/usr/bin/env bash
# A repo with accio set up, a design and one recorded decision: invoice data stays on our server.
set -euo pipefail
git init -q -b main .
mkdir -p .accio/decisions .accio/stories src
printf '{}\n' > .accio/config.json
printf '.accio/run/\n' > .gitignore
printf 'def overdue(rows):\n    return [row for row in rows if row["days_late"] > 0]\n' > src/invoices.py
cat > .accio/design.md <<'DESIGN'
# Design: overdue-invoice reminder

## Outcome
After this ships, no invoice stays overdue for more than a week without its account manager being told, and we'd
know because the weekly overdue report shows none older than 7 days without a reminder.

## What we build
1. **Read the export.** Each morning a cron job reads the invoice CSV export (src/invoices.py).
2. **Email reminders.** Each account manager gets one email listing their overdue invoices, through our SMTP
   server (src/mail.py).

## Decisions
- Decision 001: invoice data never leaves our server.
DESIGN
cat > .accio/decisions/001-invoice-data-stays-on-our-server.md <<'RECORD'
# 001 — Invoice data stays on our server

Date: 2026-10-01 · Status: decided by the user (a cron script on our server, of two options)

## What was decided
Where the reminder runs and where the invoice data goes. It was the user's to decide because the invoices hold
customer names and amounts.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| Cron script on our server | a Python script sends the emails | the data never leaves our server | we maintain it |
| Zapier | a hosted workflow reads the CSV | no code | the invoices pass through a third party |

Costs:
- Cron script, money: none (user's figure)
- Zapier, money: about $30/month (user's figure)

## Decision
A cron script on our server. "Invoice data must never leave our server."

## Why
The invoices hold customer names and amounts, and finance has promised customers they stay in-house.
RECORD
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "design and decision 001"
git config user.name eval
git config user.email eval@example.com
