#!/bin/sh
set -eu
configured=$(git config --get core.hooksPath || true)
if [ "$configured" = .githooks ]; then exit 0; fi
if [ -n "$configured" ]; then
    echo "Existing hooksPath: $configured. Chain .githooks/pre-push from your pre-push hook." >&2
    exit 0
fi
for hook in "$(git rev-parse --git-path hooks)"/*; do
    case "$hook" in *.sample) continue ;; esac
    if [ -f "$hook" ] && [ -x "$hook" ]; then
        echo "Existing hook: $hook. Preserve it and chain .githooks/pre-push manually." >&2
        exit 0
    fi
done
git config --local core.hooksPath .githooks
