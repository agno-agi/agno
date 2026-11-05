"""Public MCP validates the tools that registration will actually expose."""

import pytest

pytest.importorskip("fastmcp")

from fastmcp import Client  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.postgres import PostgresDb  # noqa: E402
from agno.os import AgentOS, MCPConfig  # noqa: E402
from agno.os.mcp import build_mcp_server  # noqa: E402
from agno.os.public import PublicSurface  # noqa: E402
from agno.team import Team  # noqa: E402
from agno.workflow import Workflow  # noqa: E402


def echo(message: str) -> str:
    return message


@pytest.fixture
def public_os():
    db = PostgresDb(db_engine=create_engine("postgresql+psycopg://unused:unused@127.0.0.1:1/unused"))
    agent = Agent(id="docs-agent")
    team = Team(id="docs-team", members=[agent])
    workflow = Workflow(id="sync-docs", steps=[])
    return AgentOS(
        id="public-mcp",
        db=db,
        agents=[agent],
        teams=[team],
        workflows=[workflow],
        public=PublicSurface(mcp=True),
        auto_provision_dbs=False,
        telemetry=False,
    )


@pytest.mark.asyncio
async def test_public_custom_tools_need_no_lifecycle_override(public_os):
    public_os.mcp = MCPConfig(tools=[echo], default_tools=False, stateless=True)
    public_os.get_app()

    async with Client(build_mcp_server(public_os)) as client:
        assert {tool.name for tool in await client.list_tools()} == {"echo"}
        result = await client.call_tool("echo", {"message": "hello"})
        assert result.content[0].text == "hello"
    assert public_os.mcp_config.lifecycle_tools is False


@pytest.mark.parametrize("kind", ["agents", "teams", "workflows"])
@pytest.mark.parametrize("named", [False, True])
def test_public_exposed_components_reject_explicit_lifecycle_tools(public_os, kind, named):
    component = getattr(public_os, kind)[0]
    tool = component.as_tool(name="docs") if named else component
    public_os.mcp = MCPConfig(tools=[tool], lifecycle_tools=True, stateless=True)

    with pytest.raises(ValueError) as error:
        public_os.get_app()
    message = str(error.value)
    assert "continue_run or cancel_run" in message
    assert "lifecycle_tools=False" in message
    assert 'exclude_tags={"lifecycle"}' in message


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agents", "teams", "workflows"])
@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize(
    "options", [{}, {"lifecycle_tools": False}, {"lifecycle_tools": True, "exclude_tags": {"lifecycle"}}]
)
async def test_public_exposed_components_allow_defaults_and_lifecycle_exclusions(public_os, kind, named, options):
    component = getattr(public_os, kind)[0]
    tool = component.as_tool(name="docs") if named else component
    public_os.mcp = MCPConfig(tools=[tool], stateless=True, **options)
    public_os.get_app()

    async with Client(build_mcp_server(public_os)) as client:
        assert {tool.name for tool in await client.list_tools()} == {"docs" if named else component.id}


@pytest.mark.parametrize("invalid", [{"default_tools": True}, {"stateless": False}])
def test_public_mcp_still_requires_explicit_tools_and_stateless_transport(public_os, invalid):
    config = {"tools": [echo], "default_tools": False, "stateless": True, **invalid}
    public_os.mcp = MCPConfig(**config)
    with pytest.raises(ValueError, match=r"MCPConfig\(tools=\[\.\.\.\], default_tools=False, stateless=True\)"):
        public_os.get_app()
