# Phase 6: admin web dashboard (stages 1 to 3)

A browser interface for the office, served by the `web` container (Next.js) behind Caddy at the same
address as the API. Stage 1: login, dashboard, customers, Wasooli import. Stage 2 (below): billing,
payments and receipts. Stage 3 (below): customers (create, edit, archive), connections and their status, users, collectors and the
audit log.

## What you can do now

* **Log in** with your existing username and password. The menu shows only what your role may use.
* **Dashboard:** biggest balances owed, the last billing run, the latest import.
* **Customers:** search by name, customer ID, mobile, house number or Internet ID; open a customer to see
  details, connections (with next due date) and unpaid bills.
* **Import customers (Wasooli PDF):**
  1. Upload the PDF. It is read and checked in the background (about half a minute).
  2. Read the summary and "things worth a look" (missing mobiles, guessed areas, zero prices...). Click
     one to list only those rows.
  3. Open the **Needs your decision** tab: for each possible duplicate choose *Import as new*,
     *Attach to <existing customer>*, or *Skip*; or decide all at once.
  4. **Preview** the import (changes nothing), tick the option for undecided duplicates if you want them,
     then **Import now** and confirm.

## Stage 2: billing and payments

* **Record a payment** on any customer's page (office cash, bank, JazzCash, Easypaisa, card, QR). You are
  asked to confirm the amount and customer first. It settles the oldest unpaid bill first; any extra is
  kept as advance credit, and later bills use that credit automatically.
* **Payments** lists every payment with filters (recorded or cancelled, date range). Open one to see its
  receipt; users with the right permission can **cancel** a payment (a reason is required, it is audited,
  and the customer's bills become unpaid again).
* **Bill run:** settings, then **Preview**, which changes nothing and lists every customer and what would
  happen, with problems first (no price, no due date, failures). The create button stays disabled until
  you have previewed the *current* settings and ticked the box, then asks you to confirm. For your first
  run choose 1 month and tick *leave out older months*; see `docs/phase3.md`.
* **Billing history:** every run with its full record, filterable by what happened.
* **Who owes money:** balances by area and minimum amount, plus a **long overdue** list. It never suspends
  anyone automatically.
* **Late fees:** off until a fee is set; preview, then charge. Once per bill, never on fees.
* **Opening balances (optional):** paste `wasooli_id,amount,note` lines, check, then load. Bad lines are
  reported with their line number and left out.

Safeguards on every action that changes money: it needs a preview of the exact current settings,
an explicit tick and a confirmation; the server independently refuses a real run without
`"confirm": true`; double clicks are blocked while a request is running.

## Stage 3: customers, people and the record

* **Customers:** *New customer* (only the name is required), *Edit details* (saving sends only what you
  changed, so editing never erases the stored CNIC, which is never shown in the form), *Archive*.
* **Connections:** *Add connection* (internet, cable or both, package and/or price, next due date; the
  screen warns that a connection with no due date is not billed). *Change status* on each connection:
  suspend, disconnect, reactivate, free or trial, always with a reason; reactivating can add a
  reconnection fee and set the date billing resumes. Suspended or disconnected connections are never billed.
* **Users:** add people, set roles, disable accounts, reset passwords. Only a super admin can grant the
  super-admin role, and you cannot disable your own account.
* **Collectors:** add a collector (a user with the Collector role plus a code such as C01), deactivate or
  reactivate them (a deactivated collector's phone is locked out at its next sync), and choose which
  **areas** and **individual customers** they see, with a visiting order.
* **Audit log:** who did what and when, filterable by action and person, with details. Passwords, tokens
  and CNIC numbers are never displayed.

Backend additions for this stage: the collector list now carries names; `GET /collectors/{id}/assignments`
reads current assignments; `PATCH /collectors/{id}` activates or deactivates.

## How login is kept safe

The browser never holds an API token. Login sets two cookies the page's JavaScript cannot read
(`httpOnly`, `SameSite=Strict`, `Secure` on HTTPS); the web server attaches the token when it forwards
each request to the API. Changing requests also need a custom header, and request paths are checked, so
a malicious website or a script injected into a page cannot act as you. Several requests expiring at the
same moment share one token refresh, and a brief network problem never logs you out. The API still
checks your permissions on every call; hiding a menu item is only a convenience.

## Deploying it

`web` is a normal service in `docker-compose.yml`; `./scripts/update.sh` builds and starts it. Caddy
sends `/api`, `/health` and `/ready` to the API and everything else to `web`, and does **not** wait for
`web`, so a problem with the web container cannot take the API or the collector app offline.

After updating, check: `docker compose ps` (web should be *healthy*) then open your address.

* The first build downloads packages and needs roughly **1.5 GB of RAM**. If the container has less, the
  build may be killed ("Killed" / exit 137): raise the container's memory in Proxmox, or build elsewhere.
* Reproducible builds: run `npm install` once inside `web/` on a computer, commit the generated
  `package-lock.json`, and the image will use `npm ci` from then on.

## Known limits (stage 1)

* On the review screen, rows you decided during this visit are marked; after a refresh they show as
  undecided even though the decision is saved on the server (the API does not return it per row).
* Not yet in the web app: packages and areas management (use the API for now), the customer's
  full ledger and invoice history, reports and exports, and printing receipts.
* The bill-run preview lists the first 200 customers on screen; the complete list is saved with the
  run once you bill and can be browsed under Billing history.
* Not yet checked in a real browser by the author: please report anything that looks or behaves wrongly.

## Developing

```bash
cd web
npm install
API_URL=http://localhost:8000 npm run dev      # needs the API running
npm run typecheck && npm test && npm run build
```
