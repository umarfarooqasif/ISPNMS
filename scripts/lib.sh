#!/usr/bin/env bash
# Shared helpers. Sourced by the other scripts; not meant to be run directly.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

dc() { docker compose "$@"; }

die() { echo "ERROR: $*" >&2; exit 1; }

load_env() {
  [ -f .env ] || die ".env not found in $ROOT (run ./install.sh first)"
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
}

require_backup_passphrase() {
  [ -n "${BACKUP_PASSPHRASE:-}" ] || die "BACKUP_PASSPHRASE is empty in .env; backups must be encrypted"
  [ "$BACKUP_PASSPHRASE" != "change-me" ] || die "BACKUP_PASSPHRASE is still the example value"
}

# Waits until the api container reports healthy (migrations done, database reachable).
wait_healthy() {
  local timeout="${1:-180}" waited=0 cid status
  while [ "$waited" -lt "$timeout" ]; do
    cid="$(dc ps -q api 2>/dev/null || true)"
    if [ -n "$cid" ]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || true)"
      [ "$status" = "healthy" ] && return 0
    fi
    sleep 3
    waited=$((waited + 3))
  done
  return 1
}

decrypt_to() { # <encrypted-file> <output-tar>
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$1" -out "$2"
}
