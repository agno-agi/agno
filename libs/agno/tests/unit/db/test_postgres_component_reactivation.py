"""Regression coverage for PostgreSQL component reactivation boundaries."""

from unittest.mock import patch

import pytest
from sqlalchemy import JSON, BigInteger, Column, Integer, MetaData, String, Table, Text, create_engine

from agno.db.base import ComponentType
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
    )
    metadata.create_all(engine)

    db = PostgresDb(db_engine=engine, db_schema="unused", create_schema=False)

    def get_table(table_type, create_table_if_not_found=False):
        return components if table_type == "components" else None

    with (
        patch.object(db, "_get_table", side_effect=get_table),
        patch.object(db, "_lock_component_graph_writes"),
    ):
        yield db

    db.Session.remove()
    engine.dispose()


def test_upsert_component_does_not_reactivate_soft_deleted_component(postgres_components_db):
    db = postgres_components_db

    created = db.upsert_component(
        component_id="agent-1",
        component_type=ComponentType.AGENT,
        name="before",
    )
    assert created["name"] == "before"

    assert db.delete_component("agent-1") is True
    assert db.get_component("agent-1") is None

    deleted_rows, total = db.list_components(include_deleted=True)
    assert total == 1
    assert deleted_rows[0]["deleted_at"] is not None

    with pytest.raises(ValueError, match="archived and remains reserved"):
        db.upsert_component(
            component_id="agent-1",
            component_type=ComponentType.AGENT,
            name="after",
        )

    all_rows, total = db.list_components(include_deleted=True)
    assert total == 1
    assert [row["component_id"] for row in all_rows] == ["agent-1"]
    assert all_rows[0]["name"] == "before"
    assert all_rows[0]["deleted_at"] is not None
