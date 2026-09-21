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
    assert agent.filesystem_instance.namespace == "research-agent"
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


def test_managed_filesystem_preserves_agent_id_case(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    upper = Agent(id="Research", db=db, filesystem=True)
    lower = Agent(id="research", db=db, filesystem=True)
    upper.initialize_agent()
    lower.initialize_agent()
    upper_filesystem = upper.filesystem_instance
    lower_filesystem = lower.filesystem_instance
    assert upper_filesystem is not None
    assert lower_filesystem is not None

    upper_filesystem.write("state.md", "upper")

    assert upper_filesystem.namespace == "%52esearch"
    assert lower_filesystem.read("state.md") is None


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
    assert copied.filesystem_instance.namespace == "users/{user_id}/research-agent"  # type: ignore[union-attr]
    assert len(_filesystem_tools(copied)) == 1


def test_stored_filesystem_agent_rehydrates_namespace_and_toolkit(tmp_path):
    from agno.agent.agent import get_agent_by_id

    db = SqliteDb(id="catalog", db_file=str(tmp_path / "catalog.db"))
    agent = Agent(id="research-agent", db=db, filesystem=True)
    agent.save()

    loaded = get_agent_by_id(db=db, id="research-agent", registry=Registry(dbs=[db]))

    assert loaded is not None
    assert loaded.filesystem_instance is not None
    assert loaded.filesystem_instance.namespace == "research-agent"
    assert len(_filesystem_tools(loaded)) == 1


def test_toolkit_setting_keeps_its_permissions(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    filesystem = FileSystem(db, namespace="research/decisions")
    toolkit = filesystem.tools(read_only=True)
    agent = Agent(id="answerer", db=db, filesystem=toolkit)

    agent.initialize_agent()

    assert agent.filesystem_instance is filesystem
    assert _filesystem_tools(agent) == [toolkit]
    assert sorted(toolkit.functions) == ["list_files", "read_file", "search_content"]
    assert agent.filesystems == [(filesystem, True)]


def test_toolkit_setting_round_trips_permissions(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    toolkit = FileSystem(db, namespace="research/decisions").tools(read_only=True, add_instructions=True)
    agent = Agent(id="answerer", db=db, filesystem=toolkit)

    restored = Agent.from_dict(agent.to_dict())

    assert isinstance(restored.filesystem, FileSystemTools)
    assert restored.filesystem.read_only is True
    assert restored.filesystem.add_instructions is True
    assert restored.filesystem.fs.namespace == "research/decisions"
    assert sorted(restored.filesystem.functions) == ["list_files", "read_file", "search_content"]


def test_filesystems_lists_manually_attached_toolkits(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "agents.db"))
    shared = FileSystem(db, namespace="shared")
    agent = Agent(id="reader", db=db, tools=[shared.tools(read_only=True)])

    assert agent.filesystem_instance is None
    assert agent.filesystems == [(shared, True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_tools", [False, True])
async def test_multiple_filesystems_route_tools_and_preserve_permissions(tmp_path, async_tools):
    db = SqliteDb(db_file=str(tmp_path / "files.db"))
    drafts = FileSystem(db, namespace="analyst/drafts")
    handbook = FileSystem(db, namespace="team/handbook")
    handbook.write("style.md", "Lead with the conclusion.")
    reader = FileSystemTools(fs=handbook, read_only=True, add_instructions=True)
    agent = Agent(id="analyst", filesystem=[drafts, reader])

    if async_tools:
        tools = await agent.aget_tools(
            run_response=RunOutput(run_id="run", session_id="multi-fs"),
            run_context=RunContext(run_id="run", session_id="multi-fs"),
            session=AgentSession(session_id="multi-fs", session_data={}),
        )
        attached = [tool for tool in tools if isinstance(tool, FileSystemTools)]
        functions = {name: function for tool in attached for name, function in tool.get_async_functions().items()}
    else:
        attached = _filesystem_tools(agent)
        functions = {name: function for tool in attached for name, function in tool.get_functions().items()}

    writer = functions["fs_1_analyst_drafts_write_file"].entrypoint
    read_draft = functions["fs_1_analyst_drafts_read_file"].entrypoint
    read_handbook = functions["fs_2_team_handbook_read_file"].entrypoint
    assert writer is not None and read_draft is not None and read_handbook is not None
    if async_tools:
        await writer(path="style.md", content="My draft.")
        draft_text = await read_draft(path="style.md")
        handbook_text = await read_handbook(path="style.md")
    else:
        writer(path="style.md", content="My draft.")
        draft_text = read_draft(path="style.md")
        handbook_text = read_handbook(path="style.md")

    assert "My draft." in draft_text
    assert "Lead with the conclusion." in handbook_text
    assert "fs_2_team_handbook_write_file" not in functions
    assert agent.filesystems == [(drafts, False), (handbook, True)]
    assert agent.filesystem_instance is drafts
    assert sorted(reader.functions) == ["list_files", "read_file", "search_content"]
    assert attached[1] is not reader
    assert attached[1].instructions is not None
    assert "fs_2_team_handbook_read_file" in attached[1].instructions


def test_multiple_filesystems_round_trip_distinct_databases_and_tool_restrictions(tmp_path):
    from agno.os.utils import collect_components_from_agent

    first_db = SqliteDb(id="drafts-db", db_file=str(tmp_path / "drafts.db"))
    second_db = SqliteDb(id="handbook-db", db_file=str(tmp_path / "handbook.db"))
    drafts = FileSystem(first_db, namespace="drafts")
    handbook = FileSystem(second_db, namespace="handbook")
    agent = Agent(
        id="analyst",
        filesystem=[
            drafts.tools(include_tools=["read_file", "write_file"], requires_confirmation_tools=["write_file"]),
            handbook.tools(read_only=True, include_tools=["read_file"]),
        ],
    )
    registry = Registry()
    collect_components_from_agent(agent, registry, visited=set())

    restored = Agent.from_dict(agent.to_dict(), registry=registry, strict=True)
    toolkits = _filesystem_tools(restored)

    assert toolkits[0].fs.backend.db is first_db
    assert toolkits[1].fs.backend.db is second_db
    assert sorted(toolkits[0].functions) == ["fs_1_drafts_read_file", "fs_1_drafts_write_file"]
    assert list(toolkits[1].functions) == ["fs_2_handbook_read_file"]
    assert toolkits[0].functions["fs_1_drafts_write_file"].requires_confirmation is True
    assert toolkits[0].async_functions["fs_1_drafts_write_file"].requires_confirmation is True
    assert toolkits[1].read_only is True


def test_multiple_filesystems_disambiguate_normalized_namespace_names(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "files.db"))
    agent = Agent(filesystem=[FileSystem(db, namespace="a/b"), FileSystem(db, namespace="a_b")])

    first, second = _filesystem_tools(agent)

    assert "fs_1_a_b_read_file" in first.functions
    assert "fs_2_a_b_read_file" in second.functions
    assert first.functions.keys().isdisjoint(second.functions)


@pytest.mark.parametrize("invalid", [True, False, None, "drafts", []])
def test_filesystem_lists_reject_non_stores(invalid):
    agent = Agent(filesystem=[invalid])

    with pytest.raises(TypeError, match="filesystem lists must contain only"):
        agent.initialize_agent()


def test_single_item_filesystem_list_keeps_tool_names_and_empty_list_disables(tmp_path):
    filesystem = FileSystem(SqliteDb(db_file=str(tmp_path / "files.db")), namespace="drafts")
    agent = Agent(filesystem=[filesystem])

    assert "read_file" in _filesystem_tools(agent)[0].functions
    assert _filesystem_tools(Agent(filesystem=[])) == []


def test_filesystem_list_deep_copy_owns_list_and_shares_stores(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "files.db"))
    first = FileSystem(db, namespace="drafts")
    second = FileSystem(db, namespace="handbook")
    agent = Agent(filesystem=[first, second])

    copied = agent.deep_copy()

    assert copied.filesystem is not agent.filesystem
    assert copied.filesystem == [first, second]
    assert copied.filesystem_instance is first
