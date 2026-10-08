import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from agno.agent import Agent
from agno.os import AgentOS, CORSConfig
from agno.os.middleware.cors import OriginPolicy, OriginPolicyCORSMiddleware
from agno.os.utils import _is_cors_middleware, resolve_origins, update_cors_middleware


def _installed_cors(app: FastAPI) -> CORSMiddleware:
    cors = [m for m in app.user_middleware if _is_cors_middleware(m)]
    assert len(cors) == 1
    return cors[0].cls(app, **cors[0].kwargs)


def _preflight(app: FastAPI, origin: str):
    return TestClient(app).options("/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})


@pytest.mark.parametrize("merge", [False, True])
def test_base_app_origins_and_patterns_can_be_preserved_or_replaced(merge):
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware, allow_origins=["https://old.example"], allow_origin_regex=r"https://old-[a-z]+\.example"
    )
    policy = update_cors_middleware(
        app, ["https://docs.example"], origin_regex=r"https://new-[a-z]+\.example", merge_existing=merge
    )
    assert policy.allows("https://docs.example")
    assert policy.allows("https://new-feature.example")
    assert policy.allows("https://old.example") is merge
    assert policy.allows("https://old-feature.example") is merge
    assert not policy.allows("https://new-feature.example.evil")
    middleware = _installed_cors(app)
    for origin in ("https://docs.example", "https://new-feature.example", "https://old.example", "https://evil.test"):
        assert middleware.is_allowed_origin(origin) == policy.allows(origin)


def test_legacy_empty_cors_allowed_origins_still_uses_defaults():
    assert resolve_origins([], ["https://default.example"]) == ["https://default.example"]
    assert resolve_origins(None, ["https://default.example"]) == ["https://default.example"]
    agent_os = AgentOS(agents=[Agent(id="docs", telemetry=False)], cors_allowed_origins=[], telemetry=False)
    assert agent_os.cors_allowed_origins == agent_os.settings.cors_origin_list


def test_cors_config_empty_origins_allow_none():
    agent_os = AgentOS(agents=[Agent(id="docs", telemetry=False)], cors=CORSConfig(origins=[]), telemetry=False)
    assert agent_os.cors_allowed_origins == []
    response = _preflight(agent_os.get_app(), "https://os.agno.com")
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_config_without_origins_uses_defaults():
    agent_os = AgentOS(
        agents=[Agent(id="docs", telemetry=False)], cors=CORSConfig(origin_regex=r"https://x\.test"), telemetry=False
    )
    assert agent_os.cors_allowed_origins == agent_os.settings.cors_origin_list


def test_cors_and_cors_allowed_origins_are_mutually_exclusive():
    with pytest.raises(ValueError, match="not both"):
        AgentOS(
            agents=[Agent(id="docs", telemetry=False)],
            cors=CORSConfig(origins=["https://a.test"]),
            cors_allowed_origins=["https://b.test"],
        )


def test_invalid_regex_fails_during_configuration():
    with pytest.raises(ValidationError, match="origin_regex"):
        CORSConfig(origin_regex="[")


def test_cors_config_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        CORSConfig(origin=["https://a.test"])  # type: ignore[call-arg]


def test_inline_flag_regex_on_agentos():
    agent_os = AgentOS(
        agents=[Agent(id="docs", telemetry=False)],
        cors=CORSConfig(origins=[], origin_regex=r"(?i)https://docs-[a-z]+\.example\.com"),
        telemetry=False,
    )
    app = agent_os.get_app()
    assert _preflight(app, "https://DOCS-Feature.example.com").status_code == 200
    assert _preflight(app, "https://docs-feature.example.com.evil.test").status_code == 400


def test_inline_flag_regex_on_base_app_merges_with_agentos_regex():
    base = FastAPI()
    base.add_middleware(CORSMiddleware, allow_origin_regex=r"(?i)https://legacy-[a-z]+\.example\.com")
    app = AgentOS(
        agents=[Agent(id="docs", telemetry=False)],
        base_app=base,
        cors=CORSConfig(origins=[], origin_regex=r"https://docs-[a-z]+\.example\.com"),
        telemetry=False,
    ).get_app()
    assert _preflight(app, "https://LEGACY-old.example.com").status_code == 200
    assert _preflight(app, "https://docs-new.example.com").status_code == 200
    # The base app's case-insensitive flag stays scoped to its own pattern.
    assert _preflight(app, "https://DOCS-new.example.com").status_code == 400


