"""Company detail edits retain patch semantics and the human caller's authority."""

import inspect
import json

import pytest

from agno.company.execution import _automatic_task, _ExecutorAuthorization
from agno.company.routines import _RoutineAuthorization
from agno.db.sqlite import SqliteDb
from agno.os.auth import INTERNAL_SCHEDULER_USER_ID
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.run import RunContext
from agno.run.authorization import RunAuthorization, authorization_scope
from agno.tools.company import CompanyTools


def authority(scopes, *, principal="alice", service_account=False):
    return RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id=principal, scopes=scopes),
        service_account=service_account,
    )


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def edit(request, tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "details.db"))
    db.initialize_company("Original", "Original description")
    toolkit = CompanyTools(db)
    functions = toolkit.get_async_functions() if request.param else toolkit.functions
    function = functions["update_company_details"]
    function.process_entrypoint()
    assert set(function.parameters["properties"]) == {"name", "description"}
    confirmation = functions["confirm_company_details"]
    confirmation.process_entrypoint()
    assert confirmation.requires_confirmation is True

    async def invoke(changes, auth=None, user="alice", confirm_version=None):
        context = RunContext(run_id="edit", session_id="chat", user_id=user, authorization=auth)
        fn = function if confirm_version is None else confirmation
        arguments = changes if confirm_version is None else {**changes, "expected_updated_at": confirm_version}
        result = fn.entrypoint(**arguments, _agno_run_context=context)
        return json.loads(await result if inspect.isawaitable(result) else result)

    yield db, invoke
    db.close()


@pytest.mark.asyncio
async def test_patch_fields_and_restart(edit):
    db, invoke = edit
    auth = authority(["company:write"])
    renamed = await invoke({"name": "Acme"}, auth)
    assert renamed["name"] == "Acme" and renamed["description"] == "Original description"
    original = db.get_company()
    pending = await invoke({"description": "We build warehouse robots."}, auth)
    assert pending["confirmation_required"] is True
    assert db.get_company() == original
    described = await invoke(pending["changes"], auth, confirm_version=pending["expected_updated_at"])
    assert described["name"] == "Acme" and described["description"] == "We build warehouse robots."
    assert await invoke({"name": "Acme", "description": None}, auth) == described
    # Internal metadata is not part of the saved tool response.
    assert set(described) == {"name", "description", "updated_at", "confirmation_required"}
    assert described["confirmation_required"] is False
    saved = db.get_company()
    db.close()
    fresh = SqliteDb(db_file=db.db_file)
    try:
        assert fresh.initialize_company("Deployment", "Stale configuration") == saved
    finally:
        fresh.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("scopes", [["company:read"], ["products:write"], []])
async def test_missing_write_scope_cannot_change_details(edit, scopes, confirmed):
    db, invoke = edit
    original = db.get_company()
    with pytest.raises(PermissionError, match="company:write"):
        await invoke(
            {"name": "Denied"}, authority(scopes), confirm_version=original["updated_at"] if confirmed else None
        )
    assert db.get_company() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("kind", ["routine", "task", "automatic_task", "service_account", "scheduler"])
async def test_automated_identities_cannot_edit_even_with_admin(edit, kind, confirmed):
    db, invoke = edit
    original = db.get_company()
    auth = authority(["agent_os:admin"])
    if kind == "routine":
        auth = _RoutineAuthorization(auth)
    elif kind == "task":
        auth = _ExecutorAuthorization(auth)
    elif kind == "service_account":
        auth.service_account = True
    elif kind == "scheduler":
        auth.context.principal_id = INTERNAL_SCHEDULER_USER_ID
    token = _automatic_task.set({"id": "running-task"} if kind == "automatic_task" else None)
    try:
        with pytest.raises(PermissionError, match="human.*edit company details"):
            await invoke({"name": "Denied"}, auth, confirm_version=original["updated_at"] if confirmed else None)
        assert db.get_company() == original
    finally:
        _automatic_task.reset(token)


