"""Company details REST permissions, conflict behavior and manager context."""

import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, Authorization, CompanyConfig

SECRET = "company-details-offline-test-key-32-characters"


def headers(scopes):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": "alice", "aud": "details-test", "scopes": scopes, "exp": time.time() + 600},
            SECRET,
            algorithm="HS256",
        )
    }


def test_details_permissions_edits_and_restart(tmp_path):
    db_file = str(tmp_path / "company.db")
    db = SqliteDb(db_file=db_file)
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256", audience="details-test")
    os = AgentOS(id="details-test", db=db, company=CompanyConfig(name="Initial"), authorization=auth, telemetry=False)
    client = TestClient(os.get_app())
    assert client.get("/company/details", headers=headers([])).status_code == 403
    read = client.get("/company/details", headers=headers(["company:read"]))
    assert read.status_code == 200
    assert client.get("/company/details/access", headers=headers(["company:read"])).json() == {"can_edit": False}
    assert client.get("/company/details/access", headers=headers(["agent_os:admin"])).json() == {"can_edit": True}
    assert client.get("/company/details/access", headers=headers(["company:write", "company:read"])).json() == {
        "can_edit": True
    }
    data = read.json()
    body = {"expected_updated_at": data["updated_at"], "name": "Edited", "description": "Human identity"}
    assert (
        client.patch("/company/details", json=body, headers=headers(["company:read", "products:write"])).status_code
        == 403
    )
    edited = client.patch("/company/details", json=body, headers=headers(["company:write"]))
    assert edited.status_code == 200
    assert client.patch("/company/details", json=body, headers=headers(["agent_os:admin"])).status_code == 409
    assert (
        client.patch("/company/details", json={**body, "name": None}, headers=headers(["agent_os:admin"])).status_code
        == 422
    )
    db.close()
    fresh_db = SqliteDb(db_file=db_file)
    restarted = AgentOS(
        id="details-test", db=fresh_db, company=CompanyConfig(name="Deployment"), authorization=auth, telemetry=False
    )
    fresh = TestClient(restarted.get_app()).get("/company/details", headers=headers(["company:read"]))
    assert fresh.json() == edited.json()
    fresh_db.close()


def test_database_scope_isolated(tmp_path):
    path = str(tmp_path / "shared.db")
    first = SqliteDb(db_file=path, products_table="first_products")
    second = SqliteDb(db_file=path, products_table="second_products")
    first.initialize_company("First")
    second.initialize_company("Second")
    assert first.get_company()["name"] == "First"
    assert second.get_company()["name"] == "Second"
    first.close()
    second.close()


