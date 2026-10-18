#!/bin/sh
# Point git at the hooks in scripts/hooks (pre-commit, commit-msg and pre-push).
# Run once per clone, from anywhere: sh scripts/install-hooks.sh
set -eu
cd "$(dirname "$0")/.."
git config core.hooksPath scripts/hooks
chmod +x scripts/hooks/pre-commit scripts/hooks/commit-msg scripts/hooks/pre-push
echo "hooks installed: core.hooksPath is scripts/hooks"
