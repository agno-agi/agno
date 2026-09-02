from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.toolkit import FileSystemTools


def _filesystem_tools(agent: Agent) -> list[FileSystemTools]:
    return [tool for tool in agent.tools if isinstance(tool, FileSystemTools)]  # type: ignore[union-attr]


def test_filesystem_true_adds_one_isolated_toolkit(tmp_path):
    agent = Agent(
        id="research-agent",
        db=SqliteDb(db_file=str(tmp_path / "agents.db")),
        filesystem=True,
    )

    agent.initialize_agent()

    assert agent.filesystem_instance is not None
    assert agent.filesystem_instance.namespace == "agents/research-agent"
    assert len(_filesystem_tools(agent)) == 1


def test_explicit_filesystem_uses_supplied_instance(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    filesystem = FileSystem(db, namespace="agents/research-agent")
    agent = Agent(filesystem=filesystem)

    agent.initialize_agent()

    assert agent.filesystem_instance is filesystem
    assert agent.filesystem_instance.namespace == "agents/research-agent"
    assert _filesystem_tools(agent)[0].fs is filesystem


def test_explicit_filesystem_round_trips_with_agent_config(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    filesystem = FileSystem(
        db,
        namespace="agents/research-agent",
        max_file_bytes=2_000,
        max_namespace_bytes=10_000,
    )
    agent = Agent(id="research-agent", db=db, filesystem=filesystem)

    restored = Agent.from_dict(agent.to_dict())
    restored_filesystem = restored.filesystem_instance

    assert restored_filesystem is not None
    assert restored_filesystem.namespace == "agents/research-agent"
    assert restored_filesystem.max_file_bytes == 2_000
    assert restored_filesystem.max_namespace_bytes == 10_000


def test_filesystem_namespace_isolated_by_agent_id(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    first = Agent(id="first-agent", db=db, filesystem=True)
    second = Agent(id="second-agent", db=db, filesystem=True)
    first.initialize_agent()
    second.initialize_agent()

    first.filesystem_instance.write("notes/state.md", "first")  # type: ignore[union-attr]

    assert second.filesystem_instance.read("notes/state.md") is None  # type: ignore[union-attr]


def test_filesystem_namespace_isolated_by_user_id(tmp_path):
    agent = Agent(
        id="research-agent",
        db=SqliteDb(db_file=str(tmp_path / "agents.db")),
        filesystem=True,
    )
    agent._filesystem_user_isolation = True
    agent.initialize_agent()
    alice_files = agent.filesystem_instance.resolve(user_id="alice")  # type: ignore[union-attr]
    bob_files = agent.filesystem_instance.resolve(user_id="bob")  # type: ignore[union-attr]

    alice_files.write("notes/state.md", "alice")

    assert bob_files.read("notes/state.md") is None


def test_managed_filesystem_toolkit_is_not_serialized_as_user_tool(tmp_path):
    agent = Agent(
        id="research-agent",
        db=SqliteDb(db_file=str(tmp_path / "agents.db")),
        filesystem=True,
    )
    agent.initialize_agent()

    config = agent.to_dict()

    assert config["filesystem"] is True
    assert "tools" not in config


def test_deep_copy_rebuilds_managed_filesystem_toolkit(tmp_path):
    agent = Agent(
        id="research-agent",
        db=SqliteDb(db_file=str(tmp_path / "agents.db")),
        filesystem=True,
    )
    agent._filesystem_user_isolation = True
    agent.initialize_agent()

    copied = agent.deep_copy()
    copied.initialize_agent()

    assert copied.filesystem_instance is not agent.filesystem_instance
    assert copied.filesystem_instance.namespace == "users/{user_id}/agents/research-agent"  # type: ignore[union-attr]
    assert len(_filesystem_tools(copied)) == 1
