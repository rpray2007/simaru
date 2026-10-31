from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from sim.db.bootstrap import create_all
from sim.db.models import Base
from sim.db.session import get_engine, get_session_factory


def _database_url() -> str:
    return os.environ.get(
        "SIM_DATABASE_URL", "postgresql+psycopg://sim:sim@localhost:5432/sim"
    )


def postgres_available() -> bool:
    """Probe Postgres with a short connect timeout (not at import time)."""
    try:
        engine = create_engine(
            _database_url(),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 2},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


# Evaluate at import time (boolean), not as a string — string skipif is resolved
# in the *test module* namespace, where postgres_available is not defined.
requires_postgres = pytest.mark.skipif(
    not postgres_available(),
    reason="Postgres not available (set SIM_DATABASE_URL or start docker compose)",
)


def _truncate_all(engine) -> None:
    """Clear rows without DROP (avoids deadlocks with concurrent sessions)."""
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(872364)"))
        names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        if names:
            conn.execute(text(f"TRUNCATE {names} CASCADE"))


@pytest.fixture()
def db_session():
    if not postgres_available():
        pytest.skip("Postgres not available")
    engine = get_engine(_database_url())
    create_all(engine)
    _truncate_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        try:
            _truncate_all(engine)
        except Exception:
            pass
