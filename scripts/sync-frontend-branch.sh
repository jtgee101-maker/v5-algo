#!/usr/bin/env bash
set -euo pipefail

# Sync repo's /frontend folder into a dedicated branch whose root is the frontend app.
# Usage:
#   scripts/sync-frontend-branch.sh [branch-name] [remote]
# Example:
#   scripts/sync-frontend-branch.sh frontend origin

BRANCH_NAME="${1:-frontend}"
REMOTE_NAME="${2:-origin}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: not inside a git repository" >&2
  exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "Current branch: ${CURRENT_BRANCH}"
echo "Creating subtree split from /frontend into branch: ${BRANCH_NAME}"

SPLIT_SHA="$(git subtree split --prefix frontend "${CURRENT_BRANCH}")"

git branch -f "${BRANCH_NAME}" "${SPLIT_SHA}"
echo "Updated local branch '${BRANCH_NAME}' to ${SPLIT_SHA}"

echo "Pushing to ${REMOTE_NAME}/${BRANCH_NAME} ..."
git push "${REMOTE_NAME}" "${BRANCH_NAME}:${BRANCH_NAME}" --force-with-lease

echo "Done. '${BRANCH_NAME}' now tracks frontend-only history rooted at /frontend."
