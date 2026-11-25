"""A deployment written for agno 3.2.0 starts unchanged.

In 3.2.0 a Goal was a Product and its objective was its purpose. Every name below is what a 3.2.0
deployment wrote in code, in config.yaml, in a token or in a stored role. Each keeps working, and
none logs a warning.
"""

import asyncio
import logging
import sys
import types
import warnings
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agno.company import Goal
from agno.company.declarations import AcceptanceScope, CompanyDeclarations
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from agno.os.authz._scope_policy import resource_matches, scope_to_resource_action
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.config import AuthorizationConfig
from agno.os.scopes import get_accessible_resource_ids, has_required_scopes, parse_scope, split_scope
from agno.run.authorization import RunAuthorization
from agno.utils.log import log_warning

# app/company.py of the agentos-render template at its agno==3.2.0 pin, copied as it is.
RENDER_COMPANY_PY = r'''"""
CompanyOS
=========
"""

from pathlib import Path

from agno.company import Product, Routine, Source

from app.sandbox import REPOSITORY

# Recommended: enable an engineer in app/main.py, then add a line to these instructions
# naming it as the executor for code changes, for example: "Use codex-engineer for code changes."
MAINTENANCE = """\
Keep this AgentOS current, secure and working. Propose only demonstrated problems or
released Agno changes affecting this repository. No new features, tables or refactors.
Most runs should propose nothing.

Read AGENTS.md, the Product status and open Projects and Tasks. Resume unfinished
checks, then scan upgrades, security and quality. Stay within this Product; skip the
company wiki. You have 30 tool calls: reserve the last 3 for updating status.

- Upgrades: compare the Agno pin with newer releases; propose relevant upgrades with
  breaking changes and required checks.
- Security: exposed secrets, weakened authorization, unnecessary tools and dependency
  advisories.
- Quality: conflicting instructions or configuration, ineffective settings and missing
  or failing checks.

Resolve code/docs disagreements using Product context, decisions, tests and history.
Never rewrite docs to excuse weakened protections or tests. Record unclear decisions
in Product status for a person; do not guess.

Propose one bounded Project per finding, named for its outcome, with one Task per PR.
Reuse existing Projects. Cite file/line or release-note evidence, explain the change
and why it matters, and say how to verify it.

Always update Product status before the tool limit: date, latest Agno release reviewed,
checks completed and what to check next, even if the scan is incomplete.
"""

products = [
    Product(
        id="this-agentos",
        name="AgentOS",
        purpose="Keep this AgentOS current, secure and working.",
        sources=[
            Source(type="website", reference="https://github.com/agno-agi/agno/releases"),
            Source(type="git", reference=str(Path(__file__).resolve().parents[1])),
            *([Source(type="git", reference=REPOSITORY.url)] if REPOSITORY is not None else []),
        ],
        routines=[
            # This routine runs on Agno's default routine executor: `miniagent`.
            Routine(
                name="agentos-maintenance",
                # Mondays at 09:00 UTC.
                cron_expr="0 9 * * 1",
                instructions=MAINTENANCE,
                enabled=False,
                auto_accept=False,
            ),
        ],
    ),
]
'''

SECRET = "company-3-2-0-names-tests-secret"
OS_ID = "company-3-2-0-names"
POSTGRES_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
BOTH_TABLES = "Give goals_table or products_table, not both"


@pytest.fixture
def logged():
    """Every warning agno logs and every Python warning raised while the test runs."""
    records = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Collect(level=logging.WARNING)
    loggers = [logging.getLogger(name) for name in ("agno", "agno-team", "agno-workflow")]
    for logger in loggers:
        logger.addHandler(handler)
    # The capture is checked first, so an empty list below means nothing was logged.
    log_warning("capture check")
    assert records == ["capture check"]
    records.clear()
    with warnings.catch_warnings(record=True) as raised:
        warnings.simplefilter("always")
        yield records, raised
    for logger in loggers:
        logger.removeHandler(handler)


def _assert_silent(logged):
    records, raised = logged
    assert records == []
    renamed = ("product", "purpose", "goal", "objective")
    assert [str(w.message) for w in raised if any(word in str(w.message).lower() for word in renamed)] == []


def _template_declarations(tmp_path, monkeypatch):
    """Run the template's app/company.py and return what app/main.py imports from it."""
    sandbox = types.ModuleType("app.sandbox")
    sandbox.REPOSITORY = None
    monkeypatch.setitem(sys.modules, "app", types.ModuleType("app"))
    monkeypatch.setitem(sys.modules, "app.sandbox", sandbox)
    path = tmp_path / "app" / "company.py"
    path.parent.mkdir()
    namespace = {"__file__": str(path), "__name__": "app.company"}
    exec(compile(RENDER_COMPANY_PY, str(path), "exec"), namespace)
    return namespace["products"]


