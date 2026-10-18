#!/usr/bin/env bash
# A design with one part far too big for one story (11 files), so the score flags it and quill splits it.
set -euo pipefail
git init -q -b main .
mkdir -p .accio
printf '{}\n' > .accio/config.json
printf '.accio/run/\n' > .gitignore
cat > .accio/design.md <<'DESIGN'
# Design: admin dashboard

## Outcome
After this ships, an admin sees signups, active users and errors on one page and can act on them, and we'd know
because the admin team stops asking engineers for weekly numbers.

## What we build
1. **Dashboard.** One admin page with a signups chart, an active-users chart, an error list with filters, CSV
   export, and a refresh button. Files: src/admin/page.py, src/admin/signups.py, src/admin/active.py,
   src/admin/errors.py, src/admin/filters.py, src/admin/export.py, src/admin/refresh.py, src/admin/charts.py,
   src/admin/queries.py, src/admin/templates.py, src/admin/routes.py.

## Decisions
- An admin is a user with `is_admin` set; anyone else gets a 403 and no data, from one shared check every admin
  route uses.
- An active user signed in within the last 7 days. The error list filters by level and by date range.
- CSV columns: signups `date,signups`; active users `date,active_users`; errors `time,level,message`, newest first.
DESIGN
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "design"
git config user.name eval
git config user.email eval@example.com
