"""Unit tests for component, config, and link DB schema definitions.

Tests verify that CASCADE constraints are correctly defined across
the component hierarchy: components -> configs -> links.
"""

import pytest


def _has_sqlalchemy() -> bool:
    try:
        import sqlalchemy  # noqa: F401

        return True
    except ImportError:
        return False


# =============================================================================
# Postgres Schema Tests
# =============================================================================


@pytest.mark.skipif(not _has_sqlalchemy(), reason="SQLAlchemy not installed")
class TestPostgresComponentSchemas:
    """Tests for postgres component/config/link schema definitions."""

    def test_configs_fk_has_cascade(self):
        """component_configs.component_id FK should cascade on delete."""
        from agno.db.postgres.schemas import COMPONENT_CONFIGS_TABLE_SCHEMA

        col = COMPONENT_CONFIGS_TABLE_SCHEMA["component_id"]
        assert col["foreign_key"] == "components.component_id"
        assert col["ondelete"] == "CASCADE"

    def test_links_child_fk_has_cascade(self):
        """component_links.child_component_id FK should cascade on delete."""
        from agno.db.postgres.schemas import COMPONENT_LINKS_TABLE_SCHEMA

        col = COMPONENT_LINKS_TABLE_SCHEMA["child_component_id"]
        assert col["foreign_key"] == "components.component_id"
        assert col["ondelete"] == "CASCADE"

    def test_links_composite_fk_has_cascade(self):
        """component_links composite FK to component_configs should cascade on delete."""
        from agno.db.postgres.schemas import COMPONENT_LINKS_TABLE_SCHEMA

        fks = COMPONENT_LINKS_TABLE_SCHEMA["__foreign_keys__"]
        assert len(fks) == 1

        fk = fks[0]
        assert fk["columns"] == ["parent_component_id", "parent_version"]
        assert fk["ref_table"] == "component_configs"
        assert fk["ref_columns"] == ["component_id", "version"]
        assert fk["ondelete"] == "CASCADE"

    def test_component_table_has_no_fk(self):
        """components table is the root - it should have no foreign keys."""
        from agno.db.postgres.schemas import COMPONENT_TABLE_SCHEMA

        for col_name, col_config in COMPONENT_TABLE_SCHEMA.items():
            if isinstance(col_config, dict):
                assert "foreign_key" not in col_config, f"Unexpected FK on {col_name}"


# =============================================================================
# SQLite Schema Tests
# =============================================================================


@pytest.mark.skipif(not _has_sqlalchemy(), reason="SQLAlchemy not installed")
class TestSqliteComponentSchemas:
    """Tests for sqlite component/config/link schema definitions."""

    def test_configs_fk_has_cascade(self):
        """component_configs.component_id FK should cascade on delete."""
        from agno.db.sqlite.schemas import COMPONENT_CONFIGS_TABLE_SCHEMA

        col = COMPONENT_CONFIGS_TABLE_SCHEMA["component_id"]
        assert col["foreign_key"] == "components.component_id"
        assert col["ondelete"] == "CASCADE"

    def test_links_child_fk_has_cascade(self):
        """component_links.child_component_id FK should cascade on delete."""
        from agno.db.sqlite.schemas import COMPONENT_LINKS_TABLE_SCHEMA

        col = COMPONENT_LINKS_TABLE_SCHEMA["child_component_id"]
        assert col["foreign_key"] == "components.component_id"
        assert col["ondelete"] == "CASCADE"

    def test_links_composite_fk_has_cascade(self):
        """component_links composite FK to component_configs should cascade on delete."""
        from agno.db.sqlite.schemas import COMPONENT_LINKS_TABLE_SCHEMA

        fks = COMPONENT_LINKS_TABLE_SCHEMA["__foreign_keys__"]
        assert len(fks) == 1

        fk = fks[0]
        assert fk["columns"] == ["parent_component_id", "parent_version"]
        assert fk["ref_table"] == "component_configs"
        assert fk["ref_columns"] == ["component_id", "version"]
        assert fk["ondelete"] == "CASCADE"

    def test_links_has_composite_primary_key(self):
        """component_links should define a composite primary key."""
        from agno.db.sqlite.schemas import COMPONENT_LINKS_TABLE_SCHEMA

        pk = COMPONENT_LINKS_TABLE_SCHEMA["__primary_key__"]
        assert pk == ["parent_component_id", "parent_version", "link_kind", "link_key"]

    def test_component_table_has_no_fk(self):
        """components table is the root - it should have no foreign keys."""
        from agno.db.sqlite.schemas import COMPONENTS_TABLE_SCHEMA

        for col_name, col_config in COMPONENTS_TABLE_SCHEMA.items():
            if isinstance(col_config, dict):
                assert "foreign_key" not in col_config, f"Unexpected FK on {col_name}"


# =============================================================================
# Cross-DB Consistency Tests
# =============================================================================


