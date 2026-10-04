# ISP Billing & Collection Management System

## Project Purpose

Build a production-ready, self-hosted ISP Billing and Collection Management System for deployment on a Linux VM hosted on Proxmox.

### Critical Existing Infrastructure

The ISP already uses:

- **MikroTik** for actual network connectivity/users.
- **Zalpro** for existing internet connection/user management.

**DO NOT replace MikroTik or Zalpro.**

This application is primarily a business/operations layer for:

- Customer management
- Billing
- Payments
- Collections
- Collector mobile app
- Urdu thermal receipts
- Accounting
- Reports
- PDF customer import
- Complaints/tickets
- Inventory
- Notifications
- Future integrations with MikroTik/Zalpro

The system must be designed so that MikroTik/Zalpro integrations can be added later without making the core billing system dependent on them.

---

# 1. Core Technology Direction

Recommended architecture:

- **Deployment:** Proxmox → Linux VM → Docker
- **Database:** PostgreSQL
- **Backend:** REST API
- **Web frontend:** React / Next.js
- **Mobile app:** Flutter
- **Cache/queues:** Redis
- **Reverse proxy:** Nginx or Caddy
- **Containerization:** Docker Compose

The final application must be deployable on a Linux VM and should be maintainable as a real production application, not a prototype/demo.

---

# 2. Development Rule

## DO NOT build the entire system at once.

Development must happen phase-by-phase.

For every phase:

1. Understand the requirements.
2. Inspect the existing codebase.
3. Implement only the requested phase.
4. Write automated tests.
5. Run tests.
6. Fix failures.
7. Check database migrations.
8. Check security and permissions.
9. Document what was implemented.
10. Stop and wait for approval before moving to the next major phase.

Do not silently redesign earlier approved architecture.

Do not remove existing functionality just to make implementation easier.

If a requirement conflicts with the existing architecture, explain the conflict before making a destructive change.

---

# 3. Real Existing Customer Data

There is an existing PDF export:

**`Wasooli all conections.pdf`**

This is a real export from the existing Wasooli system and must be treated as an important source for the import architecture.

The PDF contains customer/connection information including fields such as:

- Sno
- ID
- Internet ID
- Name
- Address
- Install Date
- Recharge Date
- Mobile No
- Install Amount
- Other Amount
- Package-Cable
- Amount-Cable
- Package-Internet
- Amount-Internet
- Total

The data includes cases such as:

- Internet-only customers
- Cable-only customers
- Combined cable + internet customers
- Disconnected customers
- Different package names
- Missing values
- `-` values
- Different amounts
- Variable/multiline addresses
- Potential PDF extraction irregularities

Do not assume every row has every field.

Do not make CNIC mandatory during initial import because the existing PDF does not provide CNIC.

Existing IDs such as **ID** and **Internet ID** must be preserved because they are important for matching existing customers during future imports and possible Zalpro integration.

---

# 4. System Architecture

The application should contain these major layers:

```text
                         ┌─────────────────────┐
                         │     Web Browser      │
                         │   Admin Dashboard    │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │      Backend API    │
                         │ Auth / Billing /    │
                         │ Customers / Reports│
                         └──────────┬──────────┘
                                    │
                ┌───────────────────┼───────────────────┐
                ▼                   ▼                   ▼
        ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
        │ PostgreSQL   │    │    Redis     │    │ File Storage │
        └──────────────┘    └──────────────┘    └──────────────┘

                         ▲
                         │ REST API
                         │
                  ┌──────┴───────┐
                  │ Flutter App  │
                  │  Collectors  │
                  └──────────────┘

Existing external systems:

        ┌──────────────┐              ┌──────────────┐
        │   MikroTik   │              │    Zalpro    │
        │ Existing     │              │ Existing     │
        │ Network      │              │ ISP System   │
        └──────────────┘              └──────────────┘

These are NOT replaced.
Integration is optional/future.
```

---

# 5. Database Architecture

Use PostgreSQL.

Use proper:

- Primary keys
- Foreign keys
- Unique constraints
- Check constraints
- Indexes
- Timestamps
- Soft-delete where appropriate
- Audit history
- Database migrations

Never use floating point for money.

Use appropriate decimal/numeric types for financial values.

---

# 6. Customer Management

Customer fields should support:

