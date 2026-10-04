# Phase 2: Wasooli PDF Importer

Upload → parse → normalise → validate → duplicate detection → preview → review → import → report.
Run against the real `Wasooli all conections.pdf` (59 pages, 1,254 customers).

## What the real export told us (answers to the Phase 0 questions)

| Question | Answer found in the PDF |
|---|---|
| How is a disconnected customer shown? | The **Area** part of the address says `Dissconect` (132 customers). `Free conections` (17) marks free customers. Both are statuses typed into the area field, not places. |
| Date format / currency | `DD/Mon/YYYY` (e.g. `16/Feb/2026`); amounts are whole rupees. |
| Is "Total" reliable / does it include arrears? | `Total` = Install + Other + Cable + Internet amounts, and matched on all 1,254 rows. It is the **monthly charge**, not a balance. |
| Opening balances / arrears | **None in the file.** Every customer starts at a zero balance. |
| "Recharge Date": next due or last paid? | **Still unconfirmed.** Dates run from Feb 2024 to 3 Oct 2026 (the PDF was printed 22 Sep 2026), and 81 are earlier than the install date. It is stored unchanged in `connections.source_recharge_date` so Phase 3 can decide. |

Other facts that shaped the rules: `Internet ID` is **not unique** (19 values are shared by different
customers, e.g. `yousaf`); only the Wasooli `ID` is. 289 rows are cable-only (279 of them with an `FTTH` name), 19 are
combined, 946 internet-only. 313 rows have no mobile and 29 have an unusable one. 3 names are Urdu.

## What gets created

For each customer: a **customer**, a **billing account** (zero balance, no ledger entries), one **connection**
with an INTERNET and/or CABLE **service line** carrying that customer's exact amount, and **external references**
(Wasooli ID always; Internet ID when no one else has it yet). Packages (`Star3`, `cable 1`, …) and areas are created
when missing; a package's list price is the most common amount charged for it.

| Source | Becomes |
|---|---|
| Area `Dissconect` / `Free conections` | connection status `DISCONNECTED` / `FREE`; the real area is guessed from the address text when it names a known one (98 of 149), else left empty |
| Address `<text> - <Area>` | address text + area; `St# N` in the text becomes a street under that area |
| Mobile `0 - 03xx…` | first valid number → mobile; second → alternate contact; numbers missing a leading 0 are repaired; unusable ones are kept in the customer's notes |
| Name in Urdu | repaired from the PDF's visual-order text; stored as both name and Urdu name |
| Recharge Date | `connections.source_recharge_date` (meaning unconfirmed) |

Disconnected customers are imported (customer stays active, connection is `DISCONNECTED`) so history is kept.

## Duplicate handling

* Same **Wasooli ID** already in the system → never created twice. Unchanged → `DUPLICATE`; changed in a newer export →
  `UPDATED` (nothing is applied until you decide `UPDATE_EXISTING`).
* Same mobile **and** a similar name as another row or an existing customer → `REVIEW`, held back. On the real file
  this is 30 rows: a few true duplicates (same person entered twice), several people with two services.
* Row problems (`ERROR`): no ID, no name, no service, bad amount, ID repeated in the file. Fix with `MANUAL_EDIT`.

## Using it

**Command line, on the VM (simplest for the first load):**

```bash
cp Wasooli_all_conections.pdf storage/
docker compose exec api python -m app.import_cli /data/storage/Wasooli_all_conections.pdf            # preview
docker compose exec api python -m app.import_cli /data/storage/Wasooli_all_conections.pdf --commit   # import
```

The 30 held-back rows are skipped; add `--include-review` to import them as separate customers, or use the API to decide
them one by one.

**API** (`import.upload`, `import.review`, `import.commit` permissions; admins have all three):

| Step | Call |
|---|---|
| Upload (returns at once, parses in the background, ~30 s) | `POST /api/v1/imports/wasooli` (multipart `file`) |
| Wait for `MATCHED` / `IN_REVIEW` / `FAILED`; read the report | `GET /api/v1/imports/{id}` |
| Browse rows | `GET /api/v1/imports/{id}/rows?status=REVIEW&issue=INVALID_MOBILE&q=ali` |
| Decide one row | `POST /imports/{id}/rows/{row}/decision` `{"decision":"CREATE_SEPARATE"}` |
| Same customer, second connection | `{"decision":"UPDATE_EXISTING","edited_values":{"customer_id":"<uuid>"}}` |
| Fix a row | `{"decision":"MANUAL_EDIT","edited_values":{"full_name":"…"}}` |
| Decide many | `POST /imports/{id}/decisions/bulk` `{"status":"REVIEW","decision":"CREATE_SEPARATE"}` |
| Preview (default) / import | `POST /imports/{id}/commit` `{"dry_run":false}` |

Re-uploading the exact same file is refused (`409`) unless `?force=true`. Committing twice is harmless.
Every import step is audited, and `import_rows` keeps the raw PDF cells next to what was stored.

## Verified

* 106 automated tests pass (27 new): normalisation rules, PDF reader on generated Wasooli-shaped PDFs, upload →
  commit, re-import, changed export, duplicate review, manual edit, permissions. `WASOOLI_SAMPLE_PDF=<file>` adds a
  check against a real export.
* Against the real PDF in a scratch PostgreSQL: 1,224 customers imported at once, the 30 held rows decided in bulk
  → 1,254 customers; the sum of all imported service-line prices equals the PDF's monthly total (1,080,750); no ledger
  entries; a second upload of the file produced 1,224 `DUPLICATE` rows and created nobody.

## Known limits / not done here

* No web screen for reviewing rows yet (Phase 6); use the API or the command line.
* Parsing runs inside the API process (no Redis/worker). Fine for one file at a time.
* Customers whose area was `Dissconect`/`Free` and could not be guessed (51) have no area until someone sets one.
* The importer trusts the PDF's text layer; a scanned or re-typed export would fail with a clear error.
