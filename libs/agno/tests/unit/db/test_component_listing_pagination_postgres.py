"""Component listing pagination on the PostgreSQL adapter.

Mirror of the SQLite pagination suites in tests/unit/agent/test_agent_config.py,
tests/unit/team/test_team_config.py and tests/unit/workflow/test_workflow_config.py
against a live Postgres (cookbook/scripts/run_pgvector.sh, port 5532).

get_agents/get_teams/get_workflows must page past the adapter's default
list_components limit: published components from other users share the
catalog, so without paging they crowd a user's own components out of the
first page.

Each test runs in its own schema, dropped on teardown. The whole module
skips when psycopg is missing or the server is unreachable.
"""

import uuid

import pytest
from sqlalchemy import create_engine, text

from agno.agent.agent import get_agents
from agno.db.base import ComponentType
from agno.db.postgres import PostgresDb
from agno.team.team import get_teams
from agno.workflow.workflow import get_workflows

pytest.importorskip("psycopg")

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _server_reachable() -> bool:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _postgres_server():
    if not _server_reachable():
        pytest.skip(f"Postgres server not reachable at {DB_URL}")


@pytest.fixture
def db(_postgres_server):
    schema = f"p_listpage_{uuid.uuid4().hex[:8]}"
    database = PostgresDb(db_url=DB_URL, db_schema=schema, id=f"listing-pagination-{schema}")
    yield database
    database.Session.remove()
    with database.db_engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()
    database.db_engine.dispose()


def _create(db, component_id, user_id, component_type, config):
    db.create_component_with_config(
        component_id=component_id,
        component_type=component_type,
        name=component_id,
        config=config,
        stage="published",
        user_id=user_id,
    )


class TestGetAgentsPaginationPostgres:
    def test_returns_all_own_agents_beyond_default_page(self, db):
        for i in range(25):
            _create(db, f"own-agent-{i:02d}", "owner", ComponentType.AGENT, {"name": f"own-agent-{i:02d}"})

        agents = get_agents(db=db, user_id="owner")

        assert {a.id for a in agents} == {f"own-agent-{i:02d}" for i in range(25)}

    def test_own_agents_not_crowded_out_by_foreign_published(self, db):
        # Own rows first (older), foreign rows second (newer): the listing
        # orders created_at DESC with component_id ASC ties, so the foreign
        # rows fill the first page either way.
        for i in range(5):
            _create(db, f"z-own-agent-{i}", "owner", ComponentType.AGENT, {"name": f"z-own-agent-{i}"})
        for i in range(25):
            _create(db, f"a-pub-agent-{i:02d}", "someone-else", ComponentType.AGENT, {"name": f"a-pub-agent-{i:02d}"})

        agents = get_agents(db=db, user_id="owner")

        ids = {a.id for a in agents}
        assert {f"z-own-agent-{i}" for i in range(5)} <= ids
        assert len(agents) == 30


class TestGetTeamsPaginationPostgres:
    def test_returns_all_own_teams_beyond_default_page(self, db):
        for i in range(25):
            _create(db, f"own-team-{i:02d}", "owner", ComponentType.TEAM, {"name": f"own-team-{i:02d}", "members": []})

        teams = get_teams(db=db, user_id="owner")

        assert {t.id for t in teams} == {f"own-team-{i:02d}" for i in range(25)}

    def test_own_teams_not_crowded_out_by_foreign_published(self, db):
        for i in range(5):
            _create(db, f"z-own-team-{i}", "owner", ComponentType.TEAM, {"name": f"z-own-team-{i}", "members": []})
        for i in range(25):
            _create(
                db,
                f"a-pub-team-{i:02d}",
                "someone-else",
                ComponentType.TEAM,
                {"name": f"a-pub-team-{i:02d}", "members": []},
            )

        teams = get_teams(db=db, user_id="owner")

        ids = {t.id for t in teams}
        assert {f"z-own-team-{i}" for i in range(5)} <= ids
        assert len(teams) == 30


class TestGetWorkflowsPaginationPostgres:
    def test_returns_all_own_workflows_beyond_default_page(self, db):
        for i in range(25):
            _create(db, f"own-wf-{i:02d}", "owner", ComponentType.WORKFLOW, {"name": f"own-wf-{i:02d}", "steps": []})

        workflows = get_workflows(db=db, user_id="owner")

        assert {w.id for w in workflows} == {f"own-wf-{i:02d}" for i in range(25)}

    def test_own_workflows_not_crowded_out_by_foreign_published(self, db):
        for i in range(5):
            _create(db, f"z-own-wf-{i}", "owner", ComponentType.WORKFLOW, {"name": f"z-own-wf-{i}", "steps": []})
        for i in range(25):
            _create(
                db,
                f"a-pub-wf-{i:02d}",
                "someone-else",
                ComponentType.WORKFLOW,
                {"name": f"a-pub-wf-{i:02d}", "steps": []},
            )

        workflows = get_workflows(db=db, user_id="owner")

        ids = {w.id for w in workflows}
        assert {f"z-own-wf-{i}" for i in range(5)} <= ids
        assert len(workflows) == 30