- Customer ID/code
- Full name
- Urdu name
- Father name
- CNIC
- CNIC images/documents where authorized
- Mobile number
- WhatsApp number
- Alternate contact
- Address
- Urdu address
- Area
- Street
- House number
- GPS latitude
- GPS longitude
- Notes
- Customer photo
- Documents
- Status
- Custom fields

Do not force every field to be mandatory.

The admin must be able to configure additional customer fields.

---

# 7. Separate Customer and Connection Entities

A customer and a connection must not be treated as the same database object.

One customer may have multiple connections.

A connection should support fields such as:

- Connection ID
- Customer ID
- Internet ID
- Existing external ID
- Username
- Package
- Connection type
- Installation date
- Status
- Monthly price
- Billing day
- MikroTik reference
- Zalpro reference
- Notes

This separation is important for future integrations and customers with multiple services.

---

# 8. Packages

Packages must be database-driven.

Do NOT hardcode package names or prices.

Package fields should support:

- Internal package ID
- Package name
- Display name
- Urdu display name
- Speed
- Monthly price
- Cable price
- Internet price
- Status
- Description

Existing PDF values such as:

- Star3
- Star4
- Star6
- Star8
- Star10
- Star15
- Star30

must be handled through package mapping/configuration.

Example:

```text
PDF: Star3
Database display name: Star 3
```

Do not assume a package price from its name.

---

# 9. Billing System

Implement:

- Monthly billing
- Custom billing dates
- Due dates
- Previous balance
- Credit balance
- Partial payments
- Advance payments
- Discounts
- Special pricing
- Installation charges
- Reconnection charges
- Equipment charges
- Other charges
- Late fees
- Refunds
- Adjustments
- Automatic invoices
- Outstanding balances
- Free/trial connections
- Cable charges
- Internet charges
- Combined cable + internet charges

Billing calculations must happen server-side.

Financial changes must be audited.

Billing statuses should support:

- PAID
- DUE
- PARTIAL
- OVERDUE
- SUSPENDED
- DISCONNECTED
- FREE

Disconnected customers from the imported PDF must not automatically become active customers.

---

# 10. PDF Importer — Critical Feature

The PDF importer is one of the most important parts of the system.

Required workflow:

```text
PDF Upload
    ↓
Parse
    ↓
Normalize
    ↓
Validate
    ↓
Duplicate Detection
    ↓
Preview
    ↓
Admin Review
    ↓
Import
    ↓
Import Report
```

## Never directly insert parsed PDF data.

Every PDF import must create an import session.

The system should retain:

- Import session
- Uploaded file information
- Original extracted values
- Normalized values
- Validation errors
- Duplicate decisions
- Row status
- Import result
- Timestamp
- Admin/user who performed import

---

# 11. PDF Parser Requirements

The parser must handle:

- Multi-page PDFs
- Rows split across page boundaries
- Multiline names
- Multiline addresses
- Missing values
- `-` values
- Disconnected customers
- Cable-only customers
- Internet-only customers
- Combined customers
- Different package names
- Inconsistent spacing
- PDF extraction irregularities
- OCR-related irregularities where applicable

Do not silently discard a row.

If a row cannot be confidently parsed:

```text
Status = REVIEW or ERROR
```

and show it to the administrator.

---

# 12. PDF Import Row Statuses

Support:

- NEW
- DUPLICATE
- UPDATED
- ERROR
- REVIEW
- IMPORTED
- SKIPPED

The admin must be able to see:

### Original values

Exactly what was extracted.

### Normalized values

What the system proposes to store.

The admin should be able to:

- Import
- Skip
- Update existing
- Create separate customer
- Manually edit

---

# 13. Duplicate Detection

Use multiple matching levels.

Priority:

1. Existing external ID / Internet ID
2. Existing Wasooli/Zalpro ID
3. Mobile number
4. Internet username
5. Fuzzy name/address matching

Duplicate detection must not blindly merge records.

Potential duplicates should be shown for human review.

---

# 14. Repeated Monthly PDF Imports

The system must support importing future PDFs from the same source.

Example:

```text
Month 1 PDF
    ↓
Create customers

Month 2 PDF
    ↓
Match existing customers
    ↓
Update changed information
    ↓
Create genuinely new customers
    ↓
Flag changed/disconnected customers
    ↓
Generate import report
```

