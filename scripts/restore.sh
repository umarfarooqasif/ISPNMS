#!/usr/bin/env bash
# Usage:
#   scripts/restore.sh <backup-file|latest>             verify only: restores into a scratch DB, checks it, drops it
#   scripts/restore.sh <backup-file|latest> --apply     OVERWRITE the live database and files (asks to confirm)
#   scripts/restore.sh <backup-file|latest> --env-only  print the .env stored in the backup (for a rebuilt server)
#
# A backup that has never been restored is not a backup: the default (verify) mode is run weekly by cron.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

SRC="${1:-}"
MODE="${2:-verify}"
[ -n "$SRC" ] || die "usage: restore.sh <backup-file|latest> [--apply|--env-only]"
if [ "$SRC" = "latest" ]; then
  SRC=""
  for f in backups/isp-*.tar.enc; do   # names carry a timestamp, so the last one is the newest
    if [ -e "$f" ]; then SRC="$f"; fi
  done
  [ -n "$SRC" ] || die "no backups found in $ROOT/backups"
fi
[ -f "$SRC" ] || die "backup file not found: $SRC"

# .env may be missing on a rebuilt server; allow BACKUP_PASSPHRASE from the environment then.
if [ -f .env ]; then load_env; fi
require_backup_passphrase

if [ -f "$SRC.sha256" ]; then
  ( cd "$(dirname "$SRC")" && sha256sum -c "$(basename "$SRC").sha256" >/dev/null ) \
    || die "checksum mismatch: the backup file is corrupted"
fi

umask 077
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
decrypt_to "$SRC" "$TMP/backup.tar" || die "could not decrypt (wrong BACKUP_PASSPHRASE?)"
tar -C "$TMP" -xf "$TMP/backup.tar"
for f in db.dump storage.tgz env.backup; do [ -s "$TMP/$f" ] || die "backup is missing $f"; done

if [ "$MODE" = "--env-only" ]; then
  cat "$TMP/env.backup"
  exit 0
fi

psql_admin() { dc exec -T postgres psql -U isp -d postgres -v ON_ERROR_STOP=1 "$@"; }

if [ "$MODE" = "verify" ]; then
  echo "[restore] verifying $SRC in a scratch database (live data is untouched)"
  psql_admin -c "DROP DATABASE IF EXISTS isp_restore_test WITH (FORCE)" >/dev/null
  psql_admin -c "CREATE DATABASE isp_restore_test" >/dev/null
  # cleanup() is called through the EXIT trap below, which shellcheck cannot see.
  # shellcheck disable=SC2317
  cleanup() { psql_admin -c "DROP DATABASE IF EXISTS isp_restore_test WITH (FORCE)" >/dev/null 2>&1 || true; }
  trap 'cleanup; rm -rf "$TMP"' EXIT
  dc exec -T postgres pg_restore -U isp -d isp_restore_test --no-owner --exit-on-error < "$TMP/db.dump"
  q() { dc exec -T postgres psql -U isp -d isp_restore_test -tA -v ON_ERROR_STOP=1 -c "$1" | tr -d '[:space:]'; }
  tables="$(q "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
  rev="$(q "SELECT version_num FROM alembic_version")"
  q "SELECT coalesce(sum(amount),0) FROM ledger_entries" >/dev/null
  q "SELECT count(*) FROM users" >/dev/null
  [ "$tables" -ge 30 ] || die "restored database looks incomplete ($tables tables)"
  tar -tzf "$TMP/storage.tgz" >/dev/null || die "storage archive is corrupt"
  echo "[restore] VERIFIED: $tables tables, schema revision $rev, ledger readable, files archive intact"
  exit 0
fi

[ "$MODE" = "--apply" ] || die "unknown option: $MODE"
echo "This will OVERWRITE the live database and uploaded files with the contents of:"
echo "  $SRC"
read -r -p "Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || die "aborted"

echo "[restore] taking a safety backup of the current state first"
"$ROOT/scripts/backup.sh" || echo "[restore] WARNING: safety backup failed (continuing as requested)"

echo "[restore] stopping application services"
dc stop caddy api >/dev/null 2>&1 || true
psql_admin -c "DROP DATABASE IF EXISTS isp WITH (FORCE)" >/dev/null
psql_admin -c "CREATE DATABASE isp OWNER isp" >/dev/null
dc exec -T postgres pg_restore -U isp -d isp --no-owner --exit-on-error < "$TMP/db.dump"

echo "[restore] restoring uploaded files"
if [ -d storage ] && [ -n "$(find storage -mindepth 1 ! -name .gitkeep -print -quit 2>/dev/null)" ]; then
  mv storage "storage.pre-restore.$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p storage
tar -xzf "$TMP/storage.tgz" -C storage
chown -R 10001:10001 storage 2>/dev/null || true   # the API container runs as uid 10001

echo "[restore] starting services"
dc up -d
echo "[restore] done. Check the application, then remove any storage.pre-restore.* folder when satisfied."
