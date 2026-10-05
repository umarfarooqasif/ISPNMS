# Phase 3: billing engine

Monthly billing, late fees, optional opening balances, billing-aware connection status, and the
reports a collector or manager needs. Everything is also available over the API (see `/api/docs`
if `ENABLE_DOCS=true`); screens come in a later phase.

## How billing works

* Billing is **prepaid, one cycle per month per connection**. A connection with next due date `D`
  is invoiced for `D` to one month later; the invoice is due on `D` (or on the run date if `D` has
  already passed). After invoicing, the due date moves one month forward.
* A bill run invoices every **ACTIVE** connection whose due date is within `BILLING_LEAD_DAYS`
  (default 5) of the run date. **FREE / TRIAL** connections are rolled forward and never charged.
  **SUSPENDED / DISCONNECTED** and archived customers are never billed.
* A customer with several connections due on the same date gets **one invoice** with a line per
  service (cable and internet stay separate lines).
* Price per connection: the special price (`monthly_price_override`) if set, otherwise each service
  line's own price, falling back to the package's list price. **A connection with no usable price is
  never billed as zero**: it is reported and left due until you fix it.
* **Advance payments** now settle new invoices automatically (capped by what the ledger says the
  customer really has, so a refunded advance is never counted twice).

## Safety guarantees

| Guarantee | How |
|---|---|
| Preview writes nothing | `POST /billing/runs/preview` is read-only |
| A real run needs an explicit `"confirm": true` | otherwise 422 |
| A cycle is never invoiced twice | partial unique index in the database; running twice creates nothing |
| Two runs can't overlap | database advisory lock |
| One bad customer doesn't stop the run | per-customer savepoint; recorded as an `ERROR` item |
| Nothing is silent | skipped cycles, unpriced and date-less connections are reported per run |
| Nothing is suspended automatically | the suspension list is read-only |
| Every run, late-fee run, opening-balance load and status change is audited | audit log |

## The first bill run: read this

Your export has **no due dates in the future** and 320 active customers with dates over a year old.
Two consequences:

1. **What does "Recharge Date" mean?** If it is the date a customer *last paid*, set
   `RECHARGE_DATE_MEANS=LAST_RECHARGE` in `.env` **before importing**. If you already imported, run
   `python -m app.rebase_due_dates_cli` (preview) then `--commit` once, before the first bill run.
   Spot-check two or three customers you know before deciding: pick someone who paid recently and see
   whether their date is the day they paid or the day they are next due.
2. **Backlog.** Customers whose date is months or years old would otherwise be billed a month at a
   time on every run. Choose how to handle it on the first run:
   * `max_cycles: 1, skip_remaining: true` bills one month and jumps to the current cycle, listing
     every skipped month in the run report. **Recommended for the first run.**
   * `max_cycles: N` bills up to N missed months at once.
   * Default (`max_cycles: 1`) bills one month per run and reports who is still behind.
   Dormant customers (very old dates, still ACTIVE) are probably candidates to **disconnect** rather
   than bill; use `GET /billing/suspension-candidates`.

Checklist:
1. Decide what Recharge Date means (above) and set `RECHARGE_DATE_MEANS` / rebase.
2. Set packages' prices and fix the ~26 active connections with a zero price (the preview lists them).
3. `POST /billing/runs/preview`: read the counts and the `ZERO_PRICE` / `NO_DUE_DATE` items.
4. Optionally load opening balances (below).
5. `POST /billing/runs` with `"confirm": true`. Check `GET /billing/runs/{id}/items?outcome=ERROR`.

## Endpoints

| | Permission |
|---|---|
| `POST /billing/runs/preview`, `POST /billing/runs` | `billing.run` |
| `GET /billing/runs`, `/billing/runs/{id}`, `/billing/runs/{id}/items?outcome=` | `invoice.view` |
| `POST /billing/late-fees/preview`, `POST /billing/late-fees` | `billing.run` |
| `POST /billing/opening-balances` (dry run by default) | `billing.opening_balance` |
| `POST /connections/{id}/status` (suspend / disconnect / reactivate, optional reconnection fee) | `connection.status` |
| `GET /billing/outstanding`, `GET /billing/suspension-candidates` | `invoice.view` |
| `GET /customers/{id}/statement` now includes `billing_status` | existing |

Bill-run body: `run_date` (default today), `lead_days`, `max_cycles` (1-12), `skip_remaining`.
Admins and accountants get `billing.run` automatically; only admins get `connection.status`.

## Late fees (off by default)

Set `LATE_FEE_AMOUNT` (flat, per overdue invoice) in `.env`, or pass `amount` in the request. A fee is
charged once per invoice, as a separate fee invoice, only after `LATE_FEE_GRACE_DAYS` past the due
date. Never charged on: late-fee invoices, imported opening balances, or customers whose connections
are all disconnected. Always preview first.

## Opening balances (optional)

The PDF has no balances, so everyone starts at zero. To carry old dues over:
`POST /billing/opening-balances` with rows of `{wasooli_id | customer_id, amount, note}` (preview is the
default), or from a CSV (`wasooli_id,amount[,note]`):
`python -m app.opening_balances_cli dues.csv` (preview) then `--commit`. Each becomes a normal invoice
that payments settle; one per customer, loading twice is refused. Amounts owed only (no credits).

## Reconnecting

`POST /connections/{id}/status` with `{"status":"ACTIVE","reason":"...","reconnection_fee":"500.00"}`
reactivates a suspended/disconnected connection, restarts billing at `next_due_date` (default today)
and charges the fee as a normal invoice. The importer never re-activates a disconnected connection.

## Upgrade notes

* Migration `0004` adds `connections.next_due_date` (back-filled from the imported recharge date),
  widens `billing_day` to 1-31, and adds `billing_runs`, `billing_run_items`, `late_fees`,
  `opening_balances`. It is reversible.
* Re-importing a changed export never moves the due date of a connection already in the system.
* Existing roles receive only the *new* permissions by default; grants an admin removed earlier are
  not put back.
