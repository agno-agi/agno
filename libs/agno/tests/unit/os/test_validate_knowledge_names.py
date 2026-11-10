"""Tests for AgentOS._validate_knowledge_instance_names()."""

from unittest.mock import MagicMock

import pytest

from agno.os.app import AgentOS


def _make_knowledge(name, db_id="db1", table_name="knowledge"):
    """Create a mock Knowledge instance with the given name, contents_db, and table."""
    kb = MagicMock()
    kb.name = name
    kb.contents_db = MagicMock()
    kb.contents_db.id = db_id
    kb.contents_db.knowledge_table_name = table_name
    return kb


def _make_knowledge_no_db(name=None):
    """Create a mock Knowledge instance with no contents_db."""
    kb = MagicMock()
    kb.name = name
    kb.contents_db = None
    return kb


class TestValidateKnowledgeInstanceNames:
    def test_unique_names_pass(self):
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge("kb_alpha", "db1"),
            _make_knowledge("kb_beta", "db2"),
            _make_knowledge("kb_gamma", "db3"),
        ]
        # Should not raise
        os._validate_knowledge_instance_names()

    def test_same_name_different_db_passes(self):
        """Same name with different db_id is allowed (different tuple key)."""
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge("shared_name", "db1"),
            _make_knowledge("shared_name", "db2"),
        ]
        # Should not raise — different db_id makes the tuple unique
        os._validate_knowledge_instance_names()

    def test_same_name_different_table_passes(self):
        """Same name + same db but different table is allowed."""
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge("shared_name", "db1", "table_a"),
            _make_knowledge("shared_name", "db1", "table_b"),
        ]
        os._validate_knowledge_instance_names()

    def test_duplicate_name_db_table_raises(self):
        """Same (name, db_id, table) tuple should raise."""
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge("shared_name", "db1", "knowledge"),
            _make_knowledge("shared_name", "db1", "knowledge"),
        ]
        with pytest.raises(ValueError, match="Duplicate knowledge instances"):
            os._validate_knowledge_instance_names()

    def test_empty_list_passes(self):
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = []
        os._validate_knowledge_instance_names()

    def test_no_contents_db_skipped(self):
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge_no_db("orphan"),
            _make_knowledge("valid", "db1"),
        ]
        # The one without contents_db is skipped; no duplicate => passes
        os._validate_knowledge_instance_names()

    def test_fallback_name_from_db_id(self):
        """When knowledge.name is None, the fallback is 'knowledge_{db.id}'.
        Two with same db_id and same table => duplicate tuple."""
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge(None, "same_db", "knowledge"),
            _make_knowledge(None, "same_db", "knowledge"),
        ]
        with pytest.raises(ValueError, match="Duplicate knowledge instances"):
            os._validate_knowledge_instance_names()

    def test_fallback_name_unique_db_ids(self):
        """Different db.id values produce different fallback names and different tuple keys."""
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge(None, "db_a"),
            _make_knowledge(None, "db_b"),
        ]
        os._validate_knowledge_instance_names()

    def test_error_message_contains_duplicate_name(self):
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge("dup_name", "db1", "knowledge"),
            _make_knowledge("dup_name", "db1", "knowledge"),
            _make_knowledge("unique", "db3"),
        ]
        with pytest.raises(ValueError, match="dup_name"):
            os._validate_knowledge_instance_names()

    def test_multiple_different_duplicates(self):
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge("name_a", "db1", "tbl"),
            _make_knowledge("name_a", "db1", "tbl"),
            _make_knowledge("name_b", "db3", "tbl"),
            _make_knowledge("name_b", "db3", "tbl"),
        ]
        with pytest.raises(ValueError, match="Duplicate knowledge instances"):
            os._validate_knowledge_instance_names()
