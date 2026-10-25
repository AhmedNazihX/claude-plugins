#!/usr/bin/env bash
# A small accio backlog with no `checks` in config.json: accio-board next says prophecy, and accio-board go refuses
# ("there are no checks to run"). Only S-001 and S-002, with no deps, so prophecy asks nothing before go when driven.
set -euo pipefail
git init -q -b main .
mkdir -p .accio/stories
printf '{}\n' > .accio/config.json
story() {  # id title
  printf -- '---\nid: %s\ntitle: %s\ntrack: story\nstatus: backlog\n---\n## Context\nA small web app.\n## Definition of Done\n- [ ] %s/1 WHEN a user %s THE SYSTEM SHALL respond within a second\n' \
    "$1" "$2" "$1" "$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')" > ".accio/stories/$1.md"
}
story S-001 "Password reset email"
story S-002 "Profile photo upload"
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "backlog"
