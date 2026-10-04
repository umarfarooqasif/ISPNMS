"""Migrations must apply, be reversible, and match the models (run against a throwaway database)."""

import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.models import Base
from tests.conftest import alembic_config

ADMIN_URL = get_settings().database_url.rsplit("/", 1)[0] + "/postgres"
URL = get_settings().database_url.rsplit("/", 1)[0] + "/isp_migration_test"


@pytest.fixture
def fresh_db():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS isp_migration_test"))
        c.execute(text("CREATE DATABASE isp_migration_test"))
    yield URL
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS isp_migration_test WITH (FORCE)"))
    os.environ.pop("ALEMBIC_DATABASE_URL", None)


def test_upgrade_downgrade_upgrade(fresh_db):
    cfg = alembic_config(fresh_db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    eng = create_engine(fresh_db)
    with eng.connect() as c:
        left = c.execute(text(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' "
            "AND table_name <> 'alembic_version'")).scalar()
        assert left == 0, "downgrade left tables behind"
        assert c.execute(text("SELECT count(*) FROM pg_proc WHERE proname IN "
                              "('forbid_update_delete','forbid_delete','payments_guard','receipts_guard')")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM pg_class WHERE relkind='S'")).scalar() == 0
    command.upgrade(cfg, "head")


def test_models_match_migrations(fresh_db):
    command.upgrade(alembic_config(fresh_db), "head")
    eng = create_engine(fresh_db)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(ctx, Base.metadata) == []
