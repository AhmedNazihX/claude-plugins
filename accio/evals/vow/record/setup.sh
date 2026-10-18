#!/usr/bin/env bash
set -euo pipefail
git init -q -b main .
mkdir -p .accio
printf '{}\n' > .accio/config.json
git add -A
git -c user.name=eval -c user.email=eval@example.com commit -q -m "accio set up"
git config user.name eval
git config user.email eval@example.com
