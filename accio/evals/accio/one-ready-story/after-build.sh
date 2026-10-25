#!/usr/bin/env bash
# A repo just after a build: S-001 is the only story, built on branch story/S-001 and in review (READY in owl.md).
set -euo pipefail
git init -q -b main .
mkdir -p .accio/stories .accio/iterations .accio/run src
printf '{}\n' > .accio/config.json
printf '.accio/run/\n' > .gitignore
printf -- '---\nid: S-001\ntitle: Password reset email\ntrack: story\nstatus: ready\n---\n## Context\nA small web app.\n## Definition of Done\n- [ ] S-001/1 WHEN a user asks THE SYSTEM SHALL respond\n## Review notes\n## Blocked question\n' > .accio/stories/S-001.md
printf '# Iteration 1\n\n| Story | Title | Track | Stacked on |\n|---|---|---|---|\n| S-001 | Password reset email | story | - |\n\n## Outcome\n\nWritten by the owl review.\n' > .accio/iterations/1.md
printf 'def login():\n    return False\n' > src/auth.py
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "iteration 1 planned"
git config user.name eval
git config user.email eval@example.com
git checkout -q -b story/S-001
printf 'def reset():\n    return "sent"\n' > src/reset.py
git add -A
git commit -q -m "feat(S-001): reset email"
git checkout -q main
printf '{"S-001": "review"}\n' > .accio/run/status.json
mkdir -p .accio/run/S-001
printf '## What changed\nSends a reset link by email.\n## How to try it\nAsk for a reset.\n## Risks\nNone.\n' > .accio/run/S-001/build-report.md
