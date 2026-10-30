from typing import Annotated, Any

from fastapi import Query
from sqlalchemy import Select
from sqlalchemy.orm import InstrumentedAttribute, Session

Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=64)]


def paginate(
    db: Session, stmt: Select, id_col: InstrumentedAttribute, limit: int, cursor: str | None
) -> tuple[list[Any], str | None]:
    """Newest-first keyset pagination on time-sortable IDs."""
    if cursor:
        stmt = stmt.where(id_col < cursor)
    rows = list(db.scalars(stmt.order_by(id_col.desc()).limit(limit + 1)).unique().all())
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor
