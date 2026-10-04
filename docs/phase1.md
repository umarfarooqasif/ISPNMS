# Phase 1: Database + Backend Foundation

## What exists

**Database (PostgreSQL 16, Alembic migrations `0001`, `0002`)**: 31 tables for users/roles/permissions,
customers, connections, packages (+aliases), areas/streets, billing accounts, ledger, invoices, payments,
allocations, receipts, collectors and assignments, import tracking, and audit logs.

- Money is `NUMERIC(12,2)`; a test asserts there are no float columns anywhere.
- `ledger_entries`, `audit_logs`, `invoices`, `invoice_lines`, `payment_allocations` are **append-only** (DB trigger).
  Payments/receipts/customers/connections/billing accounts **cannot be deleted**; a payment's money fields are immutable
  and a voided payment cannot be reinstated. These rules hold even for someone with direct SQL access through the app role.
- Only `customers.full_name` is required. CNIC is optional and encrypted at rest (Fernet; key rotation supported).
- Source IDs live in `external_refs` (unique per system/type/value), preserving Wasooli ID / Internet ID.

**API (`/api/v1`)**, all authorised server-side by permission:

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `/auth/refresh` (rotating, reuse detection), `/auth/logout`, `GET /auth/me` |
| Users | `GET/POST /users`, `PATCH /users/{id}`, `POST /users/{id}/password`, `GET /roles`, `/permissions` |
| Master data | `/areas`, `/streets`, `/packages` (+ aliases, archive) |
| Customers | `POST/GET /customers` (search by name, code, mobile, house no, Internet ID), `GET/PATCH /customers/{id}`, `/archive`, `/cnic` (audited) |
| Connections | `POST/GET /customers/{id}/connections`, `GET/PATCH /connections/{id}` |
| Billing | `POST /invoices`, `GET /invoices/{id}`, `GET /customers/{id}/statement`, `POST /payments` (idempotent via `client_txn_id`), `GET /payments`, `POST /payments/{id}/void`, `POST /adjustments`, `POST /refunds`, `GET /receipts/{number}` |
| Collectors | `POST/GET /collectors`, `PUT /collectors/{id}/areas`, `/customers`, `GET /collectors/me` |
| Audit / ops | `GET /audit-logs`, `/health`, `/ready` |

**Billing rules (server-side)**: balance = sum of the ledger (positive = owes). Payments allocate to the oldest due invoice
first; any remainder is an advance (credit). Invoice status is derived: `PAID`, `PARTIAL`, `DUE`, `OVERDUE`, `FREE`.
Voids post reversing entries. Refunds cannot exceed available credit. Amounts with more than 2 decimals are rejected.

**Roles** seeded: super_admin, admin, manager, accountant, collector, technician, noc, sales, dealer. Collectors only see
customers assigned to them (directly or by area), only take payments for those, and only see their own payments/receipts.

## Verified

79 automated tests pass (repeatably, including a concurrent duplicate-sync test): migrations up/down/up and model drift,
billing scenarios, DB-level immutability, permissions/scoping, auth (lockout, rotation, reuse detection), CNIC handling,
configuration validation. Backup/verify/restore/retention scripts were exercised against a real PostgreSQL, and the app was
smoke-tested under gunicorn.

## Not verified yet, please check on the VM

The sandbox this was built in has no Docker daemon, so these were **not run**: `docker compose up`, the Docker image build,
`install.sh` on a real VM, and Caddy HTTPS. Compose syntax and script syntax are validated. CI builds the image on GitHub.
On first install, if anything fails: `docker compose logs --tail=100 migrate api`.

## Known limitations (deliberate, for later phases)

- **Admin 2FA, rate limiting**: planned for Phase 15 (a `totp_secret_enc` column is reserved). Until then run behind the LAN or a VPN.
- **No Redis/worker/web containers yet**: they arrive with the importer (Phase 2) and dashboard (Phase 6).
- **Opening balances**: a positive `ADJUSTMENT` is ledger debt that is not tied to an invoice, so payments reduce the balance
  but are not "allocated" to it. Phase 3 should model arrears from the Wasooli import as invoices. `PaymentOut.unallocated`
  is therefore not always a true credit; use `balance`.
- **Receipt numbers** come from a database sequence, which can skip numbers if a transaction rolls back. Phase 4 introduces
  per-device number blocks for offline receipts.
- IDs are UUIDv4 (not v7). Devices, receipt series, sync batches and routes tables arrive in Phases 4/14.
- Audit logs capture who/what/when and before/after for changes; reads are only audited for CNIC reveal.