Re-importing the same PDF must not create duplicate customers.

---

# 15. Collector Mobile Application

Build the mobile app with Flutter.

Collector features:

- Login
- Assigned areas
- Assigned customers
- Customer search
- Search by name
- Search by Internet ID
- Search by mobile number
- Search by customer ID
- Search by house number
- Customer details
- Urdu customer information
- Current bill
- Previous balance
- Package information
- Payment collection
- Payment method selection
- Receipt generation
- Thermal printing
- Today's collection
- Collection history

---

# 16. Offline-First Collection

This is critical.

Before leaving the office, the collector should be able to synchronize assigned customers.

During poor/no internet:

```text
Customer Search
     ↓
View Bill
     ↓
Collect Payment
     ↓
Store Payment Locally
     ↓
Print Receipt
```

When internet returns:

```text
Local Payment Queue
        ↓
Automatic Sync
        ↓
Server Validation
        ↓
Permanent Payment Record
```

Every offline transaction must have a unique client transaction ID.

The server must reject duplicate synchronization attempts.

Collectors must not be able to silently delete or alter payment history.

---

# 17. Urdu Thermal Printing

Urdu printing is a first-class requirement.

Support:

- 58mm thermal printers
- 80mm thermal printers
- Bluetooth printers
- Urdu/Arabic RTL
- Proper Urdu shaping
- Urdu-compatible fonts

### Important

Do NOT depend on raw printer text encoding for Urdu.

Instead:

```text
Generate Urdu receipt
        ↓
Render using proper Urdu font + RTL shaping
        ↓
Convert receipt to bitmap/image
        ↓
Send image to thermal printer
```

This is much more reliable across inexpensive thermal printers.

---

# 18. Receipt Contents

Receipt should support configurable:

- ISP logo
- ISP name
- Urdu ISP name
- Address
- Phone
- Receipt number
- Customer name
- Urdu customer name
- Address
- Urdu address
- Package
- Monthly bill
- Previous balance
- Total
- Paid amount
- Remaining balance
- Payment method
- Collector name
- Date/time
- QR code
- Footer
- Custom text

Example Urdu receipt content:

```text
پاکستان کیبل اینڈ انٹرنیٹ

رسید نمبر: RC-000001

صارف: محمد علی
پتہ: ...

پیکیج: اسٹار 10

ماہانہ بل: 2000
پچھلا بقایا: 500
کل رقم: 2500

وصول شدہ: 2500
بقایا: 0

تاریخ: ...
وصول کنندہ: ...

شکریہ
```

The exact wording must be configurable.

---

# 19. Printer Configuration

Admin should be able to configure:

- Printer width
- 58mm / 80mm
- Bluetooth printer
- Font size
- Receipt layout
- Logo
- Language
- QR code
- Footer
- Receipt number format

The collector app should allow selecting/remembering their assigned printer.

Include a test-print function.

---

# 20. Receipt History

Every receipt must be permanently tracked.

Store:

- Receipt number
- Customer
- Connection
- Payment
- Amount
- Collector
- Date/time
- Payment method
- Status

Admin should be able to:

- View receipt
- Reprint receipt
- Download/share where supported
- Void with permission
- View audit history

Do not physically delete financial records.

---

# 21. Collection Areas and Routes

Support:

- Areas
- Streets
- Collector assignments
- Customer assignments
- Ordered customer lists
- Collection routes

Future extension:

- GPS
- Maps
- Route optimization
- Fiber route mapping

---

# 22. Dashboard

Admin dashboard should show:

- Total customers
- Active customers
- Disconnected customers
- Today's collection
- Monthly collection
- Outstanding amount
- Collector performance
- Number of collectors
- Complaints
- Recent payments
- Recent imports
- Recent activity

---

# 23. Accounting

Income categories:

- Internet
- Cable
- Installation
- Reconnection
- Equipment
- Other

Expense categories:

- Bandwidth
- Electricity
- Salaries
- Fuel
- Maintenance
- Equipment
- Rent
- Other

Reports:

- Daily
- Weekly
- Monthly
- Yearly
- Collector-wise
- Area-wise
- Package-wise
- Outstanding
- Reconciliation
- Profit & Loss
- Cash flow

Exports:

- PDF
- Excel
- CSV

---

# 24. Complaints / Tickets

