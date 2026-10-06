import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core import constants as C

# Money in: exactly <= 2 decimal places, never floats downstream. Money out: serialised as strings.
Amount = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
PositiveAmount = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]

CustomerStatus = Literal["ACTIVE", "INACTIVE", "ARCHIVED"]
ConnectionType = Literal["INTERNET", "CABLE", "COMBINED"]
ConnectionStatus = Literal["ACTIVE", "SUSPENDED", "DISCONNECTED", "FREE", "TRIAL"]
PaymentMethod = Literal["CASH", "COLLECTOR_CASH", "BANK", "JAZZCASH", "EASYPAISA", "CARD", "QR"]
ChargeType = Literal[
    "INTERNET", "CABLE", "INSTALLATION", "RECONNECTION", "EQUIPMENT", "LATE_FEE", "OTHER", "DISCOUNT"
]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ auth / users
class LoginIn(BaseModel):
    username: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class MeOut(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str
    roles: list[str]
    permissions: list[str]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    role_codes: list[str] = []


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    is_active: bool | None = None
    role_codes: list[str] | None = None


class PasswordSet(BaseModel):
    password: str = Field(min_length=10, max_length=128)


class UserOut(ORM):
    id: uuid.UUID
    username: str
    full_name: str
    email: str | None
    is_active: bool
    role_codes: list[str] = []


# ------------------------------------------------------------------ areas / packages
class AreaIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    name_ur: str | None = None
    code: str | None = None


class AreaOut(ORM):
    id: uuid.UUID
    name: str
    name_ur: str | None
    code: str | None


class StreetIn(BaseModel):
    area_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    name_ur: str | None = None


class StreetOut(ORM):
    id: uuid.UUID
    area_id: uuid.UUID
    name: str
    name_ur: str | None


class PackageIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str
    display_name: str
    display_name_ur: str | None = None
    speed_mbps: int | None = Field(default=None, ge=0)
    monthly_price: Amount | None = Field(default=None, ge=0)
    cable_price: Amount | None = Field(default=None, ge=0)
    internet_price: Amount | None = Field(default=None, ge=0)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"
    description: str | None = None
    aliases: list[str] = []


class PackageUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    display_name_ur: str | None = None
    speed_mbps: int | None = Field(default=None, ge=0)
    monthly_price: Amount | None = Field(default=None, ge=0)
    cable_price: Amount | None = Field(default=None, ge=0)
    internet_price: Amount | None = Field(default=None, ge=0)
    status: Literal["ACTIVE", "INACTIVE"] | None = None
    description: str | None = None


class PackageOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    display_name: str
    display_name_ur: str | None
    speed_mbps: int | None
    monthly_price: Decimal | None
    cable_price: Decimal | None
    internet_price: Decimal | None
    status: str
    description: str | None
    aliases: list[str] = []


class AliasIn(BaseModel):
    alias: str = Field(min_length=1, max_length=120)
    source: str | None = None


# ------------------------------------------------------------------ customers / connections
class CustomerFields(BaseModel):
    full_name_ur: str | None = None
    father_name: str | None = None
    cnic: str | None = Field(default=None, max_length=20)
    mobile: str | None = Field(default=None, max_length=32)
    whatsapp: str | None = Field(default=None, max_length=32)
    alt_contact: str | None = Field(default=None, max_length=64)
    address: str | None = None
    address_ur: str | None = None
    area_id: uuid.UUID | None = None
    street_id: uuid.UUID | None = None
    house_no: str | None = Field(default=None, max_length=64)
    lat: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=9, decimal_places=6)
    lng: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=9, decimal_places=6)
    notes: str | None = None


class CustomerCreate(CustomerFields):
    full_name: str = Field(min_length=1, max_length=200)  # the only required field
    status: CustomerStatus = "ACTIVE"


class CustomerUpdate(CustomerFields):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    status: CustomerStatus | None = None


class CustomerOut(ORM):
    id: uuid.UUID
    customer_code: str
    full_name: str
    full_name_ur: str | None
    father_name: str | None
    cnic_masked: str | None = None
    mobile: str | None
    mobile_normalized: str | None
    whatsapp: str | None
    alt_contact: str | None
    address: str | None
    address_ur: str | None
    area_id: uuid.UUID | None
    street_id: uuid.UUID | None
    house_no: str | None
    lat: Decimal | None
    lng: Decimal | None
    notes: str | None
    status: str
    created_at: datetime


