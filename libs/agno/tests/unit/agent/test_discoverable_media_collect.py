"""Tests for DiscoverableTools media-collection branch in determine_tools_for_model.

Pins three branches:
  1. No DiscoverableTools - collect_joint_* called unconditionally (pre-PR behavior).
  2. DT present + pool has a media-needing tool - collect_joint_* called.
  3. DT present + neither upfront nor pool needs media - collect_joint_* NOT called.
"""

from unittest.mock import MagicMock

import pytest

from agno.agent._tools import determine_tools_for_model
from agno.agent.agent import Agent
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.session.agent import AgentSession
from agno.tools.discoverable import DiscoverableTools
from agno.tools.toolkit import Toolkit


def _plain_tool(query: str) -> str:
    """Plain tool with no media params."""
    return query


def _image_tool(images: list) -> str:
    """Tool that consumes images."""
    return "ok"


class _AsyncImageKit(Toolkit):
    def __init__(self):
        async def async_image_op(images: list) -> str:
            """Async media op."""
            return "ok"

        super().__init__(name="async_img", tools=[async_image_op])


def _mock_model():
    model = MagicMock()
    model.supports_native_structured_outputs = False
    return model


def _run_response():
    return RunOutput(run_id="r", session_id="s", agent_id="a")


def _run_context():
    return RunContext(run_id="r", session_id="s")


def _session():
    return AgentSession(session_id="s")


@pytest.fixture
def patched_collectors(monkeypatch):
    """Patch the four collect_joint_* helpers and return their mocks."""
    from agno.agent import _tools as agent_tools

    mocks = {
        "images": MagicMock(return_value=None),
        "files": MagicMock(return_value=None),
        "audios": MagicMock(return_value=None),
        "videos": MagicMock(return_value=None),
    }
    monkeypatch.setattr(agent_tools, "collect_joint_images", mocks["images"])
    monkeypatch.setattr(agent_tools, "collect_joint_files", mocks["files"])
    monkeypatch.setattr(agent_tools, "collect_joint_audios", mocks["audios"])
    monkeypatch.setattr(agent_tools, "collect_joint_videos", mocks["videos"])
    return mocks


def test_no_discoverable_tools_collects_unconditionally(patched_collectors):
    """Without DT, agents pay no needs-media scan and media is always collected."""
    agent = Agent(tools=[_plain_tool])

    determine_tools_for_model(
        agent=agent,
        model=_mock_model(),
        processed_tools=agent.tools,
        run_response=_run_response(),
        run_context=_run_context(),
        session=_session(),
        async_mode=False,
    )

    # Pre-PR behavior: collectors invoked unconditionally when tools are present.
    assert patched_collectors["images"].called
    assert patched_collectors["files"].called
    assert patched_collectors["audios"].called
    assert patched_collectors["videos"].called


def test_discoverable_with_media_tool_in_pool_collects(patched_collectors):
    """Pool contains a media-needing tool - needs_media scan returns True, collectors fire."""
    dt = DiscoverableTools(tools=[_image_tool])
    agent = Agent(tools=[dt])

    determine_tools_for_model(
        agent=agent,
        model=_mock_model(),
        processed_tools=agent.tools,
        run_response=_run_response(),
        run_context=_run_context(),
        session=_session(),
        async_mode=False,
    )

    assert patched_collectors["images"].called
    assert patched_collectors["files"].called


def test_discoverable_without_media_tool_skips_collect(patched_collectors):
    """Neither upfront nor pool tools need media - optimization skips collection."""
    dt = DiscoverableTools(tools=[_plain_tool])
    agent = Agent(tools=[dt])

    determine_tools_for_model(
        agent=agent,
        model=_mock_model(),
        processed_tools=agent.tools,
        run_response=_run_response(),
        run_context=_run_context(),
        session=_session(),
        async_mode=False,
    )

    assert not patched_collectors["images"].called
    assert not patched_collectors["files"].called
    assert not patched_collectors["audios"].called
    assert not patched_collectors["videos"].called


def test_discoverable_async_only_media_tool_detected_in_async_mode(patched_collectors):
    """Async-only toolkit with media param must be seen via _async_registry when async_mode=True."""
    dt = DiscoverableTools(tools=[_AsyncImageKit()])
    agent = Agent(tools=[dt])

    determine_tools_for_model(
        agent=agent,
        model=_mock_model(),
        processed_tools=agent.tools,
        run_response=_run_response(),
        run_context=_run_context(),
        session=_session(),
        async_mode=True,
    )

    assert patched_collectors["images"].called
