# ISP Billing & Collection System

Self-hosted billing and collection platform for an ISP, running alongside the existing
MikroTik and Zalpro systems (which it does **not** replace).

**Current status: Phases 1-4 complete, web dashboard stage 1 (login, customers, import) added.** Thermal
printing and the rest of the web dashboard are later phases. See [`docs/phase1.md`](docs/phase1.md), [`docs/phase2.md`](docs/phase2.md),
[`docs/phase3.md`](docs/phase3.md) (**read its "first bill run" section before billing**) and
[`docs/phase4.md`](docs/phase4.md) and [`docs/phase6.md`](docs/phase6.md) (web dashboard, stage 1) for exactly what exists and [`docs/architecture.md`](docs/architecture.md) for the overall design.

Load your customers: `cp Wasooli.pdf storage/ && docker compose exec api python -m app.import_cli /data/storage/Wasooli.pdf --commit` (preview first without `--commit`).

## Install on a fresh Ubuntu/Debian VM

```bash
git clone https://github.com/<you>/isp-billing-system.git
cd isp-billing-system
sudo ./install.sh                      # plain HTTP, good for a first test on the LAN
# production variants:
# sudo ./install.sh --domain billing.example.com     # automatic Let's Encrypt HTTPS
# sudo ./install.sh --lan-https 192.168.1.50         # HTTPS with a LAN-only certificate
```

The installer installs Docker if needed, generates all secrets into `.env`, builds and starts everything,
runs the database migrations, creates the first admin, and schedules encrypted backups.
At the end it prints the admin login. **Copy `.env` to a safe place off the server**: it holds the backup
passphrase and the CNIC encryption key.

## Everyday commands

| Task | Command |
|---|---|
| Status / logs | `docker compose ps` / `docker compose logs -f api` |
| Update to the latest code | `./scripts/update.sh` (backs up first, migrates, verifies health) |
| Back up now | `./scripts/backup.sh` |
| Test that the newest backup restores | `./scripts/restore.sh latest` |
| Restore for real (overwrites live data) | `./scripts/restore.sh <file\|latest> --apply` |
| Stop / start | `docker compose down` / `docker compose up -d` |

## Develop and test (no Docker needed, only PostgreSQL 16)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/isp_test   # needs a superuser DB
python -m pytest
```

Layout: `backend/` (FastAPI, SQLAlchemy, Alembic), `scripts/` (backup/restore/update),
`docs/`, `web/` and `mobile/` (placeholders for later phases), `storage/` (uploaded files, not in git).

Never commit real customer data (the Wasooli PDF, backups, `.env`): `.gitignore` already blocks them.