@pytest.mark.asyncio
async def test_no_authorization_configuration_and_scheduler_identity(edit):
    db, invoke = edit
    await invoke({"name": "Trusted application chat"})
    original = db.get_company()
    with pytest.raises(PermissionError, match="human"):
        await invoke({"name": "Denied"}, user=INTERNAL_SCHEDULER_USER_ID)
    assert db.get_company() == original


@pytest.mark.asyncio
async def test_active_caller_overrides_stale_admin_context(edit):
    db, invoke = edit
    original = db.get_company()
    with authorization_scope(lambda: authority(["company:read"])):
        with pytest.raises(PermissionError, match="company:write"):
            await invoke({"name": "Denied"}, authority(["agent_os:admin"]))
    assert db.get_company() == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"name": None, "description": None},
        {"name": " "},
        {"name": "x" * 256},
        {"name": "Acme\x00"},
        {"description": "x" * 2001},
        {"description": ""},
        {"description": 42},
        {"description": "robots\x00"},
    ],
)
async def test_invalid_patch_cannot_change_details(edit, changes):
    db, invoke = edit
    original = db.get_company()
    with pytest.raises(ValueError):
        await invoke(changes)
    assert db.get_company() == original


@pytest.mark.asyncio
async def test_conflict_preserves_intervening_edit_without_retry(edit, monkeypatch):
    db, invoke = edit
    update = db.update_company
    calls = []

    def concurrent_update(expected_updated_at, **fields):
        calls.append(expected_updated_at)
        assert update(expected_updated_at, name="Concurrent winner") is not None
        return update(expected_updated_at, **fields)

    monkeypatch.setattr(db, "update_company", concurrent_update)
    with pytest.raises(ValueError, match="changed concurrently; this edit was not saved"):
        await invoke({"name": "Loser"})
    assert len(calls) == 1
    assert db.get_company()["name"] == "Concurrent winner"


@pytest.mark.asyncio
async def test_async_tool_uses_async_permission_provider(tmp_path):
    class AsyncAuthority(RunAuthorization):
        def require(self, *args, **kwargs):
            raise AssertionError("Async tools must use arequire")

    db = SqliteDb(db_file=str(tmp_path / "async-authority.db"))
    try:
        db.initialize_company("Initial")
        auth = AsyncAuthority(ScopeAuthorizationProvider(), AuthorizationContext(scopes=["company:write"]))
        result = await CompanyTools(db).aupdate_company_details(
            name="Allowed", _agno_run_context=RunContext(run_id="edit", session_id="chat", authorization=auth)
        )
        assert json.loads(result)["name"] == "Allowed"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_description_limit_points_to_playbook_and_does_not_change_http_limit(edit):
    from agno.os.routers.company.details import CompanyDetailsUpdate

    db, invoke = edit
    for size in (2001, 20001):
        with pytest.raises(ValueError, match="2000 characters.*playbook"):
            await invoke({"description": "x" * size})
    assert CompanyDetailsUpdate(expected_updated_at=0, description="x" * 20000).description
    result = await invoke({"description": "x" * 2000, "name": None})
    assert result["name"] == "Original" and len(result["description"]) == 2000


@pytest.mark.asyncio
async def test_pending_confirmation_cannot_overwrite_intervening_edit(edit):
    db, invoke = edit
    await invoke({"name": "Human name"})
    pending = await invoke({"name": "Proposed name"})
    db.update_company(pending["expected_updated_at"], name="Another human's edit")
    with pytest.raises(ValueError, match="this edit was not saved"):
        await invoke(pending["changes"], confirm_version=pending["expected_updated_at"])
    assert db.get_company()["name"] == "Another human's edit"


@pytest.mark.parametrize("operation", ["create Company Products and Routines", "edit company details"])
def test_automated_creation_retains_routine_hint(operation):
    from agno.tools.company import _require_human_creation

    context = RunContext(run_id="routine", session_id="routine", authorization=_RoutineAuthorization(None))
    with pytest.raises(PermissionError) as exc:
        _require_human_creation(context, operation)
    assert ("Routines propose work" in str(exc.value)) == (operation == "create Company Products and Routines")
