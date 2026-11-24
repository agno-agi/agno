"""A deployment written for agno 3.2.0 starts unchanged.

In 3.2.0 a Goal was a Product and its objective was its purpose. Every name below is what a 3.2.0
deployment wrote in code, in config.yaml, in a token or in a stored role. Each keeps working, and
none logs a warning.
"""

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
from agno.exceptions import MigrationRequiredError
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from agno.os.authz._scope_policy import resource_matches
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.config import AuthorizationConfig
from agno.os.scopes import has_required_scopes
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
            lambda path: CompanyConfig(goals=[Goal(name="A")], products=[Goal(name="B")]),
            "Give goals or products, not both",
        ),
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
        "company-config",
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
    # The stored deny still protects an application's own products type.
    assert sorted(engine.get_role_scopes("editor")) == [("goals:write", "allow"), ("products:write", "deny")]
    assert engine.denied_resource_ids("goals", "write", roles=["editor"]) == set()
    assert engine.denied_resource_ids("products", "write", roles=["editor"]) == {"*"}
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


def test_a_goals_policy_does_not_match_an_application_products_type():
    assert not resource_matches("goals/*", "products/catalog")
    assert resource_matches("products/*", "products/catalog")


@pytest.mark.parametrize("use_async", [False, True])
async def test_granting_goals_keeps_a_stored_products_grant(tmp_path, use_async):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    db.upsert_authz_policy(role="reader", resource="products/*", action="read", effect="allow")
    engine = Authorization(db=db)._store()._engine

    if use_async:
        await engine.aadd_scope("reader", "goals:read")
    else:
        engine.add_scope("reader", "goals:read")

    assert engine.check_resource("products", "catalog", "read", roles=["reader"]) is True
    db.close()


@pytest.mark.parametrize("change", ["add", "remove", "replace"])
@pytest.mark.parametrize("use_async", [False, True])
async def test_changing_goals_access_keeps_an_application_deny(tmp_path, change, use_async):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    db.upsert_authz_policy(role="reader", resource="products/*", action="read", effect="deny")
    db.upsert_authz_policy(role="reader", resource="products/catalog", action="read", effect="allow")
    engine = Authorization(db=db)._store()._engine

    async def call(method, *args):
        return await getattr(engine, "a" + method)(*args) if use_async else getattr(engine, method)(*args)

    if change == "replace":
        await call("set_role_scopes", "reader", [*engine.get_role_scopes("reader"), ("goals:read", "allow")])
    else:
        await call("add_scope", "reader", "goals:read")
    assert engine.check_scope("goals:read", roles=["reader"]) is True
    if change == "remove":
        await call("remove_scope", "reader", "goals:read")
        assert engine.check_scope("goals:read", roles=["reader"]) is False

    assert engine.check_resource("products", "catalog", "read", roles=["reader"]) is False
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


@pytest.mark.parametrize("named", [False, True])
def test_an_unmigrated_company_database_stops_startup(tmp_path, named):
    import sqlite3

    path = str(tmp_path / "company.db")
    table = "my_products" if named else "agno_company_products"
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TABLE {table} (id VARCHAR PRIMARY KEY, name VARCHAR, purpose TEXT)")
    db = SqliteDb(db_file=path, products_table="my_products" if named else None)
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()

    with pytest.raises(MigrationRequiredError) as refused:
        with TestClient(app):
            pass

    # The HTTP migration route is unreachable until the server starts.
    assert "asyncio.run(MigrationManager(db).up())" in str(refused.value)
    assert "await MigrationManager(db).up()" in str(refused.value)
    assert "/databases/all/migrate" not in str(refused.value)


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
