"""Regression coverage for PostgreSQL component archive semantics.

Behavior change pinned deliberately: upsert_component on a soft-deleted row used to silently reactivate it,
letting a create inherit a dead component's history. Archived ids are now
reserved and immutable; ComponentArchivedError is raised and restore_component
is the explicit way back.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import JSON, BigInteger, Column, Integer, MetaData, String, Table, Text, create_engine

from agno.db.base import ComponentArchivedError, ComponentType
from agno.db.postgres import PostgresDb


@pytest.fixture
def postgres_components_db(tmp_path):
    """Run the generic SQLAlchemy component lifecycle without a live PostgreSQL service."""
    engine = create_engine(f"sqlite:///{tmp_path / 'components.db'}")
    metadata = MetaData()
    components = Table(
        "agno_components",
        metadata,
        Column("component_id", String, primary_key=True),
        Column("component_type", String, nullable=False),
        Column("name", String),
        Column("description", Text),
        Column("current_version", Integer),
        Column("metadata", JSON),
        Column("created_at", BigInteger, nullable=False),
        Column("updated_at", BigInteger),
        Column("deleted_at", BigInteger),
        Column("user_id", String),
    )
    metadata.create_all(engine)

    db = PostgresDb(db_engine=engine, db_schema="unused", create_schema=False)

    def get_table(table_type, create_table_if_not_found=False):
        return components if table_type == "components" else None

    with patch.object(db, "_get_table", side_effect=get_table):
        yield db

    db.Session.remove()
    engine.dispose()


def test_upsert_component_refuses_archived_component(postgres_components_db):
    db = postgres_components_db

    created = db.upsert_component(
        component_id="agent-1",
        component_type=ComponentType.AGENT,
        name="before",
    )
    assert created["name"] == "before"

    assert db.delete_component("agent-1") is True
    assert db.get_component("agent-1") is None
    assert db.get_component("agent-1", include_deleted=True) is not None

    deleted_rows, total = db.list_components(include_deleted=True)
    assert total == 1
    assert deleted_rows[0]["deleted_at"] is not None

    # The old implicit reactivation is gone: the archived id is reserved
    with pytest.raises(ComponentArchivedError):
        db.upsert_component(
            component_id="agent-1",
            component_type=ComponentType.AGENT,
            name="after",
        )

    # Restore is the explicit way back, then writes work again
    assert db.restore_component("agent-1") is True
    restored = db.upsert_component(
        component_id="agent-1",
        component_type=ComponentType.AGENT,
        name="after",
    )
    assert restored["component_id"] == "agent-1"
    assert restored["name"] == "after"
    assert restored["deleted_at"] is None

    # Restoring a live component is a no-op
    assert db.restore_component("agent-1") is False

    all_rows, total = db.list_components(include_deleted=True)
    assert total == 1
    assert [row["component_id"] for row in all_rows] == ["agent-1"]
