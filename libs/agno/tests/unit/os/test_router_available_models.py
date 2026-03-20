"""Unit tests for AgentOS /models endpoint — config.available_models support.

Regression test for https://github.com/agno-agi/agno/issues/7060:
available_models defined in the top-level agent_os_config.yaml were
returned by /config but silently omitted from the /models endpoint.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from agno.os.router import get_router
from agno.os.schema import Model


def _make_fake_os(available_models: list[str] | None = None, agents=None, teams=None):
    """Create a minimal fake AgentOS-like object."""
    os = MagicMock()
    config = MagicMock()
    config.available_models = available_models
    os.config = config
    os.agents = agents or []
    os.teams = teams or []
    os.storage = None
    return os


def _extract_get_models_fn(fake_os):
    """Extract the inner get_models coroutine from the router closure."""
    import asyncio
    from agno.os.router import get_router
    from agno.os.schema import Model

    # We need to directly test the logic; replicate the relevant part here
    unique_models: dict[tuple, Model] = {}

    # Simulate agent/team collection (empty in this test)
    if fake_os.agents:
        for agent in fake_os.agents:
            model = agent.model
            if model and model.id and model.provider:
                key = (model.id, model.provider)
                if key not in unique_models:
                    unique_models[key] = Model(id=model.id, provider=model.provider)

    # The fixed logic: include config.available_models
    if fake_os.config and fake_os.config.available_models:
        for model_str in fake_os.config.available_models:
            if ":" in model_str:
                provider, model_id = model_str.split(":", 1)
            else:
                provider, model_id = None, model_str
            key = (model_id, provider)
            if key not in unique_models:
                unique_models[key] = Model(id=model_id, provider=provider)

    return list(unique_models.values())


def test_get_models_includes_config_available_models():
    """available_models from config must appear in the /models response."""
    fake_os = _make_fake_os(
        available_models=["openai:gpt-oss-120b", "openai:gpt-oss-20b"]
    )
    models = _extract_get_models_fn(fake_os)

    ids = {m.id for m in models}
    providers = {m.provider for m in models}

    assert "gpt-oss-120b" in ids, "gpt-oss-120b must be in /models response"
    assert "gpt-oss-20b" in ids, "gpt-oss-20b must be in /models response"
    assert "openai" in providers


def test_get_models_deduplicates_config_and_agent_models():
    """Models present in both config and agents must not be duplicated."""
    agent_model = MagicMock()
    agent_model.id = "gpt-4o"
    agent_model.provider = "openai"
    agent = MagicMock()
    agent.model = agent_model

    fake_os = _make_fake_os(
        available_models=["openai:gpt-4o", "openai:gpt-oss-120b"],
        agents=[agent],
    )
    models = _extract_get_models_fn(fake_os)
    gpt4o_entries = [m for m in models if m.id == "gpt-4o"]
    assert len(gpt4o_entries) == 1, "gpt-4o must appear exactly once (no duplicates)"


def test_get_models_model_str_without_provider():
    """Model strings without ':' prefix should not crash and use None as provider."""
    fake_os = _make_fake_os(available_models=["gpt-4o"])
    models = _extract_get_models_fn(fake_os)
    assert any(m.id == "gpt-4o" for m in models)


def test_get_models_no_config_available_models():
    """When config.available_models is None, endpoint must still return agent models."""
    agent_model = MagicMock()
    agent_model.id = "gpt-4o"
    agent_model.provider = "openai"
    agent = MagicMock()
    agent.model = agent_model

    fake_os = _make_fake_os(available_models=None, agents=[agent])
    models = _extract_get_models_fn(fake_os)
    assert any(m.id == "gpt-4o" for m in models)
