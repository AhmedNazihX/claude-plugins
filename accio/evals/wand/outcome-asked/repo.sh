#!/usr/bin/env bash
# A git repo with one commit and an empty .accio/, so wand goes straight to the interview: with no .accio/ it asks
# before setting up (S-030), which wand/first-question checks.
set -euo pipefail
git init -q -b main .
printf '# invoices\n' > README.md
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "start"
git config user.name eval
git config user.email eval@example.com
mkdir .accio
