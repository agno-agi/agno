import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import ComponentRehydrationError
from agno.fs import FileSystem
from agno.fs.toolkit import FileSystemTools
from agno.registry import Registry
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession


def _filesystem_tools(agent: Agent) -> list[FileSystemTools]:
    session_id = "filesystem-config-test"
    tools = agent.get_tools(
        run_response=RunOutput(run_id="run", session_id=session_id),
        run_context=RunContext(run_id="run", session_id=session_id),
        session=AgentSession(session_id=session_id, session_data={}),
    )
    return [tool for tool in tools if isinstance(tool, FileSystemTools)]


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


def test_encoded_namespace_round_trip_does_not_double_encode(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    agent = Agent(id="research-agent", db=db, filesystem=FileSystem(db, namespace="My Namespace"))

    restored = Agent.from_dict(agent.to_dict())

    assert restored.filesystem_instance is not None
    assert restored.filesystem_instance.namespace == "my%20namespace"


def test_template_values_preserve_identity_case(tmp_path):
    filesystem = FileSystem(
        SqliteDb(db_file=str(tmp_path / "agents.db")),
        namespace="Users/{user_id}/Agents/{agent_id}",
    )

    upper = filesystem.resolve(user_id="Alice", agent_id="Research")
    lower = filesystem.resolve(user_id="alice", agent_id="research")

    assert upper.namespace == "users/%41lice/agents/%52esearch"
    assert lower.namespace == "users/alice/agents/research"
    assert upper.namespace != lower.namespace


def test_explicit_filesystem_round_trip_preserves_separate_database(tmp_path):
    agent_db = SqliteDb(id="agent-db", db_file=str(tmp_path / "agents.db"))
    files_db = SqliteDb(id="files-db", db_file=str(tmp_path / "files.db"))
    registry = Registry(dbs=[files_db])
    agent = Agent(
        id="research-agent",
        db=agent_db,
        filesystem=FileSystem(files_db, namespace="agents/research-agent"),
    )

    restored = Agent.from_dict(agent.to_dict(), registry=registry, strict=True)

    assert restored.filesystem_instance is not None
    assert restored.filesystem_instance.backend.db is files_db  # type: ignore[attr-defined]


def test_strict_restore_refuses_missing_filesystem_database(tmp_path):
    agent_db = SqliteDb(id="agent-db", db_file=str(tmp_path / "agents.db"))
    files_db = SqliteDb(id="files-db", db_file=str(tmp_path / "files.db"))
    agent = Agent(id="research-agent", db=agent_db, filesystem=FileSystem(files_db))

    with pytest.raises(ComponentRehydrationError, match="files-db"):
        Agent.from_dict(agent.to_dict(), strict=True)


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


def test_callable_tools_factory_keeps_managed_filesystem(tmp_path):
    agent = Agent(
        id="research-agent",
        db=SqliteDb(db_file=str(tmp_path / "agents.db")),
        filesystem=True,
        tools=lambda: [],
    )
    agent.initialize_agent()

    assert len(_filesystem_tools(agent)) == 1


def test_set_tools_does_not_drop_managed_filesystem(tmp_path):
    agent = Agent(
        id="research-agent",
        db=SqliteDb(db_file=str(tmp_path / "agents.db")),
        filesystem=True,
    )
    agent.initialize_agent()

    agent.set_tools([])

    assert len(_filesystem_tools(agent)) == 1


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


def test_stored_filesystem_agent_rehydrates_namespace_and_toolkit(tmp_path):
    from agno.agent.agent import get_agent_by_id

    db = SqliteDb(id="catalog", db_file=str(tmp_path / "catalog.db"))
    agent = Agent(id="research-agent", db=db, filesystem=True)
    agent.save()

    loaded = get_agent_by_id(db=db, id="research-agent", registry=Registry(dbs=[db]))

    assert loaded is not None
    assert loaded.filesystem_instance is not None
    assert loaded.filesystem_instance.namespace == "agents/research-agent"
    assert len(_filesystem_tools(loaded)) == 1
