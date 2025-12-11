"""Unit tests for workflow support in WhatsApp and AgUI interfaces"""
import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.whatsapp import Whatsapp
from agno.workflow import Workflow
from agno.workflow.step import Step


def create_test_workflow():
    """Create a simple test workflow"""
    agent = Agent(
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful assistant"
    )

    step = Step(name="test_step", agent=agent)

    return Workflow(
        name="Test Workflow",
        description="A test workflow for unit testing",
        steps=[step]
    )


# WhatsApp Interface Tests

def test_whatsapp_with_workflow():
    """Test WhatsApp interface initialization with workflow"""
    workflow = create_test_workflow()
    whatsapp = Whatsapp(workflow=workflow)

    assert whatsapp.workflow is not None
    assert whatsapp.workflow.name == "Test Workflow"
    assert whatsapp.type == "whatsapp"
    assert whatsapp.agent is None
    assert whatsapp.team is None


def test_whatsapp_with_agent():
    """Test WhatsApp interface initialization with agent (existing functionality)"""
    agent = Agent(name="Test Agent", model=OpenAIChat(id="gpt-4o-mini"))
    whatsapp = Whatsapp(agent=agent)

    assert whatsapp.agent is not None
    assert whatsapp.workflow is None
    assert whatsapp.team is None


def test_whatsapp_requires_one_entity():
    """Test that WhatsApp requires agent, team, or workflow"""
    with pytest.raises(ValueError, match="requires an agent, team or workflow"):
        Whatsapp()


def test_whatsapp_workflow_router_creation():
    """Test router creation with workflow"""
    workflow = create_test_workflow()
    whatsapp = Whatsapp(workflow=workflow)
    router = whatsapp.get_router()

    assert router is not None
    assert len(router.routes) > 0
    # WhatsApp should have webhook routes
    route_paths = [route.path for route in router.routes]
    assert any("/webhook" in path for path in route_paths)


def test_whatsapp_prefix_configuration():
    """Test custom prefix configuration"""
    workflow = create_test_workflow()
    whatsapp = Whatsapp(workflow=workflow, prefix="/custom-whatsapp")

    assert whatsapp.prefix == "/custom-whatsapp"


def test_whatsapp_tags_configuration():
    """Test custom tags configuration"""
    workflow = create_test_workflow()
    whatsapp = Whatsapp(workflow=workflow, tags=["Custom", "Tags"])

    assert whatsapp.tags == ["Custom", "Tags"]


# AgUI Interface Tests

def test_agui_with_workflow():
    """Test AGUI interface initialization with workflow"""
    workflow = create_test_workflow()
    agui = AGUI(workflow=workflow)

    assert agui.workflow is not None
    assert agui.workflow.name == "Test Workflow"
    assert agui.type == "agui"
    assert agui.agent is None
    assert agui.team is None


def test_agui_with_agent():
    """Test AGUI interface initialization with agent (existing functionality)"""
    agent = Agent(name="Test Agent", model=OpenAIChat(id="gpt-4o-mini"))
    agui = AGUI(agent=agent)

    assert agui.agent is not None
    assert agui.workflow is None
    assert agui.team is None


def test_agui_requires_one_entity():
    """Test that AGUI requires agent, team, or workflow"""
    with pytest.raises(ValueError, match="requires an agent, team or workflow"):
        AGUI()


def test_agui_workflow_router_creation():
    """Test router creation with workflow"""
    workflow = create_test_workflow()
    agui = AGUI(workflow=workflow)
    router = agui.get_router()

    assert router is not None
    assert len(router.routes) > 0
    # AgUI should have the main agui route
    route_paths = [route.path for route in router.routes]
    assert any("/agui" in path or path == "" for path in route_paths)


def test_agui_prefix_configuration():
    """Test custom prefix configuration"""
    workflow = create_test_workflow()
    agui = AGUI(workflow=workflow, prefix="/custom-agui")

    assert agui.prefix == "/custom-agui"


def test_agui_tags_configuration():
    """Test custom tags configuration"""
    workflow = create_test_workflow()
    agui = AGUI(workflow=workflow, tags=["Custom", "AGUI"])

    assert agui.tags == ["Custom", "AGUI"]


# Workflow Properties Tests

def test_workflow_properties_preserved():
    """Test that workflow properties are preserved in interface"""
    workflow = Workflow(
        name="Complex Workflow",
        description="A complex test workflow",
        steps=[Step(name="step1", agent=Agent(model=OpenAIChat(id="gpt-4o-mini")))]
    )

    # Test with WhatsApp
    whatsapp = Whatsapp(workflow=workflow)
    assert whatsapp.workflow.name == "Complex Workflow"
    assert whatsapp.workflow.description == "A complex test workflow"

    # Test with AgUI
    agui = AGUI(workflow=workflow)
    assert agui.workflow.name == "Complex Workflow"
    assert agui.workflow.description == "A complex test workflow"


def test_multiple_interfaces_same_workflow():
    """Test that the same workflow can be used in multiple interfaces"""
    workflow = create_test_workflow()

    whatsapp = Whatsapp(workflow=workflow)
    agui = AGUI(workflow=workflow)

    assert whatsapp.workflow.name == agui.workflow.name
    assert whatsapp.workflow is agui.workflow


# Router Validation Tests

def test_whatsapp_router_has_status_endpoint():
    """Test that WhatsApp router includes status endpoint"""
    workflow = create_test_workflow()
    whatsapp = Whatsapp(workflow=workflow)
    router = whatsapp.get_router()

    route_paths = [route.path for route in router.routes]
    # WhatsApp includes the prefix in the route path
    assert any("status" in path for path in route_paths)


def test_agui_router_has_status_endpoint():
    """Test that AgUI router includes status endpoint"""
    workflow = create_test_workflow()
    agui = AGUI(workflow=workflow)
    router = agui.get_router()

    route_paths = [route.path for route in router.routes]
    assert "/status" in route_paths
