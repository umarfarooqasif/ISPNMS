# Deployment

```text
Proxmox host -> Ubuntu Server VM (4 vCPU, 8 GB RAM, 100 GB disk is ample)
  └─ Docker Compose: caddy (80/443) -> api (gunicorn/FastAPI) -> postgres
                      migrate (one-shot: alembic upgrade + seed)
```

Postgres and the API are not published on the host; only Caddy listens (80/443).

## First install

1. Create the VM, install Ubuntu Server, take a Proxmox snapshot.
2. `git clone <repo> && cd isp-billing-system && sudo ./install.sh [--domain X | --lan-https IP]`
3. Open the printed address, log in with the printed admin credentials, change the password.
4. Copy `.env` off the server (password manager / USB). Without `BACKUP_PASSPHRASE` and `FIELD_ENCRYPTION_KEYS`
   backups cannot be restored and CNIC data cannot be read.

## HTTPS

| Situation | Option |
|---|---|
| Public domain pointing at the VM, ports 80/443 open | `--domain billing.example.com` (Let's Encrypt, automatic) |
| LAN only | `--lan-https <ip>` (Caddy internal CA; browsers/phones must trust Caddy's root certificate once) |
| Quick test | default `:80` plain HTTP. Do not use with real data over untrusted networks. |

You can change `SITE_ADDRESS`/`CADDY_TLS` in `.env` later and run `docker compose up -d`.

## Backups and restore

- Daily 02:30 `backup.sh` (cron): database dump + uploaded files + `.env`, **always encrypted** (AES-256, passphrase from `.env`),
  with a checksum. Retention: all for 14 days, Sundays for 90 days, first-of-month for 400 days. Files are in `backups/`.
- Weekly (Sunday 04:00) cron runs `restore.sh latest`: restores the newest backup into a scratch database, checks it, and drops it.
  Look at `/var/log/isp-billing-backup.log` for `VERIFIED`. A backup that has never been restored is not a backup.
- Also copy `backups/` off the VM (another machine, Proxmox Backup Server, or cloud storage). Same-disk backups die with the disk.
- Disaster recovery on a new VM: clone the repo, put the saved `.env` in place, `docker compose up -d postgres`,
  then `./scripts/restore.sh <file> --apply`.

## Updates

`./scripts/update.sh`: refuses if local changes exist, pulls, takes a safety backup, rebuilds, migrates, and verifies the health check.
Take a Proxmox snapshot before major updates. On failure it prints how to roll back code and data.

## Operations

```bash
docker compose ps
docker compose logs -f api
curl -s http://localhost/health ; curl -s http://localhost/ready
```
