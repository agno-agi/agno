"""Offloading and tool-result compression refuse to run together.

Compression sends tool messages to a model and rewrites them, which would
replace a stored-result envelope with text whose result id may be gone while
the payload lives on unreferenced. The combination is refused at
initialization, on the agent, on the team, and on a member that would inherit
the team's store.
"""

import os
import tempfile

import pytest

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.offload import ResultStore
from agno.team import Team


@pytest.fixture()
def db(tmp_path):
    return SqliteDb(db_file=os.path.join(tempfile.mkdtemp(dir=tmp_path), "offload-config.db"))


def test_agent_refuses_offloading_with_compression(db):
    agent = Agent(db=db, compress_tool_results=True, offload_tool_results=True)
    with pytest.raises(ValueError, match="cannot be enabled together"):
        agent.initialize_agent()


def test_agent_refuses_offloading_with_a_compressing_manager(db):
    # The manager's own flag enables compression even when the agent's does not.
    agent = Agent(
        db=db,
        compression_manager=CompressionManager(compress_tool_results=True),
        offload_tool_results=ResultStore(threshold_chars=100),
    )
    with pytest.raises(ValueError, match="cannot be enabled together"):
        agent.initialize_agent()


def test_agent_allows_offloading_with_a_disabled_manager(db):
    agent = Agent(
        db=db,
        compression_manager=CompressionManager(compress_tool_results=False),
        offload_tool_results=True,
    )
    agent.initialize_agent()
    assert agent._result_store is not None


def test_agent_allows_compression_without_offloading(db):
    agent = Agent(db=db, compress_tool_results=True)
    agent.initialize_agent()
    assert agent._result_store is None


def test_result_store_property_refuses_the_combination(db):
    agent = Agent(db=db, compress_tool_results=True, offload_tool_results=True)
    with pytest.raises(ValueError, match="cannot be enabled together"):
        agent.result_store


def test_team_refuses_offloading_with_compression(db):
    team = Team(members=[Agent(db=db)], db=db, compress_tool_results=True, offload_tool_results=True)
    with pytest.raises(ValueError, match="cannot be enabled together"):
        team.initialize_team()


def test_compressing_member_cannot_inherit_the_team_store(db):
    member = Agent(name="compressor", db=db, compress_tool_results=True)
    team = Team(members=[member], db=db, offload_tool_results=True)
    with pytest.raises(ValueError, match="compressor"):
        team.initialize_team()


def test_compressing_member_that_opts_out_is_fine(db):
    member = Agent(name="compressor", db=db, compress_tool_results=True, offload_tool_results=False)
    team = Team(members=[member], db=db, offload_tool_results=True)
    team.initialize_team()
    assert member._result_store is None
    assert team._result_store is not None


def test_a_sub_team_member_keeps_its_declared_store_settings(db):
    from agno.offload import ResultStore

    member = Agent(name="deep", db=None, offload_tool_results=ResultStore(threshold_chars=100))
    sub_team = Team(name="sub", members=[member])  # no db of its own
    parent = Team(name="parent", members=[sub_team], db=db, offload_tool_results=True)
    parent.initialize_team()
    assert sub_team._result_store is parent._result_store
    assert member._result_store is not None
    assert member._result_store.threshold_chars == 100
    assert member._result_store.db is db


def test_a_member_keeps_its_own_store_when_the_team_does_not_offload(db):
    """A member's explicit setting is not a function of the team's.

    The team's ``offload_tool_results`` decides what the team does with its own
    tool results. A member that asked for a store still gets one, otherwise the
    setting is dropped on the floor: ``member._result_store`` would be None
    while ``member.offload_tool_results`` still reports a ResultStore, so the
    member looks configured and offloads nothing.
    """
    member = Agent(name="member", db=db, offload_tool_results=ResultStore(threshold_chars=100))
    team = Team(name="team", members=[member], db=db)  # the team itself does not offload
    team.initialize_team()

    assert member._result_store is not None
    assert member._result_store.threshold_chars == 100
    assert member._result_store.db is db


def test_a_member_asking_for_the_defaults_keeps_them_when_the_team_does_not_offload(db):
    """``offload_tool_results=True`` has to survive the same way a ResultStore does.

    True is the documented way to ask for the defaults, so keying the member
    branch on ``isinstance(..., ResultStore)`` would honour the verbose form and
    silently drop the common one.
    """
    member = Agent(name="member", db=db, offload_tool_results=True)
    team = Team(name="team", members=[member], db=db)  # the team itself does not offload
    team.initialize_team()

    assert member._result_store is not None
    assert member._result_store.db is db


def test_a_member_without_its_own_db_binds_to_the_team_db(db):
    member = Agent(name="member", db=None, offload_tool_results=ResultStore(threshold_chars=100))
    team = Team(name="team", members=[member], db=db)
    team.initialize_team()

    assert member._result_store is not None
    assert member._result_store.db is db


def test_a_member_opting_out_stays_out_when_the_team_does_not_offload(db):
    member = Agent(name="member", db=db, offload_tool_results=False)
    team = Team(name="team", members=[member], db=db)
    team.initialize_team()

    assert member._result_store is None


def test_a_member_on_defaults_gets_no_store_when_the_team_does_not_offload(db):
    member = Agent(name="member", db=db)
    team = Team(name="team", members=[member], db=db)
    team.initialize_team()

    assert member._result_store is None


def test_team_store_follows_a_db_change(db, tmp_path):
    import os as _os

    from agno.db.sqlite import SqliteDb as _SqliteDb

    team = Team(members=[Agent()], db=db, offload_tool_results=True)
    team.initialize_team()
    assert team._result_store is not None and team._result_store.db is db
    other = _SqliteDb(db_file=_os.path.join(str(tmp_path), "other.db"))
    team.db = other
    team.initialize_team()
    assert team._result_store.db is other


def test_team_store_follows_a_settings_change(db):
    from agno.offload import ResultStore

    team = Team(members=[Agent()], db=db, offload_tool_results=True)
    team.initialize_team()
    assert team._result_store.threshold_chars == 16000
    team.offload_tool_results = ResultStore(threshold_chars=123)
    team.initialize_team()
    assert team._result_store.threshold_chars == 123
    team.offload_tool_results = None
    team.initialize_team()
    assert team._result_store is None
