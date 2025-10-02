from agno.agent import Agent
from agno.os.app import AgentOS
from agno.os.interfaces.a2a import A2A


def test_a2a_interface_parameter():
    """Test that the A2A interface is setup correctly using the a2a_interface parameter."""
    # Setup OS with the a2a_interface parameter
    agent = Agent()
    agent_os = AgentOS(agents=[agent], a2a_interface=True)
    app = agent_os.get_app()

    # Assert that the app has the A2A interface
    assert app is not None
    assert any([isinstance(interface, A2A) for interface in agent_os.interfaces])
    assert "/a2a/agents/{id}" in [route.path for route in app.routes]


def test_a2a_interface_in_interfaces_parameter():
    """Test that the A2A interface is setup correctly using the interfaces parameter."""
    # Setup OS with the a2a_interface parameter
    interface_agent = Agent(name="interface-agent")
    os_agent = Agent(name="os-agent")
    agent_os = AgentOS(agents=[os_agent], interfaces=[A2A(agents=[interface_agent])])
    app = agent_os.get_app()

    # Assert setting the app didn't raise and the A2A interface is the expected one
    assert app is not None
    assert any([isinstance(interface, A2A) for interface in agent_os.interfaces])
    assert "/a2a/agents/{id}" in [route.path for route in app.routes]
