#!/usr/bin/env bash
# A repo with accio set up, a design over 40 KB (the long-document guard's limit) whose old parts already have
# stories, and one new note heading listed in run/unsorted.json.
set -euo pipefail
git init -q -b main .
mkdir -p .accio/stories .accio/run src
printf '{}\n' > .accio/config.json
printf '.accio/run/\n' > .gitignore
printf 'def login(user, password):\n    return False\n' > src/auth.py
{
  printf '# Design: accounts\n\n## Outcome\nAfter this ships, accounts work end to end.\n\n'
  for n in $(seq 1 40); do
    printf '## Part %s\n\n' "$n"
    for line in $(seq 1 12); do
      printf 'Part %s, point %s: the account service keeps this rule in src/part%s.py and checks it on every request, so a support agent can see why it applied.\n\n' "$n" "$line" "$n"
    done
  done
  printf '## Note: audit log\n\n### Outcome\nAfter this ships, every login is written to an audit log (src/audit.py), and we would know because a test reads the log after a login.\n\n'
  printf '### What we build\n1. **Audit entry.** Each login adds one line with the user and the time (src/audit.py, src/auth.py).\n'
} > .accio/design.md
for n in 1 2 3; do
  printf -- '---\nid: S-00%s\ntitle: Part %s\ntype: feat\ntrack: quick\nstatus: done\ndeps: []\nfiles: [src/part%s.py]\n---\n## Context\nAfter this ships: part %s works.\n## Definition of Done\n- [ ] S-00%s/1 WHEN a request comes THE SYSTEM SHALL apply part %s\n' "$n" "$n" "$n" "$n" "$n" "$n" > ".accio/stories/S-00$n.md"
done
printf '["## Note: audit log"]\n' > .accio/run/unsorted.json
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "design"
git config user.name eval
git config user.email eval@example.com
