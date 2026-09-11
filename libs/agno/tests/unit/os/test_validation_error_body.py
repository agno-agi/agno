"""A validator's ValueError is a 422 that names the field, not a 500.

AgentOS installs its own RequestValidationError handler on an app it owns and built
the body from the raw ``exc.errors()``. Pydantic v2 puts the live exception object in
``ctx["error"]`` for every validator that raised ValueError, so ``json.dumps`` failed
inside the handler and the catch-all answered 500 "Internal server error (TypeError)" —
silencing every custom validator on the platform. The router tests missed it because
they mount routers on a bare FastAPI(), which uses FastAPI's correct default handler.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

# Starts with "/" and contains "://": reaches validate_endpoint's full-URL branch.
# A bare "http://..." would trip the earlier "must start with '/'" check instead.
BAD_SCHEDULE = {"name": "x", "cron_expr": "0 3 * * *", "endpoint": "/proxy?u=http://evil.example.com"}


def _os_client(tmp_path, name, base_app=None):
    db = SqliteDb(db_file=str(tmp_path / f"{name}.db"))
    agent = Agent(id="qa-agent", name="QA Agent", db=db)
    kwargs = {"agents": [agent], "db": db, "telemetry": False}
    if base_app is not None:
        kwargs["base_app"] = base_app
    # raise_server_exceptions=False or the handler's own TypeError is re-raised
    # out of ServerErrorMiddleware and no response is ever asserted on.
    return TestClient(AgentOS(**kwargs).get_app(), raise_server_exceptions=False)


@pytest.fixture()
def harness(tmp_path):
    return SimpleNamespace(client=_os_client(tmp_path, "owned"))


class TestValidatorErrorsAnswer422:
    """Each of these FAILS on the unpatched handler and passes after the fix."""

    def test_field_validator_value_error_is_422_with_message(self, harness):
        resp = harness.client.post("/schedules", json=BAD_SCHEDULE)
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:200]}"
        assert "Endpoint must be a path, not a full URL" in resp.text, f"message missing from body: {resp.text[:200]}"
        assert resp.json()["detail"][0]["loc"] == ["body", "endpoint"]

    def test_model_validator_value_error_is_422_with_message(self, harness):
        resp = harness.client.patch("/schedules/does-not-exist", json={"method": None})
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:200]}"
        assert "cannot be set to null" in resp.text, f"message missing from body: {resp.text[:200]}"

    def test_service_account_validator_is_422_with_message(self, harness):
        resp = harness.client.post("/service-accounts", json={"name": "BAD NAME!!"})
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:200]}"
        assert "lowercase slug" in resp.text, f"message missing from body: {resp.text[:200]}"

    def test_component_guard_validator_is_422_with_message(self, harness):
        resp = harness.client.patch("/components/does-not-exist", json={"guard": {"current_version": True}})
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:200]}"
        assert "version guards must be integers" in resp.text, f"message missing from body: {resp.text[:200]}"
        assert resp.json()["detail"][0]["loc"] == ["body", "guard", "current_version"]

    def test_error_body_is_json_and_has_no_exception_repr(self, harness):
        resp = harness.client.post("/schedules", json=BAD_SCHEDULE)
        body = resp.json()
        assert isinstance(body["detail"], list), f"detail must be a list, got: {resp.text[:200]}"
        for entry in body["detail"]:
            assert "type" in entry and "loc" in entry and "msg" in entry, f"malformed entry: {entry}"
        assert "ValueError(" not in resp.text, "the encoded body must not leak a Python repr"


class TestNonValidatorPathsUnchanged:
    """These PASS today and must keep passing (regression guard for the fix itself)."""

    def test_builtin_coercion_error_still_422(self, harness):
        resp = harness.client.get("/sessions?limit=abc")
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:200]}"
        assert resp.json()["detail"][0]["type"] == "int_parsing"

    def test_missing_required_field_still_422(self, harness):
        resp = harness.client.post("/schedules", json={"name": "x"})
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:200]}"
        assert any(entry["type"] == "missing" for entry in resp.json()["detail"])

    def test_internal_error_still_500_without_echo(self, harness, monkeypatch):
        """A downstream ValueError is a SERVER failure. The fix must not turn
        every ValueError into a client error: only the ones pydantic wrapped
        into a RequestValidationError change status."""

        async def broken_arun(self, **kwargs):
            raise ValueError("db not initialized at postgresql://ai:secret@db.internal/ai")

        monkeypatch.setattr(Agent, "arun", broken_arun)
        resp = harness.client.post(
            "/agents/qa-agent/runs",
            data={"message": "hello", "stream": "false", "background": "false"},
        )
        assert resp.status_code == 500, f"expected 500, got {resp.status_code}: {resp.text[:200]}"
        assert "secret" not in resp.text, "the 500 body must not echo the exception message"


class TestValidatorInDependencyOwnedModel:
    """The handler must also cover body models agno does not author: interface
    routes validate request models from dependencies (here ag_ui's RunAgentInput),
    whose validators can change underneath agno without any agno diff."""

    def test_agui_dependency_validator_is_422_with_message(self, tmp_path):
        pytest.importorskip("ag_ui", reason="ag_ui not installed")
        from agno.os.interfaces.agui import AGUI

        db = SqliteDb(db_file=str(tmp_path / "agui.db"))
        agent = Agent(id="qa-agent", name="QA Agent", db=db)
        agent_os = AgentOS(agents=[agent], db=db, telemetry=False, interfaces=[AGUI(agent=agent)])
        client = TestClient(agent_os.get_app(), raise_server_exceptions=False)
        # A binary content item with no id, url, or data trips BinaryInputContent's
        # model_validator inside the ag_ui dependency.
        bad_content = [{"type": "binary", "mimeType": "application/octet-stream"}]
        resp = client.post(
            "/agui",
            json={
                "threadId": "t1",
                "runId": "r1",
                "state": {},
                "messages": [{"id": "m1", "role": "user", "content": bad_content}],
                "tools": [],
                "context": [],
                "forwardedProps": {},
            },
        )
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:200]}"
        assert "BinaryInputContent requires id, url, or data" in resp.text, (
            f"message missing from body: {resp.text[:300]}"
        )


class TestOwnedAndBorrowedAppsAgree:
    """The invariant that would have caught this at review time: the owned app
    must answer exactly what a caller-supplied base_app answers."""

    def test_owned_app_matches_default_fastapi_handler(self, tmp_path):
        owned = _os_client(tmp_path, "owned")
        borrowed = _os_client(tmp_path, "borrowed", base_app=FastAPI())
        owned_resp = owned.post("/schedules", json=BAD_SCHEDULE)
        borrowed_resp = borrowed.post("/schedules", json=BAD_SCHEDULE)
        assert owned_resp.status_code == borrowed_resp.status_code == 422, (
            f"owned {owned_resp.status_code} vs borrowed {borrowed_resp.status_code}: "
            f"{owned_resp.text[:200]} | {borrowed_resp.text[:200]}"
        )
        assert owned_resp.json()["detail"] == borrowed_resp.json()["detail"]
