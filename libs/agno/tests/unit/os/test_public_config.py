import pytest
from sqlalchemy import create_engine

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS, MCPConfig
from agno.os.public import PublicSurface, RateLimit
from agno.team import Team


def test_url_resolution_preserves_overrides_and_caller_config(monkeypatch):
    monkeypatch.setenv("AGENTOS_URL", "https://env.example.com/base/")

    def lookup(query: str) -> str:
        return query

    mcp = MCPConfig(tools=[lookup], default_tools=False, lifecycle_tools=False, stateless=True)
    os = AgentOS(
        id="test", agents=[Agent(id="url-test")], url="http://localhost:8888/prefix/", mcp=mcp, telemetry=False
    )
    assert os.url == "http://localhost:8888/prefix"
    assert os._scheduler_base_url == os.url
    assert os.mcp_config.server_card_url == os.url + "/mcp"
    assert mcp.server_card_url is None
    assert AgentOS(agents=[Agent()], telemetry=False).url == "https://env.example.com/base"
    explicit = AgentOS(
        agents=[Agent()],
        url="https://example.com",
        scheduler_base_url="http://localhost:9000",
        telemetry=False,
        mcp=MCPConfig(server_card_url="https://mcp.example.com/custom"),
    )
    assert explicit._scheduler_base_url == "http://localhost:9000"
    assert explicit.mcp_config.server_card_url == "https://mcp.example.com/custom"
    monkeypatch.delenv("AGENTOS_URL")
    assert AgentOS(agents=[Agent()], telemetry=False).url is None


@pytest.mark.parametrize(
    "url",
    [
        "",
        "relative",
        "https://u:p@example.com",
        "https://example.com?q=x",
        "https://example.com#x",
        "ftp://example.com",
        "https://example.com:wrong",
        "https://example.com/../a",
    ],
)
def test_invalid_urls_fail_configuration(url):
    with pytest.raises(ValueError):
        AgentOS(agents=[Agent()], url=url, telemetry=False)


def test_object_selection_identity_and_stable_namespace():
    db = PostgresDb(db_engine=create_engine("postgresql+psycopg://unused:unused@127.0.0.1:1/unused"))
    visible, hidden = Agent(id="visible"), Agent(id="hidden")
    team = Team(id="team", members=[hidden])
    surface = PublicSurface(agents=[visible, visible], teams=[team])
    os = AgentOS(
        id="stable", db=db, agents=[visible], teams=[team], public=surface, auto_provision_dbs=False, telemetry=False
    )
    os.get_app()
    assert surface.agents == [visible] and surface.namespace == "stable"
    with pytest.raises(ValueError, match="not prepared"):
        surface.limiter
    for invalid in (
        PublicSurface(agents=[Agent(id="visible")]),
        PublicSurface(agents=[team]),
        PublicSurface(namespace=""),
    ):
        instance = AgentOS(
            db=db, agents=[visible], teams=[team], public=invalid, telemetry=False, auto_provision_dbs=False
        )
        with pytest.raises(ValueError):
            instance.get_app()


def test_rate_limits_reject_invalid_values():
    with pytest.raises(ValueError):
        RateLimit(0, 1)