Support:

- Complaint categories
- Priority
- Customer
- Connection
- Technician assignment
- SLA
- Status
- Photos
- Internal notes
- Resolution history
- Customer notifications

Future technician app should support:

- Assigned complaints
- Customer location
- Connection information
- Previous complaints
- Installation jobs
- Fiber fault jobs
- Before/after photos
- Work notes
- Equipment used
- GPS
- Customer confirmation

---

# 25. Inventory

Inventory should support:

- ONUs
- Routers
- Fiber
- Patch cords
- SFPs
- Splitters
- Connectors
- Power supplies
- Network equipment
- Cables

Track:

```text
Warehouse
    ↓
Technician
    ↓
Customer
```

Maintain equipment assignment/history.

---

# 26. Notifications

Architecture should support future:

- SMS
- WhatsApp
- Email
- Push notifications

Possible messages:

- Bill generated
- Payment received
- Bill due
- Expiry reminder
- Complaint update
- Service notification

Support Urdu and English templates.

---

# 27. Customer Portal / App — Future

Future customer portal should support:

- View bills
- View payments
- View receipts
- View package
- Connection status
- Complaint creation
- Complaint tracking
- Package upgrade request
- Support

Do not prioritize this over the core billing/collection system.

---

# 28. Payment Integrations — Future

Architecture should allow:

- Cash
- Collector cash
- Bank transfer
- JazzCash
- Easypaisa
- Cards
- QR payments

Payment gateways must be modular.

Do not tightly couple the billing engine to one payment provider.

---

# 29. MikroTik / Zalpro Integration — Future

Do not rebuild the networking system.

The existing systems remain the source of truth for actual connectivity.

Future integration may support:

```text
Payment Received
        ↓
Billing Status = PAID
        ↓
Optional Integration
        ↓
Zalpro / MikroTik
        ↓
Restore/Update Connection
```

Possible future integration features:

- Customer synchronization
- Connection status
- Package synchronization
- Username synchronization
- Suspension
- Restoration
- Service status

The billing application must continue working if MikroTik/Zalpro is temporarily unavailable.

---

# 30. OLT / Fiber Management — Future

Do not make this a V1 dependency.

However, design the database so future modules can support:

- OLT
- ONU
- PON
- NAP
- Splitters
- Fiber cores
- Fiber routes
- Optical power
- Network maps
- Outage locations

Future map features may show:

```text
OLT
 ↓
PON
 ↓
Splitter / NAP
 ↓
Fiber Route
 ↓
Customer
```

---

# 31. Roles and Permissions

Recommended roles:

- Super Admin
- Admin
- Manager
- Accountant
- Collector
- Technician
- NOC
- Sales
- Dealer / Reseller

Permissions must be granular.

Example Collector permissions:

Allowed:

- View assigned customers
- Search assigned customers
- Collect payments
- Print receipts
- View own collection history

Not allowed by default:

- Delete customers
- Change packages
- Modify financial history
- View sensitive CNIC images
- Delete payments
- Modify other collectors' records

Every sensitive action should be permission-checked server-side.

---

# 32. Audit Logs

Audit important actions:

- Login
- Logout
- Customer creation
- Customer update
- Customer deletion/archival
- Package changes
- Invoice creation
- Payment creation
- Payment modification
- Receipt void
- Refund
- PDF import
- Import approval
- Import update
- Permission changes
- User changes
- Settings changes

Audit logs should contain:

- User
- Action
- Entity
- Entity ID
- Previous state where appropriate
- New state where appropriate
- Timestamp
- IP/device information where appropriate

---

# 33. Security

Implement:

- HTTPS
- Secure password hashing
- Secure authentication
- JWT/session security
- Role-based access control
- API authentication
- Rate limiting
- Admin 2FA
- Audit logs
- Login history
- Secure database credentials
- Encrypted backups
- Restore testing
- Sensitive-data protection

CNIC and related documents are sensitive and must have restricted access.

Never expose privileged operations through client-side-only authorization.

Server-side authorization is mandatory.

---

# 34. Deployment

Production deployment:

```text
Proxmox
   ↓
Linux VM
   ↓
Docker
   ├── Frontend
   ├── Backend
   ├── PostgreSQL
   ├── Redis
   ├── Reverse Proxy
   └── File/Object Storage
```

