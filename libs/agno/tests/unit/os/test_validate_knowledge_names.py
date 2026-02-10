"""Tests for AgentOS._validate_knowledge_instance_names()."""

from unittest.mock import MagicMock

import pytest

from agno.os.app import AgentOS


def _make_knowledge(name, db_id="db1"):
    """Create a mock Knowledge instance with the given name and contents_db."""
    kb = MagicMock()
    kb.name = name
    kb.contents_db = MagicMock()
    kb.contents_db.id = db_id
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

    def test_duplicate_names_raise(self):
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge("shared_name", "db1"),
            _make_knowledge("shared_name", "db2"),
        ]
        with pytest.raises(ValueError, match="Duplicate knowledge instance names"):
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
        """When knowledge.name is None, the fallback is 'knowledge_{db.id}'."""
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge(None, "same_db"),
            _make_knowledge(None, "same_db"),
        ]
        with pytest.raises(ValueError, match="Duplicate knowledge instance names"):
            os._validate_knowledge_instance_names()

    def test_fallback_name_unique_db_ids(self):
        """Different db.id values produce different fallback names."""
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge(None, "db_a"),
            _make_knowledge(None, "db_b"),
        ]
        os._validate_knowledge_instance_names()

    def test_error_message_contains_duplicate_name(self):
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge("dup_name", "db1"),
            _make_knowledge("dup_name", "db2"),
            _make_knowledge("unique", "db3"),
        ]
        with pytest.raises(ValueError, match="dup_name"):
            os._validate_knowledge_instance_names()

    def test_multiple_different_duplicates(self):
        os = AgentOS.__new__(AgentOS)
        os.knowledge_instances = [
            _make_knowledge("name_a", "db1"),
            _make_knowledge("name_a", "db2"),
            _make_knowledge("name_b", "db3"),
            _make_knowledge("name_b", "db4"),
        ]
        with pytest.raises(ValueError, match="Duplicate knowledge instance names"):
            os._validate_knowledge_instance_names()