@pytest.mark.skipif(not _has_sqlalchemy(), reason="SQLAlchemy not installed")
class TestSchemaConsistency:
    """Tests that postgres and sqlite schemas are consistent for component tables."""

    def test_configs_cascade_matches(self):
        """Both postgres and sqlite should have CASCADE on configs.component_id FK."""
        from agno.db.postgres.schemas import COMPONENT_CONFIGS_TABLE_SCHEMA as pg_configs
        from agno.db.sqlite.schemas import COMPONENT_CONFIGS_TABLE_SCHEMA as sqlite_configs

        assert pg_configs["component_id"]["ondelete"] == sqlite_configs["component_id"]["ondelete"]

    def test_links_child_cascade_matches(self):
        """Both postgres and sqlite should have CASCADE on links.child_component_id FK."""
        from agno.db.postgres.schemas import COMPONENT_LINKS_TABLE_SCHEMA as pg_links
        from agno.db.sqlite.schemas import COMPONENT_LINKS_TABLE_SCHEMA as sqlite_links

        assert pg_links["child_component_id"]["ondelete"] == sqlite_links["child_component_id"]["ondelete"]

    def test_links_composite_fk_cascade_matches(self):
        """Both postgres and sqlite should have CASCADE on links composite FK."""
        from agno.db.postgres.schemas import COMPONENT_LINKS_TABLE_SCHEMA as pg_links
        from agno.db.sqlite.schemas import COMPONENT_LINKS_TABLE_SCHEMA as sqlite_links

        pg_fk = pg_links["__foreign_keys__"][0]
        sqlite_fk = sqlite_links["__foreign_keys__"][0]

        assert pg_fk["ondelete"] == sqlite_fk["ondelete"]
        assert pg_fk["columns"] == sqlite_fk["columns"]
        assert pg_fk["ref_table"] == sqlite_fk["ref_table"]
        assert pg_fk["ref_columns"] == sqlite_fk["ref_columns"]

    def test_configs_columns_match(self):
        """Postgres and sqlite configs schemas should have the same column names."""
        from agno.db.postgres.schemas import COMPONENT_CONFIGS_TABLE_SCHEMA as pg_configs
        from agno.db.sqlite.schemas import COMPONENT_CONFIGS_TABLE_SCHEMA as sqlite_configs

        pg_cols = {k for k in pg_configs if not k.startswith("_")}
        sqlite_cols = {k for k in sqlite_configs if not k.startswith("_")}
        # Postgres has deleted_at, sqlite doesn't - that's an existing difference
        assert pg_cols - sqlite_cols <= {"deleted_at"}
        assert sqlite_cols - pg_cols == set()

    def test_links_columns_match(self):
        """Postgres and sqlite links schemas should have the same column names."""
        from agno.db.postgres.schemas import COMPONENT_LINKS_TABLE_SCHEMA as pg_links
        from agno.db.sqlite.schemas import COMPONENT_LINKS_TABLE_SCHEMA as sqlite_links

        pg_cols = {k for k in pg_links if not k.startswith("_")}
        sqlite_cols = {k for k in sqlite_links if not k.startswith("_")}
        assert pg_cols == sqlite_cols


# =============================================================================
# Table Creation Tests (ondelete propagation to ForeignKeyConstraint)
# =============================================================================


@pytest.mark.skipif(not _has_sqlalchemy(), reason="SQLAlchemy not installed")
class TestForeignKeyConstraintOndelete:
    """Tests that ondelete is correctly propagated to SQLAlchemy ForeignKeyConstraint."""

    def test_composite_fk_ondelete_propagation(self):
        """Composite FK with ondelete should produce a ForeignKeyConstraint with ondelete."""
        from sqlalchemy import Column, Integer, MetaData, String, Table
        from sqlalchemy.schema import ForeignKeyConstraint, PrimaryKeyConstraint

        metadata = MetaData()

        # Create parent tables
        Table("components", metadata, Column("component_id", String, primary_key=True))
        Table(
            "component_configs",
            metadata,
            Column("component_id", String, primary_key=True),
            Column("version", Integer, primary_key=True),
        )

        # Create links table with composite FK that has ondelete
        links_table = Table(
            "component_links",
            metadata,
            Column("parent_component_id", String, nullable=False),
            Column("parent_version", Integer, nullable=False),
            Column("link_kind", String, nullable=False),
            Column("link_key", String, nullable=False),
        )
        links_table.append_constraint(
            PrimaryKeyConstraint("parent_component_id", "parent_version", "link_kind", "link_key")
        )
        links_table.append_constraint(
            ForeignKeyConstraint(
                ["parent_component_id", "parent_version"],
                ["component_configs.component_id", "component_configs.version"],
                name="component_links_parent_component_id_parent_version_fkey",
                ondelete="CASCADE",
            )
        )

        # Verify the FK constraint has ondelete
        fk_constraints = [c for c in links_table.constraints if isinstance(c, ForeignKeyConstraint)]
        assert len(fk_constraints) == 1
        assert fk_constraints[0].ondelete == "CASCADE"