@pytest.mark.parametrize(
    "patterns, allowed, denied",
    [
        ([r"(?i)https://a\.test", r"https://b\.test"], ["https://A.TEST", "https://b.test"], ["https://B.TEST"]),
        ([r"(?x) https://a \. test  # verbose", r"https://b\.test"], ["https://a.test", "https://b.test"], []),
        ([r"https://a\.test|https://c\.test", r"https://b\.test"], ["https://c.test", "https://b.test"], []),
        (
            [r"https://(?P<sub>[a-z]+)\.a\.test", r"https://(?P<sub>[a-z]+)\.b\.test"],
            ["https://x.a.test", "https://y.b.test"],
            [],
        ),
        ([r"https://(x)\1\.test", r"https://(y)\1\.test"], ["https://xx.test", "https://yy.test"], ["https://xy.test"]),
    ],
)
def test_patterns_are_matched_independently(patterns, allowed, denied):
    policy = OriginPolicy([], patterns)
    for origin in allowed:
        assert policy.allows(origin), origin
    for origin in [*denied, "https://a.test.evil", "https://evil.test"]:
        assert not policy.allows(origin), origin


def test_named_groups_in_cors_config_and_base_app_patterns():
    base = FastAPI()
    base.add_middleware(CORSMiddleware, allow_origin_regex=r"https://(?P<sub>[a-z]+)\.legacy\.test")
    app = AgentOS(
        agents=[Agent(id="docs", telemetry=False)],
        base_app=base,
        cors=CORSConfig(origins=[], origin_regex=r"https://(?P<sub>[a-z]+)\.docs\.test"),
        telemetry=False,
    ).get_app()
    assert [m.cls for m in app.user_middleware if _is_cors_middleware(m)] == [OriginPolicyCORSMiddleware]
    assert _preflight(app, "https://a.legacy.test").status_code == 200
    assert _preflight(app, "https://b.docs.test").status_code == 200
    assert _preflight(app, "https://b.docs.test.evil").status_code == 400


def test_single_pattern_keeps_plain_starlette_cors_middleware():
    base = FastAPI()
    base.add_middleware(CORSMiddleware, allow_origins=["https://old.example"], allow_origin_regex=r"https://a\.test")
    app = AgentOS(agents=[Agent(id="docs", telemetry=False)], base_app=base, telemetry=False).get_app()
    cors = [m for m in app.user_middleware if _is_cors_middleware(m)]
    assert [m.cls for m in cors] == [CORSMiddleware]
    assert cors[0].kwargs["allow_origin_regex"] == r"https://a\.test"
    assert "https://old.example" in cors[0].kwargs["allow_origins"]


def test_policy_middleware_is_merged_again_on_reapplication():
    app = FastAPI()
    first = update_cors_middleware(app, ["https://a.test"], origin_regex=r"https://b\.test")
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"https://c\.test")
    update_cors_middleware(app, [], origin_regex=r"https://d\.test")
    second = update_cors_middleware(app, [], origin_regex=r"https://e\.test")
    assert first.allows("https://b.test")
    for origin in ("https://a.test", "https://b.test", "https://c.test", "https://d.test", "https://e.test"):
        assert second.allows(origin), origin
        assert _installed_cors(app).is_allowed_origin(origin), origin


def test_base_app_replacement_is_available_on_agentos():
    base = FastAPI()
    base.add_middleware(CORSMiddleware, allow_origins=["https://old.example"])
    app = AgentOS(
        agents=[Agent(id="docs", telemetry=False)],
        base_app=base,
        cors=CORSConfig(origins=[], merge_base_app=False),
        telemetry=False,
    ).get_app()
    response = _preflight(app, "https://old.example")
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_get_app_does_not_rewrite_configured_origins():
    base = FastAPI()
    base.add_middleware(CORSMiddleware, allow_origins=["https://old.example"])
    agent_os = AgentOS(
        agents=[Agent(id="docs", telemetry=False)],
        base_app=base,
        cors_allowed_origins=["https://new.example"],
        telemetry=False,
    )
    app = agent_os.get_app()
    assert agent_os.cors_allowed_origins == ["https://new.example"]
    assert _preflight(app, "https://old.example").status_code == 200
