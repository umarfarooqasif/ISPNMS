# Phase 6: admin web dashboard (stage 1)

A browser interface for the office, served by the `web` container (Next.js) behind Caddy at the same
address as the API. Stage 1 covers login, the dashboard, customers, and the Wasooli import. Billing,
payments, collectors and reports are stage 2.

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
* No screens yet for payments, billing runs, late fees, opening balances, collectors, users or
  connection status. Those API features exist and get screens in stage 2.
* Not yet checked in a real browser by the author: please report anything that looks or behaves wrongly.

## Developing

```bash
cd web
npm install
API_URL=http://localhost:8000 npm run dev      # needs the API running
npm run typecheck && npm test && npm run build
```
