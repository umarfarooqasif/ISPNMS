# Phase 4: collector mobile app

A Flutter app for field collectors that keeps working with no internet, plus the backend endpoints it
uses. Printing to a Bluetooth thermal printer is Phase 5; this phase ends at an on-screen receipt.

## What a collector can do

* Log in (internet needed the first time only) and **download assigned customers** with their bills,
  package, balance and Urdu name/address.
* **Search offline** by name (English or Urdu), customer ID, Internet ID, mobile (any format), house
  number, address or area.
* See balance, open bills and connections, **collect a payment** (cash, JazzCash, Easypaisa, bank, QR)
  with no signal, and see an immediate receipt.
* See **today's collection** and history, and a **Sync** screen showing what is waiting, uploaded or
  rejected.

## How offline collection works

1. Before leaving, tap sync (uploads anything pending, then refreshes customers).
2. A payment is saved on the phone in one database transaction together with a **provisional receipt
   number** (`OFF-C01-0042`, counter never reused) and a unique **client transaction ID**.
3. The app tries to upload straight away and again whenever signal returns. Every answer is explicit:

| Server answer | Meaning | App does |
|---|---|---|
| `SYNCED` | Stored; permanent receipt `RC-...` returned | Marks uploaded, shows the permanent number (paper number kept) |
| `DUPLICATE` | Server already had it (lost reply, re-send) | Marks uploaded. **No second payment is ever created** |
| `REJECTED` | Can never succeed as sent (customer not assigned, bad amount, ...) | Keeps it, flags it, tells the collector to hand the cash and receipt to the office |
| `ERROR` / no signal | Temporary | Stays pending, retried later |

Re-sending a whole batch is always safe. One bad payment never blocks or rolls back the others.

## Safety rules

* **No deleting or editing.** The phone's payment table has database triggers that refuse deletes and
  any change to amount, customer, method or time; the app has no screen for it either. Logging out
  keeps unsynced payments.
* A collector can sync only for their **own assigned customers** (direct or by area). Others are rejected.
* A phone clock running ahead never loses a payment: it is stored as received now and the note says so.
* The server keeps the paper receipt number next to its own, unique per collector and immutable.
* The customer list is replaced **only after every page downloaded**, so a dropped connection never
  leaves a half list. Balances shown offline subtract what this phone collected since the download.
* Tokens live in the platform keystore. Money is integer paisa in the app, never floating point.

## Backend endpoints (collector login)

| | |
|---|---|
| `GET /api/v1/collector/snapshot?offset=&limit=` | assigned customers with bills (page through) |
| `POST /api/v1/collector/payments/sync` | up to 200 payments, one answer per item (HTTP 200) |
| `GET /api/v1/collector/summary?day=` | your own totals for a day, by method |

Migration `0005` adds `payments.client_receipt_no` (unique per collector, immutable). `GET /payments`
now also returns it.

## Setting a collector up

1. Create a user with the `collector` role, then `POST /collectors` (user id + code like `C01`).
2. Assign areas (`PUT /collectors/{id}/areas`) and/or customers (`PUT /collectors/{id}/customers`).
3. Install the app, enter your server's HTTPS address on the login screen, log in, let it download.

## Build and test

```bash
cd mobile/collector_app
flutter create . --org com.example.isp --project-name isp_collector --platforms android,ios   # once
# Android: set minSdk = 23 in android/app/build.gradle (needed by flutter_secure_storage)
flutter pub get && flutter analyze && flutter test
flutter build apk --release
```

CI runs `flutter analyze` and `flutter test` (job `collector-app-tests`) and the backend tests.

## Not in this phase

Bluetooth/Urdu receipt printing (Phase 5), the admin web dashboard (Phase 6), biometric/PIN app lock,
push notifications, iOS signing and store publishing, and cash handover/reconciliation (Phase 7).
Rejected payments are resolved by the office entering them manually for now.
