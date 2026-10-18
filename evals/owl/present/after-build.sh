#!/usr/bin/env bash
# A repo just after a build: S-001 and S-002 (stacked on S-001) in review, S-003 blocked with a question, S-004 in
# review. The statuses live in run/status.json, as during a build; owl folds them into the story files.
set -euo pipefail
git init -q -b main .
mkdir -p .accio/stories .accio/iterations .accio/run/questions
printf '{}\n' > .accio/config.json
printf '.accio/run/\n' > .gitignore
story() {  # id title deps
  printf -- '---\nid: %s\ntitle: %s\ntrack: story\nstatus: ready\n%s---\n## Context\nA small web app.\n## Definition of Done\n- [ ] %s/1 WHEN a user asks THE SYSTEM SHALL respond\n## Review notes\n## Blocked question\n' \
    "$1" "$2" "${3:+deps: [$3]
}" "$1" > ".accio/stories/$1.md"
}
report() {  # id changed try risks
  mkdir -p ".accio/run/$1"
  printf '## What changed\n%s\n## How to try it\n%s\n## Risks\n%s\n' "$2" "$3" "$4" > ".accio/run/$1/report.md"
}
story S-001 "Password reset email" ""
story S-002 "Reset token expiry" "S-001"
story S-003 "Rate-limit the reset form" ""
story S-004 "Profile photo upload" ""
printf '# Iteration 1\n\n| Story | Title | Track | Stacked on |\n|---|---|---|---|\n| S-001 | Password reset email | story | — |\n\n## Outcome\n\nWritten by `/accio:owl`.\n' > .accio/iterations/1.md
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "iteration 1 planned"
git config user.name eval
git config user.email eval@example.com
printf '{"S-001": "review", "S-002": "review", "S-003": "blocked", "S-004": "review"}\n' > .accio/run/status.json
printf 'Should the reset form allow 5 tries per hour, or 10?\n' > .accio/run/questions/S-003.md
report S-001 "Sends a reset link by email." "Ask for a reset on the login page." "The email text is plain."
report S-002 "Reset links expire after 30 minutes." "Wait 31 minutes, then use a link." "None."
report S-004 "Users can upload a profile photo." "Upload a photo on the profile page." "Large photos are not resized."
