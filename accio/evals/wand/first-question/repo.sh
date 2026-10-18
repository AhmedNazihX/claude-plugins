#!/usr/bin/env bash
# An empty project: a git repo with one commit and no .accio/ yet.
set -euo pipefail
git init -q -b main .
printf '# invoices\n' > README.md
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "start"
git config user.name eval
git config user.email eval@example.com