Provide:

- `docker-compose.yml`
- Environment configuration
- Database migrations
- Seed scripts where appropriate
- Health checks
- Backup script
- Restore script
- Update script
- Logs
- Monitoring hooks
- Production documentation

Example operational commands should eventually include:

```bash
docker compose up -d
docker compose down
./backup.sh
./restore.sh
./update.sh
```

Do not hardcode secrets.

Use `.env` and provide `.env.example`.

---

# 35. Backup Strategy

Implement a reliable backup system.

Backup:

- PostgreSQL database
- Important uploaded files/documents
- Configuration required for recovery

Support:

- Automated backups
- Retention policy
- Encrypted backup where possible
- Restore testing

A backup that has never been restored/tested should not be considered reliable.

---

# 36. Recommended Repository Structure

Use a clean monorepo structure similar to:

```text
isp-billing-system/
│
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
│
├── docs/
│   ├── architecture.md
│   ├── database.md
│   ├── pdf-import.md
│   ├── billing.md
│   ├── mobile.md
│   ├── printing.md
│   ├── security.md
│   └── deployment.md
│
├── backend/
│   ├── src/
│   ├── tests/
│   ├── migrations/
│   └── Dockerfile
│
├── web/
│   ├── src/
│   └── Dockerfile
│
├── mobile/
│   ├── lib/
│   ├── test/
│   └── pubspec.yaml
│
├── scripts/
│   ├── backup.sh
│   ├── restore.sh
│   └── update.sh
│
└── storage/
    └── .gitkeep
```

The exact framework/library structure may be adjusted after architecture review.

---

# 37. Development Phases

## Phase 0 — Architecture

Do not code.

Produce:

1. System architecture
2. ERD
3. Database schema
4. PDF import architecture
5. Duplicate detection strategy
6. Billing architecture
7. Mobile/offline architecture
8. Urdu thermal printing architecture
9. Security architecture
10. Docker deployment architecture
11. Development plan

Wait for approval.

---

## Phase 1 — Database + Backend Foundation

Implement:

- PostgreSQL
- Database migrations
- Customers
- Connections
- Packages
- Billing accounts
- Users
- Roles
- Permissions
- Payments
- Invoices
- Receipts
- Collectors
- Areas
- Locations
- Audit logs
- Import tracking tables

Do NOT implement:

- Mobile app
- PDF importer
- MikroTik integration
- Zalpro integration

Test everything.

---

## Phase 2 — PDF Importer

Implement:

```text
Upload
→ Parse
→ Normalize
→ Validate
→ Duplicate detection
→ Preview
→ Review
→ Import
→ Report
```

Use the real:

`Wasooli all conections.pdf`

as a test/reference input.

Add automated tests for representative cases.

---

## Phase 3 — Billing

Implement:

- Packages
- Monthly billing
- Invoices
- Due dates
- Previous balance
- Partial payments
- Discounts
- Adjustments
- Payment history
- Outstanding
- Disconnected
- Free/trial
- Cable
- Internet
- Combined services

Use server-side financial calculations.

---

## Phase 4 — Collector Mobile App

Flutter app:

- Login
- Assigned customers
- Search
- Customer details
- Urdu details
- Current bill
- Payment collection
- Payment methods
- Receipt
- Collection history
- Offline mode
- Synchronization

---

## Phase 5 — Thermal Printing

Implement:

- Bluetooth printers
- 58mm
- 80mm
- Urdu RTL
- Proper shaping
- Bitmap rendering
- Receipt configuration
- Test print
- Printer selection/storage

---

## Phase 6 — Admin Dashboard

Implement:

- Customer dashboard
- Billing dashboard
- Collection dashboard
- Import dashboard
- Collector dashboard
- Recent activity
- Alerts

---

## Phase 7 — Accounting

Implement:

- Income
- Expenses
- Cash flow
- Profit/loss
- Reconciliation
- Reports
- Exports

---

## Phase 8 — Reports

Implement detailed:

- Customer reports
- Collection reports
- Collector reports
- Area reports
- Package reports
- Outstanding reports
- Payment reports
- Import reports
- Financial reports

---

## Phase 9 — Complaints / Tickets

Implement:

- Complaints
- Priorities
- Technicians
- Assignments
- SLA
- Photos
- Resolution history

---

