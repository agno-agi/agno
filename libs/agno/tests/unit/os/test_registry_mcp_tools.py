"""
Unit tests for AgentOS collection and startup connection of MCP tools
declared on the registry.

MCP toolkits in ``registry.tools`` are not attached to any agent, team or
workflow, so they are not covered by the per-component collectors. AgentOS
must still connect them in its lifespan: components created from registry
tools (e.g. via StudioTool) serialize a toolkit's functions at persist time,
and an unconnected MCP toolkit has none -- its tools would be silently and
permanently dropped from the persisted config.

Detection is by class name in the MRO (``MCPTools`` / ``MultiMCPTools``), so
the stubs below carry those names and the ``mcp`` package is not required.
"""

from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


class MCPTools(Toolkit):
    """Stub with the MCPTools interface AgentOS relies on: name-based
    detection, async connect()/close(), and functions that only exist after
    connect."""

    def __init__(self, name: str = "stub_mcp"):
        super().__init__(name=name)
        self.connected = False
        self.closed = False

    async def connect(self, force: bool = False):
        self.connected = True
        self.functions["search_docs"] = Function(
            name="search_docs",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            skip_entrypoint_processing=True,
        )

    async def close(self):
        self.closed = True


class MultiMCPTools(Toolkit):
    def __init__(self, name: str = "stub_multi_mcp"):
        super().__init__(name=name)
        self.connected = False

    async def connect(self, force: bool = False):
        self.connected = True

    async def close(self):
        pass


def _agent() -> Agent:
    return Agent(name="Plain Agent", id="plain-agent", telemetry=False)


class TestRegistryMCPToolCollection:
    def test_registry_only_mcp_tools_are_collected(self):
        mcp_tool = MCPTools()
        registry = Registry(tools=[mcp_tool])

        os = AgentOS(agents=[_agent()], registry=registry, telemetry=False)

        assert mcp_tool in os.mcp_tools

    def test_multi_mcp_tools_are_collected(self):
        multi = MultiMCPTools()
        registry = Registry(tools=[multi])

        os = AgentOS(agents=[_agent()], registry=registry, telemetry=False)

        assert multi in os.mcp_tools

    def test_non_mcp_registry_tools_are_not_collected(self):
        plain = Toolkit(name="plain_toolkit")
        registry = Registry(tools=[plain])

        os = AgentOS(agents=[_agent()], registry=registry, telemetry=False)

        assert plain not in os.mcp_tools

    def test_tool_shared_between_agent_and_registry_is_collected_once(self):
        mcp_tool = MCPTools()
        agent = Agent(name="MCP Agent", id="mcp-agent", tools=[mcp_tool], telemetry=False)
        registry = Registry(tools=[mcp_tool])

        os = AgentOS(agents=[agent], registry=registry, telemetry=False)

        assert os.mcp_tools.count(mcp_tool) == 1

    def test_mcp_tool_added_to_registry_after_init_is_collected_by_get_app(self):
        registry = Registry()
        os = AgentOS(agents=[_agent()], registry=registry, telemetry=False)
        late = MCPTools(name="late_mcp")
        registry.tools.append(late)

        os.get_app()

        assert late in os.mcp_tools


class TestRegistryMCPToolStartup:
    def test_registry_mcp_tools_connect_at_startup(self):
        """The app lifespan must connect registry MCP tools, so that their
        functions exist before any Studio operation persists a component."""
        mcp_tool = MCPTools()
        registry = Registry(tools=[mcp_tool])
        os = AgentOS(agents=[_agent()], registry=registry, telemetry=False)

        app = os.get_app()
        assert not mcp_tool.connected

        with TestClient(app):
            assert mcp_tool.connected
            assert mcp_tool.functions  # populated by connect()

        assert mcp_tool.closed