def test_the_render_template_declarations_start_unchanged(tmp_path, monkeypatch, logged):
    products = _template_declarations(tmp_path, monkeypatch)
    db = SqliteDb(db_file=str(tmp_path / "template.db"))
    # The same call app/main.py makes.
    company = CompanyConfig(products=products, model=OpenAIResponses(id="offline"))
    agent_os = AgentOS(db=db, company=company, telemetry=False)

    with TestClient(agent_os.get_app()) as client:
        goals = client.get("/company/goals").json()["data"]
        sources = client.get("/company/sources", params={"goal_id": "this-agentos"}).json()["data"]
        routines = client.get("/company/routines", params={"goal_id": "this-agentos"}).json()["data"]
    db.close()

    assert [goal["id"] for goal in goals] == ["this-agentos"]
    assert goals[0]["name"] == "AgentOS"
    assert goals[0]["objective"] == "Keep this AgentOS current, secure and working."
    assert sorted(source["type"] for source in sources) == ["git", "website"]
    assert [routine["name"] for routine in routines] == ["this-agentos.agentos-maintenance"]
    _assert_silent(logged)


def test_config_yaml_products_start_unchanged(tmp_path, logged):
    config = tmp_path / "config.yaml"
    config.write_text(
        "company:\n"
        "  products:\n"
        "    - id: this-agentos\n"
        "      name: AgentOS\n"
        "      purpose: Keep this AgentOS current, secure and working.\n"
    )
    db = SqliteDb(db_file=str(tmp_path / "yaml.db"))

    with TestClient(AgentOS(db=db, config=str(config), telemetry=False).get_app()) as client:
        goals = client.get("/company/goals").json()["data"]
    db.close()

    assert [(goal["id"], goal["objective"]) for goal in goals] == [
        ("this-agentos", "Keep this AgentOS current, secure and working.")
    ]
    _assert_silent(logged)


def test_product_is_goal():
    from agno.company import Product

    assert Product is Goal
    assert Product(name="AgentOS", purpose="Keep it working.").objective == "Keep it working."


def test_a_stored_policy_scope_reads_product_ids():
    assert AcceptanceScope(product_ids=["this-agentos"]).goal_ids == ["this-agentos"]
    assert AcceptanceScope.model_validate({"product_ids": ["a"], "project_ids": None}).goal_ids == ["a"]


@pytest.mark.parametrize(
    "both, message",
    [
        (lambda path: Goal(name="AgentOS", purpose="old", objective="new"), "Give objective or purpose, not both"),
        (
            lambda path: CompanyDeclarations.model_validate({"goals": [{"name": "A"}], "products": [{"name": "B"}]}),
            "Give goals or products, not both",
        ),
        (lambda path: AcceptanceScope(goal_ids=["a"], product_ids=["b"]), "Give goal_ids or product_ids, not both"),
        (lambda path: SqliteDb(db_file=path, goals_table="a", products_table="b"), BOTH_TABLES),
        (lambda path: AsyncSqliteDb(db_file=path, goals_table="a", products_table="b"), BOTH_TABLES),
        (lambda path: PostgresDb(db_url=POSTGRES_URL, goals_table="a", products_table="b"), BOTH_TABLES),
        (lambda path: AsyncPostgresDb(db_url=POSTGRES_URL, goals_table="a", products_table="b"), BOTH_TABLES),
    ],
    ids=[
        "goal",
        "declarations",
        "acceptance-scope",
        "sqlite",
        "async-sqlite",
        "postgres",
        "async-postgres",
    ],
)
def test_giving_both_names_is_an_error(tmp_path, both, message):
    with pytest.raises((ValueError, ValidationError), match=message):
        both(str(tmp_path / "both.db"))


