#!/usr/bin/env bash
# A small accio backlog with no `checks` in config.json: accio-board next says prophecy, and accio-board go refuses
# ("there are no checks to run"). Only S-001 and S-002, with no deps, so prophecy asks nothing before go when driven.
set -euo pipefail
git init -q -b main .
mkdir -p .accio/stories
printf '{}\n' > .accio/config.json
story() {  # id title dod (a clear DoD line, so prophecy has nothing to ask)
  printf -- '---\nid: %s\ntitle: %s\ntrack: story\nstatus: backlog\n---\n## Context\nA small web app.\n## Definition of Done\n- [ ] %s/1 %s\n' \
    "$1" "$2" "$1" "$3" > ".accio/stories/$1.md"
}
story S-001 "Password reset email" "WHEN a user asks for a password reset THE SYSTEM SHALL email them a link that works once"
story S-002 "Profile photo upload" "WHEN a user uploads a JPEG or PNG under 5 MB THE SYSTEM SHALL show it as their profile photo"
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "backlog"