def test_next_manager_runs_use_saved_details_without_products(tmp_path):
    from agno.models.base import Model
    from agno.models.message import MessageMetrics
    from agno.models.response import ModelResponse
    from agno.os import OSManager
    from agno.registry._reserved import COMPANY_MANAGER_ID, MANAGER_TEAM_ID

    class ContextModel(Model):
        def __init__(self):
            super().__init__(id="company-context-offline", provider="test")

        def invoke(self, messages, *args, **kwargs):
            context = "\n".join(str(message.content) for message in messages if message.role == "system")
            return ModelResponse(
                role="assistant",
                content="new description"
                if "new description" in context
                else "original description"
                if "original description" in context
                else "no company context",
                response_usage=MessageMetrics(),
            )

        def _parse_provider_response(self, response, **kwargs):
            return response

        def _parse_provider_response_delta(self, response):
            return response

        async def ainvoke(self, *args, **kwargs):
            return self.invoke(*args, **kwargs)

        def invoke_stream(self, *args, **kwargs):
            yield self.invoke(*args, **kwargs)

        async def ainvoke_stream(self, *args, **kwargs):
            yield self.invoke(*args, **kwargs)

    db = SqliteDb(db_file=str(tmp_path / "manager.db"))
    model = ContextModel()
    os = AgentOS(
        id="details-test",
        db=db,
        company=CompanyConfig(model=model, description="original description"),
        manager=OSManager(model=model, access_docs=False, offload_tool_results=False),
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", audience="details-test"),
        telemetry=False,
    )
    client = TestClient(os.get_app())
    admin = headers(["agent_os:admin"])
    data = client.get("/company/details", headers=admin).json()
    for component_type, component_id in [("agents", COMPANY_MANAGER_ID), ("teams", MANAGER_TEAM_ID)]:
        scope = f"{component_type}:{component_id}:run"
        first = client.post(
            f"/{component_type}/{component_id}/runs",
            data={"message": "What do we do?", "stream": "false"},
            headers=headers([scope, "company:read"]),
        )
        assert first.status_code == 200, first.text
        assert first.json()["content"] == "original description"
        denied = client.post(
            f"/{component_type}/{component_id}/runs",
            data={"message": "What do we do?", "stream": "false"},
            headers=headers([scope]),
        )
        assert denied.status_code == 200, denied.text
        assert denied.json()["content"] == "no company context"
    changed = client.patch(
        "/company/details",
        json={"expected_updated_at": data["updated_at"], "description": "new description"},
        headers=admin,
    )
    assert changed.status_code == 200
    for component_type, component_id in [("agents", COMPANY_MANAGER_ID), ("teams", MANAGER_TEAM_ID)]:
        updated = client.post(
            f"/{component_type}/{component_id}/runs",
            data={"message": "What do we do?", "stream": "false"},
            headers=admin,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["content"] == "new description"
    db.close()


def test_company_config_preserves_positional_products():
    from agno.company import Product

    products = [Product(name="Existing")]
    config = CompanyConfig(None, None, products)
    assert config.products is products
    assert config.name == "Company"
    assert config.description is None


@pytest.mark.asyncio
async def test_async_context_uses_async_authority_with_sync_company_storage(tmp_path):
    from types import SimpleNamespace

    from agno.company.details import _company_instructions
    from agno.run.authorization import RunAuthorization
    from agno.utils.agent import aexecute_instructions, execute_instructions

    class AsyncAuthority(RunAuthorization):
        def __init__(self):
            pass

        def require(self, *args):
            raise RuntimeError("Async authority requires arequire")

        async def arequire(self, resource, action):
            assert (resource, action) == ("company", "read")

    db = SqliteDb(db_file=str(tmp_path / "mixed.db"))
    db.initialize_company("Mixed", "Async-authorized context")
    instructions = _company_instructions(db, ["Base"])
    context = SimpleNamespace(authorization=AsyncAuthority())
    assert "Async-authorized context" in (await aexecute_instructions(instructions, run_context=context))[-1]
    assert "Async-authorized context" in execute_instructions(instructions)[-1]
    db.close()


def _offline_model():
    from agno.models.base import Model
    from agno.models.message import MessageMetrics
    from agno.models.response import ModelResponse

    class LocalModel(Model):
        def __init__(self):
            super().__init__(id="company-details-offline", provider="test")

        def invoke(self, messages, *args, **kwargs):
            return ModelResponse(role="assistant", content="local answer", response_usage=MessageMetrics())

        def _parse_provider_response(self, response, **kwargs):
            return response

        def _parse_provider_response_delta(self, response):
            return response

        async def ainvoke(self, *args, **kwargs):
            return self.invoke(*args, **kwargs)

        def invoke_stream(self, *args, **kwargs):
            yield self.invoke(*args, **kwargs)

        async def ainvoke_stream(self, *args, **kwargs):
            yield self.invoke(*args, **kwargs)

    return LocalModel()


def _company_os(db, **company):
    from agno.os import OSManager

    model = _offline_model()
    return AgentOS(
        db=db,
        manager=OSManager(model=model, access_docs=False, offload_tool_results=False),
        company=CompanyConfig(model=model, **company),
        telemetry=False,
    )


def _assert_managers_answer(client):
    from agno.registry._reserved import COMPANY_MANAGER_ID, MANAGER_TEAM_ID

    assert client.get("/agents").status_code == 200
    assert client.get("/teams").status_code == 200
    for path in (f"/agents/{COMPANY_MANAGER_ID}/runs", f"/teams/{MANAGER_TEAM_ID}/runs"):
        run = client.post(path, data={"message": "hello", "stream": "false"})
        assert run.status_code == 200 and run.json()["content"] == "local answer"


def test_startup_applies_configuration_without_products(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "startup.db"))
    with TestClient(_company_os(db, name="Acme", description="What Acme does").get_app()):
        assert db.get_company()["name"] == "Acme"
    with TestClient(_company_os(db, name="Acme Inc").get_app()):
        row = db.get_company()
        assert (row["name"], row["description"]) == ("Acme Inc", None)
    db.update_company(row["updated_at"], name="Human edit")
    with TestClient(_company_os(db, name="Later config").get_app()):
        assert db.get_company()["name"] == "Human edit"
    db.close()