def test_config_yaml_with_goals_and_products_is_an_error(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("company:\n  goals:\n    - name: A\n  products:\n    - name: B\n")

    with pytest.raises(Exception, match="Give goals or products, not both"):
        AgentOS(db=SqliteDb(db_file=str(tmp_path / "both.db")), config=str(config), telemetry=False)


@pytest.mark.parametrize(
    "make",
    [
        lambda path, **tables: SqliteDb(db_file=path, **tables),
        lambda path, **tables: AsyncSqliteDb(db_file=path, **tables),
        lambda path, **tables: PostgresDb(db_url=POSTGRES_URL, **tables),
        lambda path, **tables: AsyncPostgresDb(db_url=POSTGRES_URL, **tables),
    ],
    ids=["sqlite", "async-sqlite", "postgres", "async-postgres"],
)
def test_products_table_names_the_goals_table(tmp_path, make, logged):
    db = make(str(tmp_path / "named.db"), products_table="my_products")

    assert db.goals_table_name == "my_products"
    assert db.company_table_name == "my_products_details"
    assert make(str(tmp_path / "default.db")).goals_table_name == "agno_company_goals"
    _assert_silent(logged)


@pytest.mark.parametrize("cls", [SqliteDb, AsyncSqliteDb, PostgresDb, AsyncPostgresDb])
def test_a_db_serialized_by_3_2_0_loads(tmp_path, cls):
    connection = {"db_url": POSTGRES_URL} if "Postgres" in cls.__name__ else {"db_file": str(tmp_path / "saved.db")}

    # 3.2.0 wrote the table name on every db, so its default means the table was never named.
    legacy_default = cls.from_dict({**connection, "products_table": "agno_company_products"})
    assert legacy_default.goals_table_name == "agno_company_goals"
    assert cls.from_dict({**connection, "products_table": "my_products"}).goals_table_name == "my_products"
    assert cls.from_dict({**connection, "goals_table": "my_goals"}).goals_table_name == "my_goals"
    assert cls.from_dict(connection).goals_table_name == "agno_company_goals"


def test_a_component_saved_by_3_2_0_keeps_the_registered_db(tmp_path):
    from agno.db.utils import resolve_db_from_config

    registered = SqliteDb(db_file=str(tmp_path / "registered.db"), id="os-db")

    class _Registry:
        def get_db(self, db_id):
            return registered if db_id == "os-db" else None

    # 3.2.0 saved the db with the old key in place of goals_table.
    saved = registered.to_dict()
    saved["products_table"] = "agno_company_products"
    del saved["goals_table"]

    assert resolve_db_from_config(saved, registry=_Registry()) is registered


@pytest.mark.parametrize("cls", [SqliteDb, AsyncSqliteDb])
def test_a_component_saved_by_3_2_0_keeps_its_table_name_with_a_registry(tmp_path, cls):
    from agno.db.utils import resolve_db_from_config

    registered = cls(db_file=str(tmp_path / "registered.db"), id="os-db")

    class _Registry:
        def get_db(self, db_id):
            return registered

    saved = registered.to_dict()
    saved["products_table"] = "my_products"
    del saved["goals_table"]

    resolved = resolve_db_from_config(saved, registry=_Registry())

    assert resolved.goals_table_name == "my_products"
    assert resolved.company_table_name == "my_products_details"
    assert resolved.db_engine is registered.db_engine
    assert "products_table" in saved and "goals_table" not in saved


def _headers(scopes):
    token = jwt.encode(
        {
            "sub": "alice",
            "aud": OS_ID,
            "scopes": scopes,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def authorized_client(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "scopes.db"))
    agent_os = AgentOS(
        id=OS_ID,
        db=db,
        company=CompanyConfig(goals=[Goal(id="this-agentos", name="AgentOS")]),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256"),
    )
    with TestClient(agent_os.get_app()) as client:
        yield client
    db.close()


def test_a_token_with_products_scopes_uses_the_goals_routes(authorized_client, logged):
    client = authorized_client

    listed = client.get("/company/goals", headers=_headers(["products:read"]))
    assert listed.status_code == 200
    assert [goal["id"] for goal in listed.json()["data"]] == ["this-agentos"]
    assert client.get("/company/goals/this-agentos", headers=_headers(["products:read"])).status_code == 200

    created = client.post("/company/goals", json={"name": "Docs"}, headers=_headers(["products:write"]))
    assert created.status_code == 201
    goal_id = created.json()["id"]
    assert client.delete("/company/goals/" + goal_id, headers=_headers(["products:delete"])).status_code == 204
    _assert_silent(logged)


def test_a_token_without_the_scope_is_refused(authorized_client):
    client = authorized_client

    assert client.get("/company/goals", headers=_headers(["tasks:read"])).status_code == 403
    assert client.get("/company/goals", headers=_headers([])).status_code == 403
    # Each products scope stands for the goals scope with the same action, and no other.
    assert client.post("/company/goals", json={"name": "Docs"}, headers=_headers(["products:read"])).status_code == 403
    assert client.delete("/company/goals/this-agentos", headers=_headers(["products:write"])).status_code == 403


def test_products_scopes_satisfy_goals_scopes_in_a_tool_call():
    def authority(scopes):
        return RunAuthorization(ScopeAuthorizationProvider(), AuthorizationContext(principal_id="alice", scopes=scopes))

    authority(["products:read"]).require("goals", "read")
    authority(["products:write"]).require("goals", "write")
    with pytest.raises(PermissionError):
        authority(["products:read"]).require("goals", "write")
    with pytest.raises(PermissionError):
        authority(["tasks:read"]).require("goals", "read")
    assert has_required_scopes(["goals:read"], ["goals:read"])


def test_a_role_stored_by_3_2_0_still_grants_goals(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    store = Authorization(db=db)
    # The policy rows 3.2.0 saved for a role that held products:read and products:write.
    db.upsert_authz_policy(role="company-editor", resource="products/*", action="read", effect="allow")
    db.upsert_authz_policy(role="company-editor", resource="products/*", action="write", effect="allow")
    engine = store._store()._engine

    assert engine.check_scope("goals:read", roles=["company-editor"]) is True
    assert engine.check_scope("goals:write", roles=["company-editor"]) is True
    assert engine.check_scope("goals:delete", roles=["company-editor"]) is False
    assert engine.check_scope("tasks:read", roles=["company-editor"]) is False
    db.close()


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("scope", ["products:write", "goals:write", "goals:docs:write"])
async def test_a_scope_stored_by_3_2_0_can_be_revoked(tmp_path, scope, use_async):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    resource = "products/docs" if ":docs:" in scope else "products/*"
    db.upsert_authz_policy(role="editor", resource=resource, action="write", effect="allow")
    db.upsert_authz_policy(role="editor", resource=resource, action="read", effect="allow")
    engine = Authorization(db=db)._store()._engine
    assert engine.check_resource("goals", "docs", "write", roles=["editor"]) is True

    if use_async:
        await engine.aremove_scope("editor", scope)
    else:
        engine.remove_scope("editor", scope)

    assert engine.check_resource("goals", "docs", "write", roles=["editor"]) is False
    assert engine.check_resource("goals", "docs", "read", roles=["editor"]) is True
    db.close()


@pytest.mark.parametrize("use_async", [False, True])
async def test_a_deny_stored_by_3_2_0_can_be_changed_to_allow(tmp_path, use_async):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    db.upsert_authz_policy(role="editor", resource="products/*", action="write", effect="deny")
    engine = Authorization(db=db)._store()._engine

    if use_async:
        await engine.aadd_scope("editor", "goals:write")
    else:
        engine.add_scope("editor", "goals:write")

    assert engine.check_scope("goals:write", roles=["editor"]) is True
    assert engine.get_role_scopes("editor") == [("goals:write", "allow")]
    db.close()


def test_a_role_saved_with_a_products_scope_grants_goals(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    store = Authorization(db=db)
    store.set_role_scopes("company-reader", ["products:read"])

    assert store._store()._engine.check_scope("goals:read", roles=["company-reader"]) is True
    db.close()


@pytest.mark.parametrize("use_async", [False, True])
async def test_stored_products_policies_filter_lists(tmp_path, use_async):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    db.upsert_authz_policy(role="reader", resource="products/*", action="read", effect="allow")
    db.upsert_authz_policy(role="reader", resource="products/secret", action="read", effect="deny")
    engine = Authorization(db=db)._store()._engine

    for resource_type in ("goals", "products"):
        if use_async:
            allowed = await engine.aaccessible_resource_ids(resource_type, "read", roles=["reader"])
            denied = await engine.adenied_resource_ids(resource_type, "read", roles=["reader"])
        else:
            allowed = engine.accessible_resource_ids(resource_type, "read", roles=["reader"])
            denied = engine.denied_resource_ids(resource_type, "read", roles=["reader"])
        assert allowed == {"*"} and denied == {"secret"}
        assert engine.check_resource(resource_type, "docs", "read", roles=["reader"]) is True
        assert engine.check_resource(resource_type, "secret", "read", roles=["reader"]) is False
    db.close()


# products is the 3.2.0 name of the goals permission. The two names are one permission.


def test_products_and_goals_are_one_permission_in_a_token():
    for held, required in (("products", "goals"), ("goals", "products"), ("products", "products")):
        assert has_required_scopes([f"{held}:read"], [f"{required}:read"])
        assert has_required_scopes([f"{held}:*:read"], [f"{required}:read"])
        assert not has_required_scopes([f"{held}:read"], [f"{required}:write"])
        # One Goal, named by id.
        one = [f"{held}:docs:read"]
        assert has_required_scopes(one, [f"{required}:read"], resource_type=required, resource_id="docs")
        assert not has_required_scopes(one, [f"{required}:read"], resource_type=required, resource_id="other")
        assert not has_required_scopes(one, [f"{required}:read"])
        assert get_accessible_resource_ids(one, required) == {"docs"}
        assert get_accessible_resource_ids([f"{held}:read"], required) == {"*"}
        assert get_accessible_resource_ids(one, required, action="write") == set()
    assert not has_required_scopes(["products:read"], ["tasks:read"])
    assert not has_required_scopes(["tasks:read"], ["products:read"])
    # A scope is shown under the current name; raw keeps what was written.
    assert parse_scope("products:read").resource == "goals"
    assert parse_scope("products:read").raw == "products:read"
    assert split_scope("products:docs:read") == ("goals", "docs", "read")


def test_a_products_requirement_of_an_application_is_read_the_same_way(tmp_path):
    from fastapi import APIRouter

    from agno.os.interfaces.base import BaseInterface

    class Catalog(BaseInterface):
        """Routes of an application that has a products permission of its own."""

        type = "catalog"
        prefix = "/catalog"

        def get_router(self, **kwargs):
            router = APIRouter(prefix=self.prefix)

            @router.get("/products")
            def products():
                return {"products": ["chair"]}

            return router

        def get_scope_mappings(self):
            return {f"GET {self.prefix}/products": ["products:read"]}

    db = SqliteDb(db_file=str(tmp_path / "catalog.db"))
    agent_os = AgentOS(
        id=OS_ID,
        db=db,
        interfaces=[Catalog()],
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256"),
    )

    with TestClient(agent_os.get_app()) as client:
        assert client.get("/catalog/products", headers=_headers(["products:read"])).status_code == 200
        # The one permission under its current name.
        assert client.get("/catalog/products", headers=_headers(["goals:read"])).status_code == 200
        assert client.get("/catalog/products", headers=_headers(["tasks:read"])).status_code == 403
        assert client.get("/catalog/products", headers=_headers(["products:write"])).status_code == 403
    db.close()


def test_the_system_scope_and_the_config_scope_are_read_as_before():
    assert has_required_scopes(["system:read"], ["config:read"])
    assert has_required_scopes(["config:read"], ["system:read"])
    assert has_required_scopes(["system:dep-1:read"], ["config:read"], resource_type="config", resource_id="dep-1")
    assert not has_required_scopes(["system:read"], ["config:write"])
    assert not has_required_scopes(["system:read"], ["registry:read"])
    assert get_accessible_resource_ids(["system:dep-1:read"], "config") == {"dep-1"}
    assert parse_scope("system:read").resource == "config"
    assert split_scope("system:read") == ("config", None, "read")
    # A role stores a system scope under config, and a row under system matches nothing.
    assert scope_to_resource_action("system:read") == ("config/*", "read")
    assert scope_to_resource_action("products:read") == ("goals/*", "read")
    assert not resource_matches("system/*", "config/*")
    assert not resource_matches("config/*", "system/*")


@pytest.mark.parametrize("use_async", [False, True])
async def test_products_and_goals_are_one_permission_in_a_role(tmp_path, use_async):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    store = Authorization(db=db)
    store.set_role_scopes("goal-reader", ["goals:read"])
    store.set_role_scopes("product-reader", ["products:read"])
    engine = store._store()._engine

    async def holds(scope, role):
        if use_async:
            return await engine.acheck_scope(scope, roles=[role])
        return engine.check_scope(scope, roles=[role])

    for role in ("goal-reader", "product-reader"):
        assert await holds("goals:read", role) is True
        assert await holds("products:read", role) is True
        assert await holds("products:docs:read", role) is True
        assert await holds("goals:write", role) is False
        assert engine.check_resource("products", "docs", "read", roles=[role]) is True
        assert engine.check_resource("goals", "docs", "read", roles=[role]) is True
    # Both are stored under the current name.
    assert db.get_authz_role_policies("goal-reader") == db.get_authz_role_policies("product-reader")
    assert db.get_authz_role_policies("product-reader") == [("goals/*", "read", "allow")]
    db.close()


async def _patch(store, use_async, role, upsert=None, remove=None):
    if use_async:
        await store._apatch_role_scopes(role, upsert=upsert, remove=remove)
    else:
        store._patch_role_scopes(role, upsert=upsert, remove=remove)


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("name", ["goals", "products"])
async def test_granting_either_name_on_a_stored_3_2_0_row_leaves_one_grant(tmp_path, name, use_async):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    # The row 3.2.0 stored for a role that held products:read.
    db.upsert_authz_policy(role="reader", resource="products/*", action="read", effect="allow")
    store = Authorization(db=db)
    engine = store._store()._engine
    assert engine.check_scope("goals:read", roles=["reader"]) is True

    await _patch(store, use_async, "reader", upsert=[f"{name}:read"])

    assert db.get_authz_role_policies("reader") == [("goals/*", "read", "allow")]
    assert engine.check_scope("goals:read", roles=["reader"]) is True
    db.close()


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("name", ["goals", "products"])
@pytest.mark.parametrize("stored", ["products/*", "goals/*"])
async def test_removing_either_name_removes_the_goals_grant(tmp_path, stored, name, use_async):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    db.upsert_authz_policy(role="reader", resource=stored, action="read", effect="allow")
    db.upsert_authz_policy(role="reader", resource="tasks/*", action="read", effect="allow")
    store = Authorization(db=db)
    engine = store._store()._engine

    await _patch(store, use_async, "reader", remove=[f"{name}:read"])

    assert db.get_authz_role_policies("reader") == [("tasks/*", "read", "allow")]
    assert engine.check_scope("goals:read", roles=["reader"]) is False
    assert engine.check_scope("products:read", roles=["reader"]) is False
    db.close()


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("name", ["goals", "products"])
@pytest.mark.parametrize("stored", ["products/*", "goals/*"])
async def test_a_deny_on_either_name_denies_both(tmp_path, stored, name, use_async):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    db.upsert_authz_policy(role="reader", resource=stored, action="read", effect="allow")
    store = Authorization(db=db)
    engine = store._store()._engine

    await _patch(store, use_async, "reader", upsert=[{"scope": f"{name}:read", "effect": "deny"}])

    assert db.get_authz_role_policies("reader") == [("goals/*", "read", "deny")]
    for checked in ("goals:read", "products:read"):
        assert engine.check_scope(checked, roles=["reader"]) is False
    assert engine.denied_resource_ids("goals", "read", roles=["reader"]) == {"*"}
    assert engine.denied_resource_ids("products", "read", roles=["reader"]) == {"*"}
    db.close()


def test_a_service_account_token_carries_products_only_from_a_holder_of_the_permission():
    from agno.os.routers.service_accounts.router import _caller_holds_scope

    for held in ("goals", "products"):
        assert _caller_holds_scope([f"{held}:read"], "products:read", None)
        assert _caller_holds_scope([f"{held}:read"], "goals:read", None)
        assert _caller_holds_scope([f"{held}:docs:read"], "products:docs:read", None)
        assert not _caller_holds_scope([f"{held}:read"], "products:write", None)
        assert not _caller_holds_scope([f"{held}:docs:read"], "products:read", None)
    assert not _caller_holds_scope(["tasks:read", "agents:read"], "products:read", None)
    assert not _caller_holds_scope([], "products:read", None)


@pytest.mark.parametrize("scope", ["application:products:*:read", "application:products:read"])
def test_no_row_is_stored_apart_from_the_one_permission(tmp_path, scope):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    store = Authorization(db=db)

    if scope.count(":") == 3:
        # Four parts is not a scope.
        with pytest.raises(ValueError):
            store.set_role_scopes("reader", [scope])
        with pytest.raises(ValueError):
            store._patch_role_scopes("reader", upsert=[scope])
        assert db.get_authz_role_policies("reader") == []
    else:
        # "application" is an ordinary resource type here, with no tie to products or goals.
        store.set_role_scopes("reader", [scope])
        engine = store._store()._engine
        assert engine.check_scope("products:read", roles=["reader"]) is False
        assert engine.check_scope("goals:read", roles=["reader"]) is False
    for resource, _action, _effect in db.get_authz_role_policies("reader"):
        assert not resource.startswith("application:")
    db.close()


@pytest.mark.parametrize(
    "saved, expected", [("custom_products", "custom_products"), ("agno_company_products", "agno_company_goals")]
)
def test_the_component_api_reads_products_table(tmp_path, saved, expected):
    from agno.os.routers.components.components import _resolve_db_in_config

    db = SqliteDb(db_file=str(tmp_path / "os.db"), id="os-db")
    config = _resolve_db_in_config({"db": {"id": "os-db", "products_table": saved}}, db)

    assert config["db"]["goals_table"] == expected
    assert "products_table" not in config["db"]


def test_a_stored_system_policy_does_not_match_config():
    assert not resource_matches("system/*", "config/*")


def test_the_3_2_0_names_can_be_read_and_set():
    goal = Goal(name="Docs", purpose="First")
    goal.purpose = "Second"
    assert (goal.purpose, goal.objective) == ("Second", "Second")
    assert "purpose" not in goal.model_dump()
    assert AcceptanceScope(goal_ids=["docs"]).product_ids == ["docs"]
    assert CompanyDeclarations(goals=[goal]).products == [goal]

    config = CompanyConfig()
    config.products = [goal]
    config.products.append(goal)
    assert config.goals == [goal, goal]
    assert replace(CompanyConfig(products=[goal]), goals=[]).goals == []


def test_a_stored_products_policy_matches_only_goals():
    assert resource_matches("products/*", "goals/*")
    assert resource_matches("products/*", "goals/this-agentos")
    assert resource_matches("products/this-agentos", "goals/this-agentos")
    assert not resource_matches("products/this-agentos", "goals/other")
    assert not resource_matches("products/*", "tasks/*")


# --------------------------------------------- a component saved on the default table


@pytest.mark.parametrize("cls", [SqliteDb, AsyncSqliteDb])
def test_a_component_saved_by_3_2_0_on_the_default_table_stays_on_it(tmp_path, cls):
    from agno.db.utils import resolve_db_from_config

    # The registered db names its Goals table. The component was saved on the default one.
    registered = cls(db_file=str(tmp_path / "registered.db"), id="os-db", goals_table="my_goals")

    class _Registry:
        def get_db(self, db_id):
            return registered

    saved = registered.to_dict()
    saved["products_table"] = "agno_company_products"
    del saved["goals_table"]

    resolved = resolve_db_from_config(saved, registry=_Registry())

    assert resolved.goals_table_name == "agno_company_goals"
    assert resolved.company_table_name == "agno_company_goals_details"
    assert resolved.db_engine is registered.db_engine
    assert registered.goals_table_name == "my_goals"


def test_the_component_api_keeps_a_3_2_0_component_on_the_default_table(tmp_path):
    from agno.os.routers.components.components import _resolve_db_in_config

    db = SqliteDb(db_file=str(tmp_path / "os.db"), id="os-db", goals_table="my_goals")
    config = _resolve_db_in_config({"db": {"id": "os-db", "products_table": "agno_company_products"}}, db)

    assert config["db"]["goals_table"] == "agno_company_goals"
    assert "products_table" not in config["db"]
    # A component that names no Goals table takes the one the OS db uses.
    assert _resolve_db_in_config({"db": {"id": "os-db"}}, db)["db"]["goals_table"] == "my_goals"


# ------------------------------------------------- one config derived from another


def test_replace_with_products_derives_a_config_that_has_goals():
    first, second = Goal(name="Docs"), Goal(name="Website")
    config = CompanyConfig(goals=[first], name="Acme")

    derived = replace(config, products=[second])

    assert derived.goals == [second] and derived.products == [second]
    assert derived.name == "Acme"
    assert config.goals == [first]
    assert replace(CompanyConfig(products=[first]), products=[second]).goals == [second]
    assert replace(config, products=[]).goals == []
    assert replace(config, name="Other").goals == [first]
    assert replace(config, goals=[second]).goals == [second]
    # replace passes the copied goals with the new products, as a caller that gives both does. The
    # constructor cannot tell the two apart, so it uses products for both.
    assert CompanyConfig(goals=[first], products=[second]).goals == [second]


# ------------------------------------- an operator's own middleware, mapped for the 3.2.0 paths


# What an operator wrote for agno 3.2.0 to guard the Company Product routes with a JWTMiddleware of their own.
MAPPINGS_FOR_3_2_0 = {
    "GET /company/products": ["products:read"],
    "GET /company/products/*": ["products:read"],
    "POST /company/products": ["products:write"],
    "PATCH /company/products/*": ["products:write"],
    "DELETE /company/products/*": ["products:delete"],
}


def _own_middleware_client(tmp_path, mappings):
    from agno.os.middleware.jwt import JWTMiddleware

    db = SqliteDb(db_file=str(tmp_path / "own.db"))
    agent_os = AgentOS(
        id=OS_ID, db=db, company=CompanyConfig(goals=[Goal(id="this-agentos", name="AgentOS")]), telemetry=False
    )
    app = agent_os.get_app()
    app.add_middleware(
        JWTMiddleware,
        verification_keys=[SECRET],
        algorithm="HS256",
        authorization=True,
        scope_mappings=mappings,
    )
    return db, TestClient(app)


def test_scope_mappings_written_for_the_3_2_0_paths_guard_the_goals_routes(tmp_path):
    db, starting = _own_middleware_client(tmp_path, MAPPINGS_FOR_3_2_0)
    with starting as client:
        # A caller with no Company scope is refused, as on 3.2.0.
        other = _headers(["agents:read"])
        assert client.get("/company/goals", headers=other).status_code == 403
        assert client.get("/company/goals/this-agentos", headers=other).status_code == 403
        assert client.post("/company/goals", json={"name": "Docs"}, headers=other).status_code == 403
        assert client.patch("/company/goals/this-agentos", json={"name": "X"}, headers=other).status_code == 403
        assert client.delete("/company/goals/this-agentos", headers=other).status_code == 403
        # Each action needs its own scope.
        assert client.delete("/company/goals/this-agentos", headers=_headers(["products:read"])).status_code == 403
        # A caller with the scope the operator mapped is let in, under either name.
        for name in ("products", "goals"):
            assert client.get("/company/goals", headers=_headers([f"{name}:read"])).status_code == 200
            assert client.get("/company/goals/this-agentos", headers=_headers([f"{name}:read"])).status_code == 200
    db.close()


def test_a_mapping_for_the_current_path_is_used_as_written(tmp_path):
    mappings = {**MAPPINGS_FOR_3_2_0, "GET /company/goals": ["tasks:read"]}
    db, starting = _own_middleware_client(tmp_path, mappings)
    with starting as client:
        assert client.get("/company/goals", headers=_headers(["tasks:read"])).status_code == 200
        assert client.get("/company/goals", headers=_headers(["goals:read"])).status_code == 403
        # The paths the operator did not map again take the 3.2.0 mapping.
        assert client.get("/company/goals/this-agentos", headers=_headers(["goals:read"])).status_code == 200
        assert client.get("/company/goals/this-agentos", headers=_headers(["tasks:read"])).status_code == 403
    db.close()


# ------------------------------------------------------- a client written for agno 3.2.0


@pytest.fixture
def company_client(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "client.db"))
    agent_os = AgentOS(
        db=db,
        company=CompanyConfig(goals=[Goal(id="docs", name="Docs", objective="Keep the docs accurate.")]),
        telemetry=False,
    )
    with TestClient(agent_os.get_app()) as client:
        other = client.post("/company/goals", json={"name": "Website"}).json()["id"]
        for goal_id in ("docs", other):
            created = client.post("/company/projects", json={"goal_id": goal_id, "name": "Project of " + goal_id[:4]})
            assert created.status_code in (200, 201), created.text
        yield client
    db.close()


@pytest.mark.parametrize(
    "path", ["/company/projects", "/company/tasks", "/company/sources", "/company/routines", "/company/attention"]
)
def test_the_3_2_0_filter_is_refused_and_not_ignored(company_client, path):
    # Ignored, product_id=docs would answer with the records of every Goal.
    refused = company_client.get(path, params={"product_id": "docs"})
    assert refused.status_code == 422, refused.text
    assert "goal_id" in refused.text
    assert company_client.get(path, params={"goal_id": "docs", "product_id": "docs"}).status_code == 422
    assert company_client.get(path, params={"goal_id": "docs"}).status_code == 200
    assert company_client.get(path).status_code == 200


def test_the_goal_filter_narrows_the_list(company_client):
    listed = company_client.get("/company/projects", params={"goal_id": "docs"}).json()
    assert listed["meta"]["total_count"] == 1
    assert company_client.get("/company/projects").json()["meta"]["total_count"] == 2


def test_purpose_in_a_goal_body_is_refused_and_not_dropped(company_client):
    patched = company_client.patch("/company/goals/docs", json={"purpose": "New aim"})
    assert patched.status_code == 422, patched.text
    assert "objective" in patched.text
    assert company_client.get("/company/goals/docs").json()["objective"] == "Keep the docs accurate."
    created = company_client.post("/company/goals", json={"name": "Blog", "purpose": "Write"})
    assert created.status_code == 422, created.text
    assert company_client.patch("/company/goals/docs", json={"objective": "New aim"}).json()["objective"] == "New aim"


@pytest.mark.parametrize("by_keyword", [False, True])
async def test_rehydrate_product_declares_a_goal(tmp_path, by_keyword):
    from agno.company.bootstrap import arehydrate_product, rehydrate_product

    declared = Goal(id="docs", name="Docs", objective="Keep the docs accurate.")
    # The sync name, the way the 3.2 weekly review cookbook calls it.
    sync_db = SqliteDb(db_file=str(tmp_path / "sync.db"))
    if by_keyword:
        row = await asyncio.to_thread(rehydrate_product, sync_db, product=declared, trusted=True)
    else:
        row = await asyncio.to_thread(rehydrate_product, sync_db, declared, trusted=True)
    assert row["id"] == "docs" and sync_db.get_goal("docs")["objective"] == "Keep the docs accurate."
    sync_db.close()

    async_db = AsyncSqliteDb(db_file=str(tmp_path / "async.db"))
    if by_keyword:
        row = await arehydrate_product(async_db, product=declared, trusted=True)
    else:
        row = await arehydrate_product(async_db, declared, trusted=True)
    assert row["id"] == "docs" and (await async_db.get_goal("docs"))["name"] == "Docs"
    await async_db.close()
