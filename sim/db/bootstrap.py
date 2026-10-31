from __future__ import annotations

from sqlalchemy.engine import Engine

from sim.db.models import Base
from sim.db.session import ensure_extensions, get_engine


def create_all(engine: Engine | None = None) -> Engine:
    eng = engine or get_engine()
    ensure_extensions(eng)
    Base.metadata.create_all(eng)
    return eng


def drop_all(engine: Engine | None = None) -> None:
    eng = engine or get_engine()
    Base.metadata.drop_all(eng)