class ExternalRefIn(BaseModel):
    system: Literal["WASOOLI", "ZALPRO", "MIKROTIK"]
    ref_type: Literal["ID", "INTERNET_ID", "USERNAME"]
    value: str = Field(min_length=1, max_length=128)


class ServiceLineIn(BaseModel):
    service: Literal["CABLE", "INTERNET"]
    package_id: uuid.UUID | None = None
    price: Amount | None = Field(default=None, ge=0)


class ConnectionCreate(BaseModel):
    internet_id: str | None = Field(default=None, max_length=64)
    username: str | None = Field(default=None, max_length=128)
    package_id: uuid.UUID | None = None
    connection_type: ConnectionType
    install_date: date | None = None
    next_due_date: date | None = None
    status: ConnectionStatus = "ACTIVE"
    monthly_price_override: Amount | None = Field(default=None, ge=0)
    billing_day: int | None = Field(default=None, ge=1, le=31)
    area_id: uuid.UUID | None = None
    notes: str | None = None
    service_lines: list[ServiceLineIn] = []
    external_refs: list[ExternalRefIn] = []


class ConnectionUpdate(BaseModel):
    internet_id: str | None = Field(default=None, max_length=64)
    username: str | None = Field(default=None, max_length=128)
    package_id: uuid.UUID | None = None
    connection_type: ConnectionType | None = None
    install_date: date | None = None
    next_due_date: date | None = None
    status: ConnectionStatus | None = None
    monthly_price_override: Amount | None = Field(default=None, ge=0)
    billing_day: int | None = Field(default=None, ge=1, le=31)
    area_id: uuid.UUID | None = None
    notes: str | None = None


class ServiceLineOut(ORM):
    service: str
    package_id: uuid.UUID | None
    price: Decimal | None


class ExternalRefOut(ORM):
    system: str
    ref_type: str
    value: str


class ConnectionOut(ORM):
    id: uuid.UUID
    customer_id: uuid.UUID
    connection_code: str
    internet_id: str | None
    username: str | None
    package_id: uuid.UUID | None
    connection_type: str
    install_date: date | None
    source_recharge_date: date | None = None
    next_due_date: date | None = None
    status: str
    monthly_price_override: Decimal | None
    billing_day: int | None
    area_id: uuid.UUID | None
    notes: str | None
    service_lines: list[ServiceLineOut] = []
    external_refs: list[ExternalRefOut] = []


# ------------------------------------------------------------------ billing
class InvoiceLineIn(BaseModel):
    charge_type: ChargeType
    amount: Amount
    description: str | None = None
    connection_id: uuid.UUID | None = None


class InvoiceCreate(BaseModel):
    customer_id: uuid.UUID
    lines: list[InvoiceLineIn] = Field(min_length=1)
    issue_date: date | None = None
    due_date: date
    period: date | None = None
    notes: str | None = None


class InvoiceLineOut(ORM):
    id: uuid.UUID
    charge_type: str
    description: str | None
    amount: Decimal
    connection_id: uuid.UUID | None


class InvoiceOut(BaseModel):
    id: uuid.UUID
    invoice_number: str
    customer_id: uuid.UUID
    issue_date: date
    due_date: date
    period: date | None
    total: Decimal
    paid: Decimal
    outstanding: Decimal
    status: str
    notes: str | None
    lines: list[InvoiceLineOut]


class PaymentCreate(BaseModel):
    customer_id: uuid.UUID
    amount: PositiveAmount
    method: PaymentMethod
    connection_id: uuid.UUID | None = None
    client_txn_id: str | None = Field(default=None, min_length=8, max_length=64)
    collected_at: datetime | None = None
    notes: str | None = None


class PaymentVoid(BaseModel):
    reason: str = Field(min_length=3)


class AllocationOut(ORM):
    invoice_id: uuid.UUID
    amount: Decimal


class PaymentOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    amount: Decimal
    method: str
    status: str
    collector_id: uuid.UUID | None
    client_txn_id: str | None
    client_receipt_no: str | None = None  # provisional receipt number printed offline, if any
    collected_at: datetime
    received_at: datetime
    receipt_number: str | None
    receipt_status: str | None
    allocations: list[AllocationOut]
    # Part of this payment not applied to any invoice (e.g. advance payment).
    unallocated: Decimal
    # Customer's ledger balance after this payment: positive = owes, negative = credit.
    balance: Decimal
    replayed: bool = False
    void_reason: str | None = None


class AdjustmentCreate(BaseModel):
    customer_id: uuid.UUID
    amount: Amount  # signed: + increases what the customer owes, - reduces it
    reason: str = Field(min_length=3)
    connection_id: uuid.UUID | None = None


class RefundCreate(BaseModel):
    customer_id: uuid.UUID
    amount: PositiveAmount
    reason: str = Field(min_length=3)


class LedgerEntryOut(ORM):
    id: uuid.UUID
    entry_type: str
    amount: Decimal
    description: str | None
    ref_type: str | None
    ref_id: uuid.UUID | None
    effective_date: date
    posted_at: datetime
    reverses_entry_id: uuid.UUID | None


class StatementOut(BaseModel):
    customer_id: uuid.UUID
    billing_status: str | None = None  # PAID/DUE/PARTIAL/OVERDUE/SUSPENDED/DISCONNECTED/FREE
    balance: Decimal
    amount_due: Decimal
    credit: Decimal
    open_invoices: list[InvoiceOut]
    recent_entries: list[LedgerEntryOut]


class ReceiptOut(BaseModel):
    receipt_number: str
    status: str
    issued_at: datetime
    payment: PaymentOut


# ------------------------------------------------------------------ collectors / audit
class CollectorCreate(BaseModel):
    user_id: uuid.UUID
    code: str = Field(min_length=1, max_length=32)


class CollectorOut(ORM):
    id: uuid.UUID
    user_id: uuid.UUID
    code: str
    status: str


class AssignAreas(BaseModel):
    area_ids: list[uuid.UUID]


class CustomerAssignment(BaseModel):
    customer_id: uuid.UUID
    sort_order: int = 0


class AssignCustomers(BaseModel):
    customers: list[CustomerAssignment]


class AuditOut(ORM):
    id: int
    at: datetime
    user_id: uuid.UUID | None
    action: str
    entity: str | None
    entity_id: str | None
    before: dict | None
    after: dict | None
    ip: str | None




# ------------------------------------------------------------------ billing runs / operations
class BillRunRequest(BaseModel):
    run_date: date | None = None            # default: today (in the configured timezone)
    lead_days: int | None = Field(default=None, ge=0, le=60)  # default: BILLING_LEAD_DAYS
    max_cycles: int = Field(default=1, ge=1, le=12)           # cycles billed per connection per run
    skip_remaining: bool = False            # write off (and report) cycles beyond max_cycles


class BillRunExecute(BillRunRequest):
    confirm: bool = False                   # must be true: a real run creates invoices


class LateFeeRequest(BaseModel):
    run_date: date | None = None
    amount: Amount | None = Field(default=None, gt=0)
    grace_days: int | None = Field(default=None, ge=0, le=90)
    due_days: int | None = Field(default=None, ge=0, le=90)


class LateFeeExecute(LateFeeRequest):
    confirm: bool = False


class RunItemOut(ORM):
    customer_id: uuid.UUID
    connection_id: uuid.UUID | None = None
    cycle_due_date: date | None = None
    outcome: str
    amount: Decimal
    invoice_id: uuid.UUID | None = None
    message: str | None = None


class RunResultOut(BaseModel):
    dry_run: bool
    run_id: uuid.UUID | None = None
    invoices_created: int
    total_billed: Decimal
    counts: dict[str, int]
    behind_connections: int = 0
    skipped_cycles: int = 0
    items: list[RunItemOut]
    items_truncated: bool = False


class BillingRunOut(ORM):
    id: uuid.UUID
    kind: str
    run_date: date
    params: dict | None = None
    invoices_created: int
    total_billed: Decimal
    summary: dict | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime


