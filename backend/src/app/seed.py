"""Idempotent first-run seeding: permissions, roles, and (optionally) the bootstrap super admin.

Run: python -m app.seed
"""

import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import session_factory
from app.models import User
from app.services.rbac import create_user, seed_rbac


def main() -> int:
    s = get_settings()
    with session_factory()() as db:
        seed_rbac(db)
        has_users = db.scalar(select(func.count()).select_from(User)) > 0
        if not has_users:
            if not s.bootstrap_admin_password:
                print("RBAC seeded. No users exist and BOOTSTRAP_ADMIN_PASSWORD is not set; "
                      "no admin created.", file=sys.stderr)
            else:
                create_user(
                    db, username=s.bootstrap_admin_username, password=s.bootstrap_admin_password,
                    full_name="Administrator", role_codes=["super_admin"],
                )
                print(f"Created super admin '{s.bootstrap_admin_username}'.")
        db.commit()
    print("Seed complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
