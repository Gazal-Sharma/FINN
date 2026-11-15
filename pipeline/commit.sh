#!/usr/bin/env bash
# Commit whatever the pipeline produced so far. Safe to call more than once.
set -u
git config user.name "finn-bot"
git config user.email "finn-bot@users.noreply.github.com"
for p in raw public/data cache logs; do if [ -e "$p" ]; then git add "$p"; fi; done
if git diff --cached --quiet; then echo "no changes"; exit 0; fi
git commit -q -m "data: ${1:-pipeline} $(date -u +%Y-%m-%dT%H:%MZ)"
for i in 1 2 3; do git pull -q --rebase -X theirs && git push -q && echo "pushed" && exit 0; sleep 5; done
echo "push failed"; exit 1
