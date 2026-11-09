import pytest
from sqlalchemy import create_engine

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS
from agno.os.public import PublicSurface, RateLimit


def test_object_selection_identity_and_stable_namespace():
    db = PostgresDb(db_engine=create_engine("postgresql+psycopg://unused:unused@127.0.0.1:1/unused"))
    visible = Agent(id="visible")
    surface = PublicSurface(agents=[visible, visible])
    os = AgentOS(id="stable", db=db, agents=[visible], public=surface, auto_provision_dbs=False, telemetry=False)
    os.get_app()
    assert surface.agents == [visible] and surface.namespace == "stable"
    with pytest.raises(ValueError, match="not prepared"):
        surface.limiter
    for invalid in (
        PublicSurface(agents=[Agent(id="visible")]),
        PublicSurface(agents=[object()]),
        PublicSurface(namespace=""),
    ):
        instance = AgentOS(db=db, agents=[visible], public=invalid, telemetry=False, auto_provision_dbs=False)
        with pytest.raises(ValueError):
            instance.get_app()


def test_rate_limits_reject_invalid_values():
    with pytest.raises(ValueError):
        RateLimit(0, 1)


def test_public_policy_selects_a_manager_by_its_former_id():
    from types import SimpleNamespace

    from agno.os.public._policy import PublicRoutePolicy

    surface = PublicSurface(agents=[Agent(id="company--manager")], namespace="stable")
    policy = PublicRoutePolicy(surface, SimpleNamespace(authorization=False))
    for component_id in ("company--manager", "company-manager-internal"):
        assert policy.allows_anonymous("POST", f"/agents/{component_id}/runs")
    assert not policy.allows_anonymous("POST", "/teams/company-manager-internal/runs")
    assert not policy.allows_anonymous("POST", "/agents/company-manager/runs")
