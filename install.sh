#!/usr/bin/env bash
# One-command installer for a fresh Ubuntu/Debian VM.
#
#   git clone <your-repo> isp-billing-system && cd isp-billing-system && sudo ./install.sh
#
# Options:
#   --domain billing.example.com   public domain: automatic Let's Encrypt HTTPS
#   --lan-https [IP]               HTTPS on the LAN with a self-signed (Caddy internal CA) certificate
#   --no-cron                      do not install the daily backup / weekly restore-check cron jobs
#
# Safe to re-run: existing .env secrets are kept; the stack is just rebuilt and restarted.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

DOMAIN=""; LAN_HTTPS=0; LAN_IP=""; CRON=1
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:?--domain needs a value}"; shift 2 ;;
    --lan-https) LAN_HTTPS=1; if [ -n "${2:-}" ] && [[ "${2:-}" != --* ]]; then LAN_IP="$2"; shift; fi; shift ;;
    --no-cron) CRON=0; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

[ "$(id -u)" = "0" ] || exec sudo -E bash "$0" "$@"

say() { printf '\n==> %s\n' "$*"; }

say "Checking prerequisites"
if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer supports Debian/Ubuntu (apt). Install Docker manually, then run: docker compose up -d --build" >&2
  exit 1
fi
need=()
for bin in curl openssl git; do command -v "$bin" >/dev/null 2>&1 || need+=("$bin"); done
if [ "${#need[@]}" -gt 0 ]; then
  apt-get update -y && apt-get install -y --no-install-recommends ca-certificates "${need[@]}"
fi

if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker compose version >/dev/null 2>&1 || { echo "Docker Compose plugin missing; install docker-compose-plugin" >&2; exit 1; }

# --- .env ---------------------------------------------------------------------------------
set_env() { # KEY VALUE  (replace the KEY= line, or append)
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$val" 'BEGIN{done=0} $0 ~ "^"k"=" {print k"="v; done=1; next} {print} END{if(!done) print k"="v}' .env > "$tmp"
  cat "$tmp" > .env; rm -f "$tmp"
}
get_env() { grep -E "^$1=" .env | head -n1 | cut -d= -f2-; }

FIRST_RUN=0
if [ ! -f .env ]; then
  say "Creating .env with freshly generated secrets"
  FIRST_RUN=1
  cp .env.example .env
  chmod 600 .env
  set_env POSTGRES_PASSWORD "$(openssl rand -hex 24)"
  set_env SECRET_KEY "$(openssl rand -hex 48)"
  set_env FIELD_ENCRYPTION_KEYS "$(openssl rand -base64 32 | tr '+/' '-_')"
  set_env BACKUP_PASSPHRASE "$(openssl rand -hex 24)"
  set_env BOOTSTRAP_ADMIN_PASSWORD "$(openssl rand -hex 10)"
else
  chmod 600 .env
  echo ".env already exists; keeping its secrets"
fi

if [ -n "$DOMAIN" ]; then
  set_env SITE_ADDRESS "$DOMAIN"; set_env CADDY_TLS ""
elif [ "$LAN_HTTPS" = "1" ]; then
  [ -n "$LAN_IP" ] || LAN_IP="$(hostname -I | awk '{print $1}')"
  set_env SITE_ADDRESS "https://$LAN_IP"; set_env CADDY_TLS "tls internal"
fi

mkdir -p storage backups
chmod 700 backups

# --- start the stack ------------------------------------------------------------------------
say "Building and starting the stack (first build takes a few minutes)"
docker compose up -d --build

# shellcheck source=scripts/lib.sh
. scripts/lib.sh
say "Waiting for the API to become healthy"
if ! wait_healthy 240; then
  echo "The API did not become healthy. Logs:" >&2
  docker compose logs --tail=60 migrate api >&2 || true
  exit 1
fi

# --- cron -----------------------------------------------------------------------------------
if [ "$CRON" = "1" ] && [ -d /etc/cron.d ]; then
  say "Installing backup schedule (daily backup 02:30, weekly restore check Sun 04:00)"
  cat > /etc/cron.d/isp-billing <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
30 2 * * * root cd $ROOT && ./scripts/backup.sh >> /var/log/isp-billing-backup.log 2>&1
0 4 * * 0 root cd $ROOT && ./scripts/restore.sh latest >> /var/log/isp-billing-backup.log 2>&1
EOF
  chmod 644 /etc/cron.d/isp-billing
fi

# --- summary --------------------------------------------------------------------------------
SITE="$(get_env SITE_ADDRESS)"
case "$SITE" in
  :80|"") URL="http://$(hostname -I | awk '{print $1}')" ;;
  https://*|http://*) URL="$SITE" ;;
  *) URL="https://$SITE" ;;
esac

say "Installed"
echo "  API address : $URL/api/v1   (health: $URL/health)"
ADMIN_PW="$(get_env BOOTSTRAP_ADMIN_PASSWORD)"
if [ -n "$ADMIN_PW" ]; then
  echo "  Admin login : $(get_env BOOTSTRAP_ADMIN_USERNAME) / $ADMIN_PW"
  echo "                (change it after first login, then delete BOOTSTRAP_ADMIN_PASSWORD from .env)"
fi
if [ "$FIRST_RUN" = "1" ]; then
  cat <<EOF

  IMPORTANT: copy this file to a safe place OFF this server:  $ROOT/.env
  It holds the backup passphrase and the encryption key for CNIC data. Without them,
  backups cannot be restored and encrypted fields cannot be read.

EOF
fi
case "$SITE" in
  :80|"") echo "  NOTE: running plain HTTP. For production use --domain <name> or --lan-https." ;;
esac
echo "  Useful: docker compose ps | docker compose logs -f api | ./scripts/backup.sh | ./scripts/update.sh"
