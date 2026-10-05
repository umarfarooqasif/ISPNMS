"""Permission catalogue, default roles, and idempotent seeding."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Permission, Role, User

PERMISSIONS: dict[str, str] = {
    "user.manage": "Create/update users and assign non-super-admin roles",
    "role.manage": "Manage roles and grant the super_admin role",
    "settings.manage": "Change system settings",
    "audit.view": "View audit logs",
    "area.view": "View areas and streets",
    "area.manage": "Create/update areas and streets",
    "package.view": "View packages",
    "package.manage": "Create/update packages and aliases",
    "customer.view": "View all customers",
    "customer.view_assigned": "View only customers assigned to own collector profile",
    "customer.create": "Create customers",
    "customer.update": "Update customers",
    "customer.archive": "Archive customers",
    "customer.cnic.view": "View full CNIC numbers (audited)",
    "connection.view": "View connections",
    "connection.create": "Create connections",
    "connection.update": "Update connections",
    "invoice.view": "View all invoices and balances",
    "invoice.create": "Create invoices",
    "payment.view": "View all payments",
    "payment.create": "Record payments",
    "payment.void": "Void payments/receipts",
    "billing.adjust": "Post billing adjustments",
    "billing.refund": "Issue refunds",
    "billing.run": "Preview and run monthly billing and late fees",
    "billing.opening_balance": "Load opening balances carried over from the old system",
    "connection.status": "Suspend, disconnect or reactivate connections (can charge a reconnection fee)",
    "receipt.view": "View receipts",
    "receipt.print": "Print/reprint receipts",
    "collection.view_own": "View own collection history",
    "collector.manage": "Manage collectors and their assignments",
    "import.upload": "Upload source-system exports (Wasooli PDF) and view import results",
    "import.review": "Review import rows and record decisions",
    "import.commit": "Commit an import into customers and connections",
}

_ALL = list(PERMISSIONS)

ROLES: dict[str, tuple[str, list[str]]] = {
    "super_admin": ("Super Admin", _ALL),
    "admin": (
        "Admin",
        [p for p in _ALL if p not in ("role.manage",)],
    ),
    "manager": (
        "Manager",
        [
            "audit.view", "area.view", "package.view", "customer.view", "connection.view",
            "invoice.view", "payment.view", "receipt.view", "receipt.print",
        ],
    ),
    "accountant": (
        "Accountant",
        [
            "area.view", "package.view", "customer.view", "connection.view", "invoice.view",
            "invoice.create", "payment.view", "payment.create", "payment.void", "billing.adjust",
            "billing.refund", "billing.run", "billing.opening_balance", "receipt.view",
            "receipt.print", "audit.view",
        ],
    ),
    "collector": (
        "Collector",
        [
            "customer.view_assigned", "connection.view", "package.view", "payment.create",
            "receipt.view", "receipt.print", "collection.view_own",
        ],
    ),
    "technician": ("Technician", ["customer.view_assigned", "connection.view"]),
    "noc": ("NOC", ["customer.view", "connection.view", "area.view", "package.view"]),
    "sales": (
        "Sales",
        [
            "customer.view", "customer.create", "connection.view", "connection.create",
            "area.view", "package.view",
        ],
    ),
    "dealer": ("Dealer / Reseller", ["customer.view_assigned", "package.view"]),
}


def seed_rbac(db: Session) -> None:
    """Idempotent. Adds missing permissions/roles/grants; never removes grants an admin changed."""
    perms = {p.code: p for p in db.scalars(select(Permission))}
    new_codes: set[str] = set()
    for code, desc in PERMISSIONS.items():
        if code not in perms:
            new_codes.add(code)
            perms[code] = Permission(code=code, description=desc)
            db.add(perms[code])
    db.flush()

    roles = {r.code: r for r in db.scalars(select(Role))}
    for code, (name, granted) in ROLES.items():
        role = roles.get(code)
        if role is None:
            role = Role(code=code, name=name, is_system=True)
            db.add(role)
            db.flush()
            role.permissions = [perms[p] for p in granted]
        else:
            have = {p.code for p in role.permissions}
            for p in granted:
                # super_admin always has everything. Other roles only receive a permission by
                # default when it is brand new, so grants an admin removed are never put back.
                if p not in have and (code == "super_admin" or p in new_codes):
                    role.permissions.append(perms[p])
    db.flush()


def create_user(
    db: Session, *, username: str, password: str, full_name: str, role_codes: list[str],
    email: str | None = None,
) -> User:
    roles = list(db.scalars(select(Role).where(Role.code.in_(role_codes))))
    if len(roles) != len(set(role_codes)):
        raise ValueError("unknown role code")
    user = User(
        username=username.strip(), full_name=full_name, email=email,
        password_hash=hash_password(password),
    )
    user.roles = roles
    db.add(user)
    db.flush()
    return user


def user_permissions(user: User) -> set[str]:
    return {p.code for r in user.roles for p in r.permissions}
