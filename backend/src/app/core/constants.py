"""Enumerations stored as plain strings guarded by CHECK constraints (easier to migrate than PG enums)."""

CUSTOMER_STATUSES = ("ACTIVE", "INACTIVE", "ARCHIVED")
CONNECTION_TYPES = ("INTERNET", "CABLE", "COMBINED")
CONNECTION_STATUSES = ("ACTIVE", "SUSPENDED", "DISCONNECTED", "FREE", "TRIAL")
PACKAGE_STATUSES = ("ACTIVE", "INACTIVE")
COLLECTOR_STATUSES = ("ACTIVE", "INACTIVE")

EXTERNAL_SYSTEMS = ("WASOOLI", "ZALPRO", "MIKROTIK")
EXTERNAL_REF_TYPES = ("ID", "INTERNET_ID", "USERNAME")

CHARGE_TYPES = (
    "INTERNET",
    "CABLE",
    "INSTALLATION",
    "RECONNECTION",
    "EQUIPMENT",
    "LATE_FEE",
    "OTHER",
    "DISCOUNT",
)

LEDGER_ENTRY_TYPES = (
    "CHARGE",
    "DISCOUNT",
    "PAYMENT",
    "PAYMENT_REVERSAL",
    "ADJUSTMENT",
    "REFUND",
)

PAYMENT_METHODS = ("CASH", "COLLECTOR_CASH", "BANK", "JAZZCASH", "EASYPAISA", "CARD", "QR")
PAYMENT_STATUSES = ("POSTED", "VOID", "NEEDS_REVIEW")
RECEIPT_STATUSES = ("ISSUED", "VOID")

IMPORT_SESSION_STATUSES = (
    "UPLOADED",
    "PARSED",
    "MATCHED",
    "IN_REVIEW",
    "APPROVED",
    "IMPORTING",
    "COMPLETED",
    "FAILED",
)
IMPORT_ROW_STATUSES = ("NEW", "DUPLICATE", "UPDATED", "ERROR", "REVIEW", "IMPORTED", "SKIPPED")
IMPORT_DECISIONS = ("IMPORT", "SKIP", "UPDATE_EXISTING", "CREATE_SEPARATE", "MANUAL_EDIT")

BILLING_RUN_KINDS = ("MONTHLY", "LATE_FEES")
BILLING_RUN_ITEM_OUTCOMES = (
    "INVOICED",        # a cycle was billed
    "FREE_SKIPPED",    # FREE/TRIAL connection: cycle rolled forward, nothing charged
    "ZERO_PRICE",      # ACTIVE connection with no price: NOT rolled forward, needs attention
    "CYCLES_SKIPPED",  # missed cycles deliberately skipped (skip_remaining); never silent
    "NO_DUE_DATE",     # ACTIVE connection without a next due date: needs attention
    "LATE_FEE",        # a late fee was charged
    "ERROR",           # this customer failed; everything else in the run still went through
)
