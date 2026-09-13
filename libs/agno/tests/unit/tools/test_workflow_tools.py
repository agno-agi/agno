"""Tests for WorkflowTools unique naming across multiple toolkit instances."""

from __future__ import annotations

from pathlib import Path

from agno.agent import Agent
from agno.agent._tools import parse_tools
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.base import RunContext
from agno.tools.workflow import WorkflowTools, _sanitize_tool_name_component
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def _step(prefix: str):
    def _inner(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"{prefix}:{step_input.input}")

    return _inner


def _workflow(tmp_path: Path, *, name: str, workflow_id: str) -> Workflow:
    return Workflow(
        name=name,
        id=workflow_id,
        description=f"Description for {name}",
        db=SqliteDb(db_file=str(tmp_path / f"{workflow_id}.db")),
        steps=[_step(name)],
        telemetry=False,
    )


def test_sanitize_tool_name_component() -> None:
    assert _sanitize_tool_name_component("Blog Workflow") == "blog_workflow"
    assert _sanitize_tool_name_component("wf-blog") == "wf_blog"
    assert _sanitize_tool_name_component("123-start") == "wf_123_start"
    assert _sanitize_tool_name_component("___") == "workflow"


def test_default_names_remain_backward_compatible(tmp_path: Path) -> None:
    wf = _workflow(tmp_path, name="BlogWorkflow", workflow_id="wf-blog")
    tools = WorkflowTools(workflow=wf, enable_think=True, enable_analyze=True)

    assert tools.run_tool_name == "run_workflow"
    assert tools.think_tool_name == "think"
    assert tools.analyze_tool_name == "analyze"
    assert set(tools.functions) == {"run_workflow", "think", "analyze"}
    assert tools.name == "workflow_tools"


def test_tool_name_override(tmp_path: Path) -> None:
    wf = _workflow(tmp_path, name="BlogWorkflow", workflow_id="wf-blog")
    tools = WorkflowTools(workflow=wf, tool_name="run_blog_workflow")

    assert tools.run_tool_name == "run_blog_workflow"
    assert "run_blog_workflow" in tools.functions
    assert "run_workflow" not in tools.functions
    assert "BlogWorkflow" in (tools.functions["run_blog_workflow"].description or "")


def test_name_prefix_applies_to_all_tools(tmp_path: Path) -> None:
    wf = _workflow(tmp_path, name="BlogWorkflow", workflow_id="wf-blog")
    tools = WorkflowTools(
        workflow=wf,
        name_prefix="blog",
        enable_think=True,
        enable_analyze=True,
    )

    assert tools.run_tool_name == "run_workflow_blog"
    assert tools.think_tool_name == "think_blog"
    assert tools.analyze_tool_name == "analyze_blog"
    assert set(tools.functions) == {"run_workflow_blog", "think_blog", "analyze_blog"}
    assert tools.name == "workflow_tools_blog"


def test_unique_derives_prefix_from_workflow_id(tmp_path: Path) -> None:
    wf = _workflow(tmp_path, name="BlogWorkflow", workflow_id="wf-blog")
    tools = WorkflowTools(workflow=wf, unique=True, enable_think=True)

    assert tools.run_tool_name == "run_workflow_wf_blog"
    assert tools.think_tool_name == "think_wf_blog"
    assert "wf-blog" in (tools.functions["run_workflow_wf_blog"].description or "")


def test_multiple_workflow_tools_parse_without_collision(tmp_path: Path) -> None:
    wf_blog = _workflow(tmp_path, name="BlogWorkflow", workflow_id="wf-blog")
    wf_weather = _workflow(tmp_path, name="WeatherWorkflow", workflow_id="wf-weather")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[
            WorkflowTools(workflow=wf_blog, unique=True),
            WorkflowTools(workflow=wf_weather, unique=True),
        ],
        telemetry=False,
    )

    rc = RunContext(run_id="r1", session_id="s1", user_id="u1")
    parsed = parse_tools(agent=agent, tools=list(agent.tools or []), model=agent.model, run_context=rc)
    names = sorted(t.name for t in parsed)

    assert names == ["run_workflow_wf_blog", "run_workflow_wf_weather"]

    blog_tools, weather_tools = agent.tools  # type: ignore[misc]
    assert isinstance(blog_tools, WorkflowTools)
    assert isinstance(weather_tools, WorkflowTools)
    assert blog_tools.workflow.id == "wf-blog"
    assert weather_tools.workflow.id == "wf-weather"
    assert blog_tools.run_tool_name == "run_workflow_wf_blog"
    assert weather_tools.run_tool_name == "run_workflow_wf_weather"
    assert "BlogWorkflow" in (blog_tools.functions["run_workflow_wf_blog"].description or "")
    assert "WeatherWorkflow" in (weather_tools.functions["run_workflow_wf_weather"].description or "")


def test_multiple_workflow_tools_with_explicit_tool_names(tmp_path: Path) -> None:
    wf_blog = _workflow(tmp_path, name="BlogWorkflow", workflow_id="wf-blog")
    wf_weather = _workflow(tmp_path, name="WeatherWorkflow", workflow_id="wf-weather")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[
            WorkflowTools(workflow=wf_blog, tool_name="run_blog_workflow"),
            WorkflowTools(workflow=wf_weather, tool_name="run_weather_workflow"),
        ],
        telemetry=False,
    )

    rc = RunContext(run_id="r1", session_id="s1", user_id="u1")
    parsed = parse_tools(agent=agent, tools=list(agent.tools or []), model=agent.model, run_context=rc)
    names = sorted(t.name for t in parsed)

    assert names == ["run_blog_workflow", "run_weather_workflow"]


def test_duplicate_default_names_still_collide(tmp_path: Path) -> None:
    """Without unique/tool_name/name_prefix, the historical collision remains."""
    wf_blog = _workflow(tmp_path, name="BlogWorkflow", workflow_id="wf-blog")
    wf_weather = _workflow(tmp_path, name="WeatherWorkflow", workflow_id="wf-weather")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[
            WorkflowTools(workflow=wf_blog),
            WorkflowTools(workflow=wf_weather),
        ],
        telemetry=False,
    )

    rc = RunContext(run_id="r1", session_id="s1", user_id="u1")
    parsed = parse_tools(agent=agent, tools=list(agent.tools or []), model=agent.model, run_context=rc)
    assert [t.name for t in parsed] == ["run_workflow"]