## Phase 10 — Inventory

Implement:

- Inventory items
- Warehouses
- Technician stock
- Customer equipment
- Equipment history

---

## Phase 11 — Customer Portal

Implement customer-facing portal/app.

---

## Phase 12 — MikroTik / Zalpro Integration

Only after the core system is stable.

---

## Phase 13 — Notifications

Add:

- SMS
- WhatsApp
- Email
- Push

---

## Phase 14 — Maps / GPS

Add:

- Customer locations
- Collection routes
- Technician locations
- Fiber routes
- Outage mapping

---

## Phase 15 — Security Hardening

Perform a full security review:

- Authentication
- Authorization
- API security
- Input validation
- File upload security
- SQL injection protection
- XSS/CSRF protection
- Rate limiting
- Sensitive data
- Audit logs
- Secrets
- Backup security

---

## Phase 16 — Production Deployment

Finalize:

- Docker
- Proxmox deployment
- HTTPS
- Backups
- Monitoring
- Logs
- Recovery
- Documentation
- Upgrade procedure

---

# 38. Testing Requirements

Every major module must include automated tests.

Important PDF importer tests:

- Normal row
- Missing mobile
- Missing package
- Cable-only
- Internet-only
- Combined
- Disconnected
- Multiline address
- Page-boundary row
- Duplicate Internet ID
- Duplicate mobile
- Changed package
- Re-import same PDF
- Invalid amount
- Missing required identification
- Unknown package

Billing tests:

- Full payment
- Partial payment
- Advance payment
- Previous balance
- Discount
- Refund
- Adjustment
- Overdue
- Disconnected
- Free account
- Cable + internet
- Decimal money calculations

Offline tests:

- Payment created offline
- Duplicate sync
- Sync failure
- Retry
- Successful sync
- Receipt generation before sync

---

# 39. Data Integrity Rules

Never:

- Silently delete imported records
- Silently merge possible duplicates
- Create duplicate customers during re-import
- Use floating point for money
- Allow client-side-only financial calculations
- Allow collectors to alter financial history without permission
- Hardcode package prices
- Make CNIC mandatory when importing the existing PDF
- Make MikroTik/Zalpro availability a requirement for billing

Always:

- Preserve source IDs
- Preserve import history
- Audit financial changes
- Validate server-side
- Use database constraints
- Use transactions for financial operations
- Make synchronization idempotent

---

# 40. Claude Development Instructions

You are the lead software architect and senior engineer for this project.

When working on this repository:

1. Read this README completely before changing code.
2. Inspect the existing repository before implementation.
3. Follow the current approved architecture.
4. Do not implement future phases prematurely.
5. Do not replace MikroTik or Zalpro.
6. Do not remove existing data fields without approval.
7. Do not silently change business rules.
8. Do not hardcode package prices.
9. Do not use floating point for money.
10. Do not directly import PDF rows into production tables without an import/review process.
11. Do not silently discard malformed PDF rows.
12. Write tests for important functionality.
13. Run tests after implementation.
14. Fix errors before declaring a phase complete.
15. Keep migrations reversible where practical.
16. Keep sensitive information protected.
17. Keep documentation updated.
18. Prefer maintainable production code over quick hacks.

---

# 41. First Task for Claude

Before writing application code, perform **PHASE 0 ONLY**.

Study:

- This README
- The existing repository
- The real `Wasooli all conections.pdf` if available in the project/workspace

Then produce:

1. Final architecture
2. Detailed ERD
3. Database schema
4. PDF parsing design
5. Import workflow
6. Duplicate detection algorithm
7. Billing architecture
8. Offline synchronization architecture
9. Urdu thermal printing architecture
10. Security model
11. Docker/Proxmox deployment architecture
12. Repository structure
13. Detailed development plan
14. Risks and technical decisions

### DO NOT START CODING YET.

Wait for explicit approval before implementing Phase 1.

---

# 42. Definition of Done

The system is not considered production-ready merely because the UI works.

A phase is complete only when:

- Requirements are implemented
- Database structure is correct
- API behavior is validated
- Permissions are enforced
- Automated tests pass
- Error handling exists
- Audit requirements are covered
- Documentation is updated
- No known critical errors remain

The final goal is a reliable, self-hosted ISP billing and collection platform that can be used by real staff and collectors in daily operations.

