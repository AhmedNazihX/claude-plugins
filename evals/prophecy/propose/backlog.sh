#!/usr/bin/env bash
# A small accio backlog for the prophecy evals: S-002 stacks on S-001, S-003 is dropped, S-004 depends on S-003.
set -euo pipefail
git init -q -b main .
mkdir -p .accio/stories
printf '{}\n' > .accio/config.json
story() {  # id title status deps [extra]
  printf -- '---\nid: %s\ntitle: %s\ntrack: story\nstatus: %s\n%s%s---\n## Context\nA small web app.\n## Definition of Done\n- [ ] %s/1 WHEN a user %s THE SYSTEM SHALL respond within a second\n' \
    "$1" "$2" "$3" "${4:+deps: [$4]
}" "${5:-}" "$1" "$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')" > ".accio/stories/$1.md"
}
story S-001 "Password reset email" backlog ""
story S-002 "Reset token expiry" backlog "S-001"
story S-003 "SMS login codes" dropped "" "dropped: we use the identity provider instead
"
story S-004 "Rate-limit SMS codes" backlog "S-003"
story S-005 "Profile photo upload" backlog ""
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "backlog"
