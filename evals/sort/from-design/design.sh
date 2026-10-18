#!/usr/bin/env bash
# A repo with accio set up and a small design: no stories yet.
set -euo pipefail
git init -q -b main .
mkdir -p .accio src
printf '{}\n' > .accio/config.json
printf '.accio/run/\n' > .gitignore
printf 'def login(user, password):\n    return False\n' > src/auth.py
cat > .accio/design.md <<'DESIGN'
# Design: password reset

## Outcome
After this ships, a user who forgot their password gets back into their account in under 5 minutes, and we'd
know because support tickets about lost passwords drop.

## What we build
1. **Reset email.** On the login page a user asks for a reset; we email a single-use link (src/reset.py,
   src/mail.py).
2. **Link expiry.** A reset link works once and only for 30 minutes (src/reset.py).
3. **Rate limit.** At most 5 reset requests per email address per hour (src/ratelimit.py).

## Decisions
- Email only, no SMS.
DESIGN
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "design"
git config user.name eval
git config user.email eval@example.com
