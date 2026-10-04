import os
import tempfile
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

# Must be set before any app module reads settings.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres@localhost:5433/isp_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-0123456789abcdef")
os.environ.setdefault("FIELD_ENCRYPTION_KEYS", Fernet.generate_key().decode())
os.environ.setdefault("LOCKOUT_MINUTES", "15")
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="isp-test-storage-"))

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import session_factory  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.rbac import create_user, seed_rbac  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    os.environ["ALEMBIC_DATABASE_URL"] = url
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Build the test database from the real migrations (so migrations are exercised too)."""
    url = get_settings().database_url
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    eng.dispose()
    command.upgrade(alembic_config(url), "head")
    os.environ.pop("ALEMBIC_DATABASE_URL", None)
    yield


@pytest.fixture(autouse=True)
def _clean(_schema):
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with session_factory()() as db:
        db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        for seq in ("customer_code_seq", "connection_code_seq", "invoice_number_seq", "receipt_number_seq"):
            db.execute(text(f"ALTER SEQUENCE {seq} RESTART WITH 1"))
        seed_rbac(db)
        db.commit()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    with session_factory()() as s:
        yield s


@pytest.fixture
def make_user():
    """Creates a user with the given roles; returns (user_id, auth headers)."""

    def _make(*roles: str, username: str | None = None, password: str = "correct-horse-battery"):
        username = username or f"user_{uuid.uuid4().hex[:8]}"
        with session_factory()() as s:
            user = create_user(
                s, username=username, password=password, full_name=username.title(),
                role_codes=list(roles),
            )
            s.commit()
            uid = user.id
        return uid, {"Authorization": f"Bearer {create_access_token(uid)}"}

    return _make


@pytest.fixture
def admin(make_user):
    return make_user("super_admin", username="root")[1]


@pytest.fixture
def accountant(make_user):
    return make_user("accountant")[1]


@pytest.fixture
def mk_customer(client, admin):
    def _make(name="Ali Khan", **extra):
        r = client.post("/api/v1/customers", json={"full_name": name, **extra}, headers=admin)
        assert r.status_code == 201, r.text
        return r.json()

    return _make