def test_startup_and_managers_survive_a_failed_seed(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "seed.db"))

    def unavailable(*args, **kwargs):
        raise RuntimeError("database down")

    db.initialize_company = unavailable
    with TestClient(_company_os(db).get_app(), raise_server_exceptions=False) as client:
        _assert_managers_answer(client)
    db.close()


def test_adapter_without_company_details_keeps_managers_working():
    from agno.db.in_memory import InMemoryDb

    with TestClient(_company_os(InMemoryDb()).get_app(), raise_server_exceptions=False) as client:
        _assert_managers_answer(client)
        assert client.get("/company/details").status_code == 503


def test_company_details_failure_keeps_managers_working(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "failure.db"))
    with TestClient(_company_os(db).get_app(), raise_server_exceptions=False) as client:

        def unavailable():
            raise RuntimeError("database down")

        db.get_company = unavailable
        _assert_managers_answer(client)
    db.close()


def test_synchronous_manager_run_with_asynchronous_company_database(tmp_path):
    from agno.db.sqlite import AsyncSqliteDb
    from agno.os import OSManager

    model = _offline_model()
    os = AgentOS(
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
        manager=OSManager(model=model, access_docs=False, offload_tool_results=False),
        company=CompanyConfig(db=AsyncSqliteDb(db_file=str(tmp_path / "company.db")), model=model),
        telemetry=False,
    )
    assert os.manager.run("hello").content == "local answer"


def test_reading_details_does_not_write_once_the_row_exists(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "read.db"))
    os = AgentOS(db=db, company=CompanyConfig(name="Acme"), telemetry=False)
    with TestClient(os.get_app()) as client:

        def no_writes(*args, **kwargs):
            raise AssertionError("A read must not initialize an existing row")

        db.initialize_company = no_writes
        assert client.get("/company/details").json()["name"] == "Acme"
    db.close()


@pytest.mark.parametrize(
    "change",
    [
        {"name": "a\x00b"},
        {"description": "a\x00b"},
        {"name": "  "},
        {"name": None},
        {"name": "x" * 256},
        {"description": "x" * 20001},
        {"id": "second"},
    ],
)
def test_invalid_details_are_rejected_by_the_request_model(tmp_path, change):
    db = SqliteDb(db_file=str(tmp_path / "invalid.db"))
    client = TestClient(AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app())
    version = client.get("/company/details").json()["updated_at"]
    assert client.patch("/company/details", json={"expected_updated_at": version, **change}).status_code == 422
    db.close()


def test_version_outside_the_stored_range_is_rejected(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "version.db"))
    client = TestClient(AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app())
    client.get("/company/details")
    assert client.patch("/company/details", json={"expected_updated_at": 2**70, "name": "x"}).status_code == 422
    db.close()


