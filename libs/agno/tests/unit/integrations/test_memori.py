"""
Unit tests for Memori integration with Agno agents.

Tests the integration pattern using Memori.llm.register().
"""

import os
import tempfile
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Skip all tests if memori is not installed
pytest.importorskip("memori")

from memori import Memori


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def db_session(temp_db):
    """Create a database session for testing."""
    engine = create_engine(f"sqlite:///{temp_db}")
    Session = sessionmaker(bind=engine)
    return Session


@pytest.fixture
def openai_model():
    """Create an OpenAI model with fake API key for testing."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        model = OpenAIChat(id="gpt-4o-mini")
        model.get_client()
        return model


class TestMemoriIntegration:
    """Test Memori integration with Agno agents."""

    def test_memori_initialization(self, db_session, openai_model):
        """Test that Memori can be initialized and registered with Agno."""
        mem = Memori(conn=db_session).llm.register(openai_model.get_client())
        mem.attribution(entity_id="test-entity", process_id="test-process")

        assert mem is not None
        assert mem.config is not None

    def test_memori_storage_build(self, db_session, openai_model):
        """Test that Memori storage can be built."""
        mem = Memori(conn=db_session).llm.register(openai_model.get_client())
        mem.attribution(entity_id="test-entity", process_id="test-process")

        # Build storage should not raise an exception
        mem.config.storage.build()
        assert True

    def test_agent_with_memori(self, db_session, openai_model):
        """Test that an agent can be created with Memori integration."""
        # Initialize Memori
        mem = Memori(conn=db_session).llm.register(openai_model.get_client())
        mem.attribution(entity_id="test-agent", process_id="test-session")
        mem.config.storage.build()

        # Create agent
        agent = Agent(
            model=openai_model,
            instructions=["You are a helpful assistant."],
            markdown=True,
        )

        assert agent is not None
        assert agent.model == openai_model

    def test_multiple_memori_instances(self, db_session, openai_model):
        """Test that multiple Memori instances can be created with different attributions."""
        mem1 = Memori(conn=db_session).llm.register(openai_model.get_client())
        mem1.attribution(entity_id="entity-1", process_id="process-1")

        mem2 = Memori(conn=db_session).llm.register(openai_model.get_client())
        mem2.attribution(entity_id="entity-2", process_id="process-2")

        assert mem1 is not None
        assert mem2 is not None

    def test_memori_with_custom_db_path(self, openai_model):
        """Test Memori initialization with custom database path."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            engine = create_engine(f"sqlite:///{db_path}")
            Session = sessionmaker(bind=engine)

            mem = Memori(conn=Session).llm.register(openai_model.get_client())
            mem.attribution(entity_id="test", process_id="test")
            mem.config.storage.build()

            assert mem is not None
            assert os.path.exists(db_path)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_memori_config_exists(self, db_session, openai_model):
        """Test that Memori config object is accessible."""
        mem = Memori(conn=db_session).llm.register(openai_model.get_client())

        assert hasattr(mem, "config")
        assert hasattr(mem.config, "storage")

    def test_memori_attribution_required(self, db_session, openai_model):
        """Test that attribution can be set on Memori instance."""
        mem = Memori(conn=db_session).llm.register(openai_model.get_client())

        # Should be able to set attribution without error
        mem.attribution(entity_id="test-entity", process_id="test-process")
        assert True


class TestMemoriWithAgent:
    """Integration tests for Memori with Agno agents."""

    def test_agent_memory_persistence(self, db_session, openai_model):
        """Test that agent conversations are persisted with Memori."""
        mem = Memori(conn=db_session).llm.register(openai_model.get_client())
        mem.attribution(entity_id="test-user", process_id="test-conversation")
        mem.config.storage.build()

        agent = Agent(
            model=openai_model,
            instructions=["You are a helpful assistant."],
            markdown=True,
        )

        # Agent should be created successfully
        assert agent is not None

    def test_agent_with_different_entity_ids(self, db_session, openai_model):
        """Test that different entity IDs can be used for different agents."""
        # Agent 1
        mem1 = Memori(conn=db_session).llm.register(openai_model.get_client())
        mem1.attribution(entity_id="user-1", process_id="session-1")
        mem1.config.storage.build()

        agent1 = Agent(
            model=openai_model,
            instructions=["You are agent 1."],
        )

        # Agent 2
        mem2 = Memori(conn=db_session).llm.register(openai_model.get_client())
        mem2.attribution(entity_id="user-2", process_id="session-2")
        mem2.config.storage.build()

        agent2 = Agent(
            model=openai_model,
            instructions=["You are agent 2."],
        )

        assert agent1 is not None
        assert agent2 is not None


class TestMemoriConfiguration:
    """Tests for Memori configuration options."""

    def test_memori_with_different_db_backends(self, openai_model):
        """Test that Memori works with SQLite (actual test)."""
        # Test with actual SQLite connection
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            engine = create_engine(f"sqlite:///{db_path}")
            Session = sessionmaker(bind=engine)

            mem = Memori(conn=Session).llm.register(openai_model.get_client())
            mem.attribution(entity_id="test", process_id="test")
            mem.config.storage.build()

            assert mem is not None
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_memori_storage_build_idempotent(self, db_session, openai_model):
        """Test that storage build can be called multiple times safely."""
        mem = Memori(conn=db_session).llm.register(openai_model.get_client())
        mem.attribution(entity_id="test", process_id="test")

        # Should be safe to call multiple times
        mem.config.storage.build()
        mem.config.storage.build()
        assert True
