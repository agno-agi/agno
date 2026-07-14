from agno.agent import Agent
from agno.os import AgentOS
from agno.team.team import Team
from agno.tools.mcp import MCPTools, MultiMCPTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


def test_agent_mcp_tools_are_registered():
    """Test that agent MCP tools are registered"""
    mcp_tools = MCPTools("npm fake-command")
    agent = Agent(tools=[mcp_tools])
    assert agent.tools is not None
    assert agent.tools[0] is mcp_tools

    # Asserting the MCP tools were registered
    agent_os = AgentOS(agents=[agent])
    assert agent_os.mcp_tools is not None
    assert agent_os.mcp_tools[0] is mcp_tools


def test_multiple_agent_mcp_tools_are_registered():
    """Test that agent MCP tools are registered"""
    mcp_tools1 = MCPTools("npm fake-command")
    mcp_tools2 = MCPTools("npm fake-command2")
    agent = Agent(tools=[mcp_tools1, mcp_tools2])
    assert agent.tools is not None
    assert len(agent.tools) == 2

    agent_os = AgentOS(agents=[agent])

    # Asserting all MCP tools were found and registered
    assert agent_os.mcp_tools is not None
    assert len(agent_os.mcp_tools) == 2
    assert mcp_tools1 in agent_os.mcp_tools
    assert mcp_tools2 in agent_os.mcp_tools


def test_team_mcp_tools_are_registered():
    """Test that team MCP tools are registered"""
    mcp_tools = MCPTools("npm fake-command")
    team = Team(tools=[mcp_tools], members=[])
    assert team.tools is not None
    assert team.tools[0] is mcp_tools

    # Asserting the MCP tools were registered
    agent_os = AgentOS(teams=[team])
    assert agent_os.mcp_tools is not None
    assert agent_os.mcp_tools[0] is mcp_tools


def test_multiple_team_mcp_tools_are_registered():
    """Test that team MCP tools are registered"""
    mcp_tools = MCPTools("npm fake-command")
    mcp_tools2 = MCPTools("npm fake-command2")
    team = Team(tools=[mcp_tools, mcp_tools2], members=[])
    assert team.tools is not None
    assert len(team.tools) == 2

    # Asserting the MCP tools were registered
    agent_os = AgentOS(teams=[team])
    assert agent_os.mcp_tools is not None
    assert len(agent_os.mcp_tools) == 2
    assert mcp_tools in agent_os.mcp_tools
    assert mcp_tools2 in agent_os.mcp_tools


def test_nested_team_mcp_tools_are_registered():
    """Test that team MCP tools are registered"""
    mcp_tools = MCPTools("npm fake-command")
    agent = Agent(tools=[mcp_tools])
    assert agent.tools is not None
    assert agent.tools[0] is mcp_tools

    mcp_tools2 = MCPTools("npm fake-command")
    nested_team = Team(tools=[mcp_tools2], members=[agent])
    assert nested_team.tools is not None
    assert nested_team.tools[0] is mcp_tools2

    mcp_tools3 = MCPTools("npm fake-command2")
    team = Team(tools=[mcp_tools3], members=[nested_team])
    assert team.tools is not None
    assert team.tools[0] is mcp_tools3

    # Asserting the MCP tools were registered
    agent_os = AgentOS(teams=[team])
    assert agent_os.mcp_tools is not None
    assert len(agent_os.mcp_tools) == 3
    assert mcp_tools in agent_os.mcp_tools
    assert mcp_tools2 in agent_os.mcp_tools
    assert mcp_tools3 in agent_os.mcp_tools


def test_workflow_with_agent_step_mcp_tools_are_registered():
    """Test that workflow MCP tools are registered from agent steps"""
    mcp_tools = MCPTools("npm fake-command")
    agent = Agent(tools=[mcp_tools])
    step = Step(agent=agent)
    workflow = Workflow(steps=[step])

    # Asserting the MCP tools were registered
    agent_os = AgentOS(workflows=[workflow])
    assert agent_os.mcp_tools is not None
    assert agent_os.mcp_tools[0] is mcp_tools


def test_workflow_with_team_step_mcp_tools_are_registered():
    """Test that workflow MCP tools are registered from team steps"""
    mcp_tools = MCPTools("npm fake-command")
    team = Team(tools=[mcp_tools], members=[])
    step = Step(team=team)
    workflow = Workflow(steps=[step])

    # Asserting the MCP tools were registered
    agent_os = AgentOS(workflows=[workflow])
    assert agent_os.mcp_tools is not None
    assert agent_os.mcp_tools[0] is mcp_tools


def test_workflow_with_nested_structures_mcp_tools_are_registered():
    """Test that workflow MCP tools are registered from complex nested structures"""
    agent_mcp_tools = MCPTools("npm fake-command")
    agent = Agent(tools=[agent_mcp_tools])

    team_mcp_tools = MCPTools("npm fake-command2")
    team = Team(tools=[team_mcp_tools], members=[])

    agent_step = Step(agent=agent)
    team_step = Step(team=team)
    workflow = Workflow(steps=[agent_step, team_step])

    # Asserting all MCP tools were registered
    agent_os = AgentOS(workflows=[workflow])
    assert agent_os.mcp_tools is not None
    assert len(agent_os.mcp_tools) == 2
    assert agent_mcp_tools in agent_os.mcp_tools
    assert team_mcp_tools in agent_os.mcp_tools


def test_mcp_tools_are_not_registered_multiple_times():
    """Test that MCP tools are not registered multiple times when present in multiple places"""
    agent_mcp_tools = MCPTools("npm fake-command")
    agent = Agent(tools=[agent_mcp_tools])
    agent2 = Agent(tools=[agent_mcp_tools])

    team_mcp_tools = MCPTools("npm fake-command2")
    team = Team(tools=[team_mcp_tools], members=[agent, agent2])

    agent_step = Step(agent=agent)
    team_step = Step(team=team)
    workflow = Workflow(steps=[agent_step, team_step])

    # Asserting all MCP tools were registered
    agent_os = AgentOS(workflows=[workflow], agents=[agent, agent2], teams=[team])
    assert agent_os.mcp_tools is not None
    assert len(agent_os.mcp_tools) == 2
    assert agent_mcp_tools in agent_os.mcp_tools
    assert team_mcp_tools in agent_os.mcp_tools


def test_subclasses_are_registered():
    """Test that subclasses of MCPTools and MultiMCPTools also are registered."""

    class MCPSubclass(MCPTools):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

    class MultiMCPSubclass(MultiMCPTools):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

    mcp_subclass_instance = MCPSubclass("npm fake-command")
    multi_mcp_subclass_instance = MultiMCPSubclass(commands=["npm fake-command"])

    # Assert the tools are registered in the Agent
    agent = Agent(tools=[mcp_subclass_instance, multi_mcp_subclass_instance])
    assert agent.tools is not None
    assert len(agent.tools) == 2

    # Assert the tools are registered in the AgentOS
    agent_os = AgentOS(agents=[agent])
    assert agent_os.mcp_tools is not None
    assert len(agent_os.mcp_tools) == 2
    assert mcp_subclass_instance in agent_os.mcp_tools
    assert multi_mcp_subclass_instance in agent_os.mcp_tools