def test_custom_admin_scope_controls_who_can_edit(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "admin.db"))
    auth = Authorization(
        verification_keys=[SECRET], algorithm="HS256", audience="details-test", admin_scope="platform:admin"
    )
    os = AgentOS(id="details-test", db=db, company=CompanyConfig(), authorization=auth, telemetry=False)
    client = TestClient(os.get_app())
    version = client.get("/company/details", headers=headers(["platform:admin"])).json()["updated_at"]
    body = {"expected_updated_at": version, "name": "Edited"}
    readers = ["company:read"]
    assert client.get("/company/details/access", headers=headers(["agent_os:admin", *readers])).json() == {
        "can_edit": False
    }
    assert client.patch("/company/details", json=body, headers=headers(["agent_os:admin"])).status_code == 403
    assert client.get("/company/details/access", headers=headers(["platform:admin"])).json() == {"can_edit": True}
    assert client.patch("/company/details", json=body, headers=headers(["platform:admin"])).status_code == 200
    db.close()


class CompanyEditModel(Model):
    """Script delegation/edit calls and echo fresh context without a provider."""

    def __init__(self, delegate=False):
        super().__init__(id="offline-company-edit", provider="test")
        self.delegate = delegate

    def invoke(self, messages, *args, **kwargs):
        start = max(i for i, message in enumerate(messages) if message.role == "user")
        results = [message for message in messages[start + 1 :] if message.role == "tool"]
        if results:
            return ModelResponse(role="assistant", content=str(results[-1].content), response_usage=MessageMetrics())
        if "What does our company do?" in str(messages[start].content):
            context = "\n".join(str(message.content) for message in messages if message.role == "system")
            return ModelResponse(role="assistant", content=context, response_usage=MessageMetrics())
        name = "delegate_task_to_member" if self.delegate else "update_company_details"
        arguments = (
            {"member_id": "company-manager", "task": "Our company is Acme. We build warehouse robots."}
            if self.delegate
            else {"changes": {"name": "Acme", "description": "We build warehouse robots."}}
        )
        return ModelResponse(
            role="assistant",
            tool_calls=[
                {
                    "id": "edit-details",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
            response_usage=MessageMetrics(),
        )

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.mark.parametrize("can_write", [False, True])
def test_chat_delegates_details_edit_with_caller_permissions_and_fresh_context(tmp_path, can_write):
    from agno.os import OSManager

    db_path = str(tmp_path / "chat.db")
    db = SqliteDb(db_file=db_path)
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256", audience="details-test")
    manager = OSManager(model=CompanyEditModel(delegate=True), access_docs=False, offload_tool_results=False)
    company = CompanyConfig(model=CompanyEditModel(), name="Initial", description="Initial description")
    os = AgentOS(db=db, manager=manager, company=company, authorization=auth, telemetry=False)
    scopes = ["teams:superagent:run", "agents:company-manager:run", "company:read"]
    if can_write:
        scopes.append("company:write")
    with TestClient(os.get_app()) as client:
        initial = db.get_company()
        response = client.post(
            "/teams/superagent/runs",
            headers=headers(scopes),
            data={
                "message": "Our company is Acme. We build warehouse robots.",
                "stream": "false",
                "session_id": "introduction",
            },
        )
        assert response.status_code == 200, response.text
        if not can_write:
            assert db.get_company() == initial
            assert "company:write" in response.json()["content"]
            db.close()
            return
        saved = db.get_company()
        assert (saved["name"], saved["description"]) == ("Acme", "We build warehouse robots.")
        assert "Acme" in response.json()["content"]
        assert "We build warehouse robots." in response.json()["content"]
        for path in ("/teams/superagent/runs", "/agents/company-manager/runs"):
            fresh = client.post(
                path,
                headers=headers(scopes),
                data={
                    "message": "What does our company do?",
                    "stream": "false",
                    "session_id": "new-" + path.split("/")[2],
                },
            )
            assert fresh.status_code == 200, fresh.text
            assert '"name": "Acme", "description": "We build warehouse robots."' in fresh.json()["content"]
    db.close()
    fresh_db = SqliteDb(db_file=db_path)
    restarted = AgentOS(
        db=fresh_db, company=CompanyConfig(name="Deployment", description="Changed config"), telemetry=False
    )
    with TestClient(restarted.get_app()):
        assert fresh_db.get_company() == saved
    fresh_db.close()
