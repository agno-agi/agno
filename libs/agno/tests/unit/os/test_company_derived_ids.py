"""Derived ids and fingerprints keep the values agno 3.2.0 gave them.

Stored rows are found by these values. A Goal declared by name, its Sources and a Routine's Project
are looked up by a derived id, and an accepted Task carries the fingerprint of the policy that
accepted it. The expected values below were printed by agno==3.2.0 for the same inputs.
"""

import pytest

from agno.company import Goal, Source
from agno.company.bootstrap import arehydrate_goal
from agno.company.manager import _routine_project_id
from agno.company.routines import _policy_fingerprint
from agno.db.sqlite import SqliteDb

GOAL_ID = "69462dfe-a16c-5894-a1dd-b57913e9c1b1"
SOURCE_ID = "e8e1b2fd-abda-5006-ac8d-62104a88089e"
PROJECT_ID = "f38f2fa8-1d45-5805-bb19-b5339bd8ef53"


def _schedule(policy):
    return {"payload": {"metadata": {"auto_accept": policy}}}


@pytest.mark.asyncio
async def test_a_goal_declared_by_name_and_its_source_keep_their_ids(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    goal = Goal(name="Docs", sources=[Source(type="website", reference="https://example.com/releases")])

    row = await arehydrate_goal(db, goal)
    sources, total = db.get_sources(goal_id=row["id"])

    assert row["id"] == GOAL_ID
    assert total == 1 and sources[0]["id"] == SOURCE_ID


def test_a_project_a_routine_proposes_keeps_its_id():
    assert _routine_project_id(GOAL_ID, "routine-1", "Release 2.4") == PROJECT_ID


@pytest.mark.parametrize(
    "policy, fingerprint",
    [
        (
            {"default_executor": "miniagent"},
            "49a889cb694d2c8c47e337f24e2c555c4331d626af2a03b87a42320b2400614d",
        ),
        (
            {
                "default_executor": "miniagent",
                "work_scope": {"goal_ids": ["this-agentos"], "project_ids": None},
                "limits": {"max_acceptances": 3, "expires_at": 1893456000},
            },
            "947ac5ea20e6a37d57466822eef45953ed206c22ddcf715bd4689813146888f8",
        ),
        (
            {"work_scope": {"goal_ids": ["a", "b"], "project_ids": ["p1", None]}},
            "a7c630f17a6723cc885f9b3547976fe235bf1c4b9a92b5789e39d2d7a07eec93",
        ),
        # The same two policies as agno 3.2.0 stored them.
        (
            {
                "default_executor": "miniagent",
                "work_scope": {"product_ids": ["this-agentos"], "project_ids": None},
                "limits": {"max_acceptances": 3, "expires_at": 1893456000},
            },
            "947ac5ea20e6a37d57466822eef45953ed206c22ddcf715bd4689813146888f8",
        ),
        (
            {"work_scope": {"product_ids": ["a", "b"], "project_ids": ["p1", None]}},
            "a7c630f17a6723cc885f9b3547976fe235bf1c4b9a92b5789e39d2d7a07eec93",
        ),
    ],
)
def test_a_policy_keeps_its_fingerprint(policy, fingerprint):
    assert _policy_fingerprint(_schedule(policy)) == fingerprint
