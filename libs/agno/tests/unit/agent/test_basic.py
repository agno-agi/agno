from agno.agent.agent import Agent


def test_set_id():
    agent = Agent(
        id="test_id",
    )
    agent.set_id()
    assert agent.id == "test_id"


def test_set_id_from_name():
    agent = Agent(
        name="Test Name",
    )
    agent.set_id()

    # Asserting the set_id method uses the name to generate the id
    agent_id = agent.id
    expected_id = "test-name"
    assert expected_id == agent_id

    # Asserting the set_id method is deterministic
    agent.set_id()
    assert agent.id == agent_id


def test_set_id_auto_generated():
    agent = Agent()
    agent.set_id()
    # Auto-generated IDs are Docker-style: adjective-name-hex8
    parts = agent.id.split("-")
    assert len(parts) == 3, f"Expected 3 parts, got {len(parts)}: {agent.id}"
    assert parts[0].isalpha() and parts[0].islower()  # adjective
    assert parts[1].isalpha() and parts[1].islower()  # name
    assert len(parts[2]) == 8  # hex suffix
    int(parts[2], 16)  # must be valid hex


def test_deep_copy():
    """Test that Agent.deep_copy() works with all dataclass fields.

    This test ensures that all dataclass fields with defaults are properly
    handled by deep_copy(), preventing TypeError for unexpected keyword arguments.
    """
    # Create agent with minimal configuration
    # The key is that deep_copy will try to pass ALL dataclass fields to __init__
    original = Agent(name="test-agent")

    # This should not raise TypeError about unexpected keyword arguments
    copied = original.deep_copy()

    # Verify it's a different instance but with same values
    assert copied is not original
    assert copied.name == original.name
    assert copied.user_message_role == "user"
    assert copied.system_message_role == "system"

    # Test deep_copy with update
    updated = original.deep_copy(update={"name": "updated-agent"})
    assert updated.name == "updated-agent"


def test_deep_copy_of_a_subclass_that_forwards_with_kwargs():
    """deep_copy rebuilds through the class __init__ and keeps only the fields that
    signature names. A subclass forwarding with **kwargs names none of them, so
    without a VAR_KEYWORD check every field is skipped and the copy comes back blank.
    """
    from agno.agent import Agent

    class Forwarding(Agent):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class WithOwnArg(Agent):
        def __init__(self, flavour="vanilla", **kwargs):
            self.flavour = flavour
            super().__init__(**kwargs)

    for cls in (Forwarding, WithOwnArg):
        original = cls(id="a1", name="Helper", instructions="be helpful")
        copied = original.deep_copy()
        assert copied is not original
        assert type(copied) is cls
        assert copied.id == "a1"
        assert copied.name == "Helper"
        assert copied.instructions == "be helpful"


def test_deep_copy_of_a_team_and_workflow_subclass_that_forwards_with_kwargs():
    from agno.agent import Agent
    from agno.team import Team
    from agno.workflow import Workflow
    from agno.workflow.step import Step

    member = Agent(id="leaf", name="Leaf")

    class ForwardingTeam(Team):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class ForwardingWorkflow(Workflow):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    team = ForwardingTeam(id="t1", name="Squad", members=[member])
    team_copy = team.deep_copy()
    assert team_copy.id == "t1" and team_copy.name == "Squad"
    assert team_copy.members and team_copy.members[0] is not member

    workflow = ForwardingWorkflow(id="w1", name="Flow", steps=[Step(name="s", agent=member)])
    workflow_copy = workflow.deep_copy()
    assert workflow_copy.id == "w1" and workflow_copy.name == "Flow"
