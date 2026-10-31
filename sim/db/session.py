from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://sim:sim@localhost:5432/sim"

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def database_url() -> str:
    return os.environ.get("SIM_DATABASE_URL", DEFAULT_DATABASE_URL)


def get_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    global _engine
    if _engine is None or (url and str(_engine.url) != url):
        _engine = create_engine(url or database_url(), echo=echo, pool_pre_ping=True)

        @event.listens_for(_engine, "connect")
        def _on_connect(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SET TIME ZONE 'UTC'")

    return _engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    global _session_factory
    eng = engine or get_engine()
    if _session_factory is None or _session_factory.kw.get("bind") is not eng:
        _session_factory = sessionmaker(bind=eng, expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    SessionFactory = factory or get_session_factory()
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_extensions(engine: Engine | None = None) -> None:
    eng = engine or get_engine()
    with eng.begin() as conn:
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
        try:
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS "vector"'))
        except Exception:
            # Tests / slim Postgres images may lack pgvector.
            pass
