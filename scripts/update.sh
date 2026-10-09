#!/usr/bin/env bash
# Pull the latest code, take a safety backup, rebuild, migrate, restart, verify health.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"
load_env

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not a git checkout; cannot update"
[ -z "$(git status --porcelain --untracked-files=no)" ] || die "local changes present; commit or stash them first"

BEFORE="$(git rev-parse --short HEAD)"
echo "[update] current version: $BEFORE"
git fetch --quiet
git pull --ff-only
AFTER="$(git rev-parse --short HEAD)"
if [ "$BEFORE" = "$AFTER" ]; then
  echo "[update] already up to date ($AFTER); rebuilding anyway to pick up base-image updates"
fi

echo "[update] safety backup before changing anything"
"$ROOT/scripts/backup.sh"

mkdir -p storage
chown 10001:10001 storage 2>/dev/null || true   # uploads are written by the API container (uid 10001)

echo "[update] building and restarting (migrations run automatically)"
dc build
dc up -d

if wait_healthy 180; then
  echo "[update] OK: running $AFTER and healthy"
else
  echo "[update] FAILED: the api did not become healthy." >&2
  echo "  See logs:        docker compose logs --tail=100 migrate api" >&2
  echo "  Roll back code:  git checkout $BEFORE && docker compose up -d --build" >&2
  echo "  Roll back data:  scripts/restore.sh latest --apply   (needed only if a migration ran)" >&2
  exit 1
fi