class OpeningBalanceRow(BaseModel):
    wasooli_id: str | None = Field(default=None, max_length=64)
    customer_id: uuid.UUID | None = None
    amount: str = Field(max_length=20)     # a string so no float ever sneaks in
    note: str | None = Field(default=None, max_length=300)


class OpeningBalanceLoad(BaseModel):
    as_of_date: date | None = None
    dry_run: bool = True
    rows: list[OpeningBalanceRow] = Field(min_length=1, max_length=5000)


class OpeningBalanceResultOut(BaseModel):
    index: int
    status: str
    customer_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    message: str | None = None


class OpeningBalanceLoadOut(BaseModel):
    dry_run: bool
    counts: dict[str, int]
    results: list[OpeningBalanceResultOut]


class ConnectionStatusChange(BaseModel):
    status: ConnectionStatus
    reason: str = Field(min_length=3, max_length=300)
    reconnection_fee: Amount | None = Field(default=None, ge=0)
    next_due_date: date | None = None


class ConnectionStatusOut(BaseModel):
    connection: ConnectionOut
    previous_status: str
    reconnection_invoice: InvoiceOut | None = None


class OutstandingRow(BaseModel):
    customer_id: uuid.UUID
    customer_code: str
    full_name: str
    mobile: str | None = None
    balance: Decimal
    oldest_due_date: date | None = None
    days_overdue: int = 0
    billing_status: str


class SuspensionCandidate(BaseModel):
    customer_id: uuid.UUID
    full_name: str
    oldest_due_date: date
    days_overdue: int
    outstanding: Decimal
    connection_ids: list[uuid.UUID]


# ------------------------------------------------------------------ collector mobile app
class SnapshotConnection(BaseModel):
    id: uuid.UUID
    connection_code: str
    internet_id: str | None = None
    connection_type: str
    status: str
    package_name: str | None = None
    package_name_ur: str | None = None
    monthly_charge: Decimal | None = None
    next_due_date: date | None = None


class SnapshotInvoice(BaseModel):
    id: uuid.UUID
    invoice_number: str
    period: date | None = None
    issue_date: date
    due_date: date
    total: Decimal
    outstanding: Decimal
    status: str


class SnapshotCustomer(BaseModel):
    id: uuid.UUID
    customer_code: str
    full_name: str
    full_name_ur: str | None = None
    mobile: str | None = None
    whatsapp: str | None = None
    address: str | None = None
    address_ur: str | None = None
    house_no: str | None = None
    area_name: str | None = None
    balance: Decimal
    amount_due: Decimal
    credit: Decimal
    billing_status: str
    oldest_due_date: date | None = None
    connections: list[SnapshotConnection]
    open_invoices: list[SnapshotInvoice]


class SnapshotPage(BaseModel):
    generated_at: datetime
    total: int
    offset: int
    limit: int
    customers: list[SnapshotCustomer]


class SyncPaymentIn(BaseModel):
    """Deliberately loose (strings): a malformed item must be rejected on its own, never fail the batch."""

    client_txn_id: str = Field(max_length=200)
    customer_id: str = Field(max_length=64)
    amount: str = Field(max_length=32)
    method: str = Field(max_length=32)
    collected_at: str | None = Field(default=None, max_length=64)
    connection_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=1000)
    client_receipt_no: str | None = Field(default=None, max_length=80)


class SyncPaymentsIn(BaseModel):
    payments: list[SyncPaymentIn] = Field(max_length=200)


class SyncPaymentOut(BaseModel):
    client_txn_id: str
    status: Literal["SYNCED", "DUPLICATE", "REJECTED", "ERROR"]
    code: str | None = None
    reason: str | None = None
    payment_id: uuid.UUID | None = None
    receipt_number: str | None = None
    allocated: Decimal | None = None
    unallocated: Decimal | None = None
    balance: Decimal | None = None
    collected_at_adjusted: bool = False


class SyncPaymentsOut(BaseModel):
    counts: dict[str, int]
    results: list[SyncPaymentOut]


class MethodTotal(BaseModel):
    method: str
    count: int
    total: Decimal


class CollectionSummaryOut(BaseModel):
    date: date
    count: int
    total: Decimal
    by_method: list[MethodTotal]
    voided_count: int


__all__ = [n for n in dir() if not n.startswith("_")]
_ = C  # constants kept importable from here for routers
