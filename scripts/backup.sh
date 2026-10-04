#!/usr/bin/env bash
# Encrypted backup of: PostgreSQL database, uploaded files, and the .env (keys needed for recovery).
# Output: backups/isp-YYYYMMDD-HHMMSS.tar.enc (+ .sha256)
# Retention: everything < 15 days, Sundays < 90 days, 1st of month < 400 days.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"
load_env
require_backup_passphrase

umask 077
mkdir -p backups storage
TS="$(date +%Y%m%d-%H%M%S)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "[backup] dumping database"
dc exec -T postgres pg_dump -U isp -Fc isp > "$TMP/db.dump"
[ -s "$TMP/db.dump" ] || die "database dump is empty"

echo "[backup] archiving uploaded files"
tar -czf "$TMP/storage.tgz" -C storage .

echo "[backup] including configuration (.env)"
cp .env "$TMP/env.backup"

OUT="backups/isp-$TS.tar.enc"
tar -C "$TMP" -cf - db.dump storage.tgz env.backup \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_PASSPHRASE -out "$OUT.partial"
mv "$OUT.partial" "$OUT"
( cd backups && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
echo "[backup] wrote $OUT ($(du -h "$OUT" | cut -f1))"

echo "[backup] applying retention"
now_s="$(date +%s)"
for f in backups/isp-*.tar.enc; do
  [ -e "$f" ] || continue
  d="$(basename "$f" | sed -E 's/^isp-([0-9]{8})-.*/\1/')"
  fs="$(date -d "$d" +%s 2>/dev/null)" || continue
  age=$(( (now_s - fs) / 86400 ))
  dow="$(date -d "$d" +%u)"
  dom="$(date -d "$d" +%d)"
  keep=0
  [ "$age" -le 14 ] && keep=1
  [ "$age" -le 90 ] && [ "$dow" = "7" ] && keep=1
  [ "$age" -le 400 ] && [ "$dom" = "01" ] && keep=1
  if [ "$keep" = "0" ]; then
    rm -f "$f" "$f.sha256"
    echo "[backup] pruned $f"
  fi
done
echo "[backup] done"
