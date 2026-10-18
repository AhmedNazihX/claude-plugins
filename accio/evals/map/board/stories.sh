#!/usr/bin/env bash
# A backlog in mid-flight: one story done, one ready to build, one in the backlog.
set -euo pipefail
git init -q -b main .
mkdir -p .accio/stories
printf '{}\n' > .accio/config.json
story() {  # id title status
  printf -- '---\nid: %s\ntitle: %s\ntrack: story\nstatus: %s\n---\n## Context\nWhy.\n## Definition of Done\n- [ ] %s/1 WHEN a user asks THE SYSTEM SHALL respond\n' "$1" "$2" "$3" "$1" > ".accio/stories/$1.md"
}
story S-001 "Password reset email" done
story S-002 "Reset link expiry" ready
story S-003 "Rate-limit the reset form" backlog
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "backlog"
