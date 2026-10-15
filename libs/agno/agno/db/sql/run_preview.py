"""Run-preview projection shared by the SQLAlchemy backends (SQLite, Postgres, MySQL)."""

from typing import Any, Dict, List

from sqlalchemy import Table

from agno.db.utils import RUN_PREVIEW_FIELDS


def run_preview_columns(runs_table: Table) -> List[Any]:
    """The preview keys read out of ``run_data`` by the dialect's JSON operators, not the whole blob."""
    return [runs_table.c.run_data[key].label(key) for key in RUN_PREVIEW_FIELDS]


def run_preview_from_row(row: Any) -> Dict[str, Any]:
    # Stored runs never hold None values, so a NULL read is an absent key.
    return {key: value for key, value in row._mapping.items() if value is not None}
