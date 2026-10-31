from uuid import UUID

from uuid6 import uuid7


def new_id() -> UUID:
    """Return a time-ordered UUIDv7."""
    return uuid7()
