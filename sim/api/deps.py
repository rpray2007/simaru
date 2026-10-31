from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from sim.db.session import get_session_factory


def get_db() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
