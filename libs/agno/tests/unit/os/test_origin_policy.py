import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.middleware.cors import OriginPolicy
from agno.os.utils import resolve_origins, update_cors_middleware


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
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1
    middleware = CORSMiddleware(app, **cors[0].kwargs)
    for origin in ("https://docs.example", "https://new-feature.example", "https://old.example", "https://evil.test"):
        assert middleware.is_allowed_origin(origin) == policy.allows(origin)


def test_empty_origins_are_explicit_not_default_fallback():
    assert resolve_origins([], ["https://default.example"]) == []
    assert resolve_origins(None, ["https://default.example"]) == ["https://default.example"]
    assert not OriginPolicy([]).allows("https://default.example")


def test_invalid_regex_fails_during_configuration():
    with pytest.raises(re.error):
        AgentOS(agents=[Agent(id="docs", telemetry=False)], cors_allowed_origin_regex="[")


def test_base_app_replacement_is_available_on_agentos():
    base = FastAPI()
    base.add_middleware(CORSMiddleware, allow_origins=["https://old.example"])
    app = AgentOS(
        agents=[Agent(id="docs", telemetry=False)],
        base_app=base,
        cors_allowed_origins=[],
        cors_merge_base_app_origins=False,
        telemetry=False,
    ).get_app()
    response = TestClient(app).options(
        "/health", headers={"Origin": "https://old.example", "Access-Control-Request-Method": "GET"}
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
