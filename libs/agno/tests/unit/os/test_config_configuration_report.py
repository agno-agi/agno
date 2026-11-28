"""The /config authorization block and feature blocks: what a settings page reads.

Every block reports EFFECTIVE behavior. Every caller that can read /config gets the
authorization mode and the feature blocks, except the user directory, audit and the
public surface; those and the authorization detail go to administrators only.
Nothing in these blocks is a secret or locates one.
"""

import time
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.knowledge.knowledge import Knowledge
from agno.media.storage.local import LocalMediaStorage
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization
from agno.os.authz import UserDirectory
from agno.os.authz.audit import LoggingAuditSink
from agno.os.config import AuthorizationConfig
from agno.os.manager import OSManager
from agno.os.public import PublicSurface
from agno.os.schema import ConfigResponse
from agno.os.settings import AgnoAPISettings
from agno.team import Team
from agno.workflow import Parallel, Step, Workflow

SECRET = "configuration-report-test-key-at-least-32-characters"
OS_KEY = "configuration-report-security-key"
OS_ID = "report-os"
MEMBER_SCOPES = ["config:read", "agents:read"]

ADMIN_ONLY_FIELDS = {"managed_roles", "default_role", "roles_from_token", "token_scopes_trusted", "audience_verified"}
FEATURES_OFF = {
    "user_directory": {"enabled": False, "auto_provision": False, "fail_closed": False},
    "audit": {"enabled": False, "changes_readable": False, "decisions_readable": False},
    "scheduler": {"enabled": False},
    "mcp": {"enabled": False},
    "public": {"enabled": False, "agents": [], "teams": [], "workflows": [], "mcp": False},
    "manager": {"enabled": False},
    "media_storage": {"enabled": False},
    "telemetry": {"enabled": False},
}
ADMIN_ONLY_FEATURES = {"user_directory", "audit", "public"}
PUBLIC_FEATURES_OFF = {k: v for k, v in FEATURES_OFF.items() if k not in ADMIN_ONLY_FEATURES}


def _features(body):
    """The top-level feature blocks without a detail block of their own."""
    return {key: body[key] for key in FEATURES_OFF if key in body}


@pytest.fixture(autouse=True)
def _no_ambient_auth(monkeypatch):
    for name in ("JWT_VERIFICATION_KEY", "JWT_JWKS_FILE", "OS_SECURITY_KEY", "AGNO_TELEMETRY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "report.db"))


def _os(db, **kwargs):
    agent = Agent(id="cfg-agent", name="Cfg Agent", db=db, telemetry=False)
    kwargs.setdefault("db", db)
    return AgentOS(id=OS_ID, agents=[agent], telemetry=False, **kwargs)


def _bearer(sub, scopes=None, aud=OS_ID):
    claims = {"sub": sub, "aud": aud, "exp": int(time.time()) + 300}
    if scopes is not None:
        claims["scopes"] = scopes
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


def _config(agent_os, headers=None):
    resp = TestClient(agent_os.get_app(), raise_server_exceptions=False).get("/config", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp


def _roles(**kwargs):
    """Managed roles: an admin, and a member who can read /config and nothing administrative."""
    kwargs.setdefault("audience", OS_ID)
    authorization = Authorization(verification_keys=[SECRET], algorithm="HS256", **kwargs)
    authorization.define_role("admin", ["agent_os:admin"])
    authorization.define_role("member", MEMBER_SCOPES, default=True)
    authorization.seed(admin="alice")
    authorization.assign("bob", "member")
    return authorization


class TestNoAuth:
    def test_everyone_sees_the_full_report(self, db):
        body = _config(_os(db)).json()
        assert body["authorization"] == {
            "enabled": False,
            "mode": "none",
            "user_isolation": False,
            "managed_roles": False,
            "roles_from_token": False,
            "token_scopes_trusted": False,
            "audience_verified": False,
        }
        assert _features(body) == FEATURES_OFF
        assert body["traces"]["enabled"] is False

    def test_user_isolation_matches_info(self, db):
        app = _os(db, user_isolation=True).get_app()
        client = TestClient(app)
        assert client.get("/config").json()["authorization"]["user_isolation"] is True
        assert client.get("/info").json()["user_isolation"] is True

    def test_name_matches_info(self, db):
        client = TestClient(_os(db, name="Support OS").get_app())
        assert client.get("/config").json()["name"] == "Support OS"
        assert client.get("/info").json()["name"] == "Support OS"


class TestSecurityKey:
    def test_key_holder_counts_as_admin(self, db):
        agent_os = _os(db, settings=AgnoAPISettings(os_security_key=OS_KEY))
        app = agent_os.get_app()
        client = TestClient(app)
        assert client.get("/config").status_code == 401
        resp = client.get("/config", headers={"Authorization": f"Bearer {OS_KEY}"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["authorization"] == {
            "enabled": False,
            "mode": "security_key",
            "user_isolation": False,
            "managed_roles": False,
            "roles_from_token": False,
            "token_scopes_trusted": False,
            "audience_verified": False,
        }
        assert client.get("/info").json()["auth_mode"] == "security_key"
        assert OS_KEY not in resp.text


class TestScopeAuthorization:
    """authorization=True: token scopes decide, and the role store is on beside them."""

    def _scope_os(self, db, verify_audience=None):
        config = AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256", verify_audience=verify_audience)
        return _os(db, authorization=True, authorization_config=config)

    def test_admin_scope_sees_the_detail(self, db):
        body = _config(self._scope_os(db), _bearer("alice", ["agent_os:admin"])).json()
        assert body["authorization"] == {
            "enabled": True,
            "mode": "jwt",
            "user_isolation": False,
            # A SQLite or Postgres database can hold roles, so the role store and /authz are on
            "managed_roles": True,
            "roles_from_token": False,
            "token_scopes_trusted": True,
            "audience_verified": False,
        }

    def test_roles_are_not_managed_on_a_database_that_cannot_hold_them(self):
        memory_db = InMemoryDb()
        agent_os = self._scope_os(memory_db)
        client = TestClient(agent_os.get_app())
        headers = _bearer("alice", ["agent_os:admin"])
        block = client.get("/config", headers=headers).json()["authorization"]
        assert block["managed_roles"] is False
        assert block["token_scopes_trusted"] is True
        assert client.get("/authz/roles", headers=headers).status_code == 404

    def test_a_role_made_at_runtime_decides_requests(self, db):
        client = TestClient(self._scope_os(db).get_app())
        admin = _bearer("alice", ["agent_os:admin"])
        assert client.get("/config", headers=_bearer("bob")).status_code == 403
        assert client.post("/authz/roles", headers=admin, json={"slug": "viewer"}).status_code == 201
        scopes = {"scopes": MEMBER_SCOPES}
        assert client.put("/authz/roles/viewer/scopes", headers=admin, json=scopes).status_code == 200
        assert client.post("/authz/subjects/bob/roles", headers=admin, json={"role": "viewer"}).status_code == 200
        assert client.get("/config", headers=_bearer("bob")).status_code == 200

    def test_non_admin_sees_the_mode_and_no_detail(self, db):
        body = _config(self._scope_os(db), _bearer("bob", MEMBER_SCOPES)).json()
        assert body["authorization"] == {"enabled": True, "mode": "jwt", "user_isolation": False}
        assert _features(body) == PUBLIC_FEATURES_OFF

    def test_audience_check_is_reported_when_it_runs(self, db):
        agent_os = self._scope_os(db, verify_audience=True)
        body = _config(agent_os, _bearer("alice", ["agent_os:admin"])).json()
        assert body["authorization"]["audience_verified"] is True

    def test_jwt_key_from_the_environment_authenticates_without_authorizing(self, db, monkeypatch):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        monkeypatch.setenv("JWT_VERIFICATION_KEY", public_pem.decode())
        client = TestClient(_os(db).get_app())
        token = jwt.encode({"sub": "bob", "exp": int(time.time()) + 300}, key, algorithm="RS256")
        resp = client.get("/config", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        # A verified token and no enforcement: nobody is an administrator, so no detail.
        assert resp.json()["authorization"] == {"enabled": False, "mode": "jwt", "user_isolation": False}
        assert client.get("/info").json()["auth_mode"] == "jwt"
        assert "BEGIN PUBLIC KEY" not in resp.text


class TestManagedRoles:
    def test_admin_role_sees_the_detail(self, db):
        body = _config(_os(db, authorization=_roles()), _bearer("alice")).json()
        assert body["authorization"] == {
            "enabled": True,
            "mode": "jwt",
            "user_isolation": False,
            "managed_roles": True,
            "roles_from_token": False,
            "default_role": "member",
            # Token scopes count beside roles unless trust_token_scopes=False is passed
            "token_scopes_trusted": True,
            "audience_verified": False,
        }

    def test_member_sees_the_mode_and_no_detail(self, db):
        body = _config(_os(db, authorization=_roles()), _bearer("bob")).json()
        assert body["authorization"] == {"enabled": True, "mode": "jwt", "user_isolation": False}
        assert not ADMIN_ONLY_FIELDS & set(body["authorization"])

    def test_admin_scope_on_a_token_is_not_admin_when_roles_decide_alone(self, db):
        agent_os = _os(db, authorization=_roles(trust_token_scopes=False))
        body = _config(agent_os, _bearer("bob", ["agent_os:admin"])).json()
        assert not ADMIN_ONLY_FIELDS & set(body["authorization"])

    def test_scope_plane_beside_roles_is_reported(self, db):
        agent_os = _os(db, authorization=_roles(trust_token_scopes=True))
        block = _config(agent_os, _bearer("alice")).json()["authorization"]
        assert block["managed_roles"] is True
        assert block["token_scopes_trusted"] is True
        # With the scope plane running, the admin scope on a token is an admin path too.
        operator = _config(agent_os, _bearer("operator", ["agent_os:admin"])).json()["authorization"]
        assert operator["token_scopes_trusted"] is True

    def test_no_scope_plane_reports_scopes_untrusted(self, db):
        agent_os = _os(db, authorization=_roles(trust_token_scopes=False))
        assert _config(agent_os, _bearer("alice")).json()["authorization"]["token_scopes_trusted"] is False

    def test_audience_check_is_reported_when_it_runs(self, db):
        agent_os = _os(db, authorization=_roles(verify_audience=True))
        assert _config(agent_os, _bearer("alice")).json()["authorization"]["audience_verified"] is True

    def test_roles_carried_on_the_token_are_reported(self, db):
        agent_os = _os(db, authorization=_roles(roles_claim="roles"))
        assert _config(agent_os, _bearer("alice")).json()["authorization"]["roles_from_token"] is True
        assert "roles_from_token" not in _config(agent_os, _bearer("bob")).json()["authorization"]

    def test_no_default_role_omits_the_field(self, db):
        authorization = Authorization(verification_keys=[SECRET], algorithm="HS256", audience=OS_ID)
        authorization.define_role("admin", ["agent_os:admin"])
        authorization.seed(admin="alice")
        block = _config(_os(db, authorization=authorization), _bearer("alice")).json()["authorization"]
        assert block["managed_roles"] is True
        assert "default_role" not in block

    def test_authorization_object_without_roles_has_the_role_store_beside_token_scopes(self, db):
        authorization = Authorization(verification_keys=[SECRET], algorithm="HS256", audience=OS_ID)
        client = TestClient(_os(db, authorization=authorization).get_app())
        headers = _bearer("alice", ["agent_os:admin"])
        block = client.get("/config", headers=headers).json()["authorization"]
        # No role in code still gets the role store, since the database can hold roles
        assert block["managed_roles"] is True
        assert "default_role" not in block
        assert block["token_scopes_trusted"] is True
        assert client.get("/authz/roles", headers=headers).status_code == 200

    def test_no_roles_and_untrusted_token_scopes_builds_no_role_store(self, db):
        # A store deciding alone would start empty and refuse everyone, so none is built
        authorization = Authorization(
            verification_keys=[SECRET], algorithm="HS256", audience=OS_ID, audit=True, trust_token_scopes=False
        )
        client = TestClient(_os(db, authorization=authorization).get_app())
        headers = _bearer("alice", ["agent_os:admin"])
        body = client.get("/config", headers=headers).json()
        assert body["authorization"]["managed_roles"] is False
        assert body["authorization"]["token_scopes_trusted"] is True
        assert body["audit"] == {"enabled": True, "changes_readable": False, "decisions_readable": False}
        assert client.get("/authz/roles", headers=headers).status_code == 404
        assert client.get("/authz/audit", headers=headers).status_code == 404


class TestFeatureBlocks:
    def test_user_directory_without_authorization(self, db):
        features = _config(_os(db, user_directory=True)).json()
        assert features["user_directory"] == {"enabled": True, "auto_provision": True, "fail_closed": True}

    def test_user_directory_settings_under_roles(self, db):
        directory = UserDirectory(auto_provision=False, fail_closed=False)
        agent_os = _os(db, authorization=_roles(), user_directory=directory)
        features = _config(agent_os, _bearer("alice")).json()
        assert features["user_directory"] == {"enabled": True, "auto_provision": False, "fail_closed": False}

    def test_no_user_directory_under_roles(self, db):
        features = _config(_os(db, authorization=_roles()), _bearer("alice")).json()
        assert features["user_directory"] == {"enabled": False, "auto_provision": False, "fail_closed": False}

    def test_member_does_not_see_directory_or_audit_status(self, db):
        agent_os = _os(db, authorization=_roles(audit=True), user_directory=True)
        assert _features(_config(agent_os, _bearer("bob")).json()) == PUBLIC_FEATURES_OFF

    def test_scope_member_does_not_see_directory_or_audit_status(self, db):
        config = AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256")
        agent_os = _os(db, authorization=True, authorization_config=config, user_directory=True)
        assert _features(_config(agent_os, _bearer("bob", MEMBER_SCOPES)).json()) == PUBLIC_FEATURES_OFF
        admin = _config(agent_os, _bearer("alice", ["agent_os:admin"])).json()
        assert admin["user_directory"]["enabled"] is True

    def test_audit_on_a_database_is_readable(self, db):
        agent_os = _os(db, authorization=_roles(audit=True))
        app = agent_os.get_app()
        client = TestClient(app)
        audit = client.get("/config", headers=_bearer("alice")).json()["audit"]
        assert audit == {"enabled": True, "changes_readable": True, "decisions_readable": True}
        # The report agrees with the routes it describes.
        assert client.get("/authz/audit", headers=_bearer("alice")).status_code == 200
        assert client.get("/authz/decisions", headers=_bearer("alice")).status_code == 200

    def test_audit_off_matches_the_404_the_routes_give(self, db):
        app = _os(db, authorization=_roles()).get_app()
        client = TestClient(app)
        audit = client.get("/config", headers=_bearer("alice")).json()["audit"]
        assert audit == {"enabled": False, "changes_readable": False, "decisions_readable": False}
        assert client.get("/authz/audit", headers=_bearer("alice")).status_code == 404
        assert client.get("/authz/decisions", headers=_bearer("alice")).status_code == 404

    def test_audit_to_a_log_is_recorded_but_not_readable(self, db):
        app = _os(db, authorization=_roles(audit=LoggingAuditSink())).get_app()
        client = TestClient(app)
        audit = client.get("/config", headers=_bearer("alice")).json()["audit"]
        assert audit == {"enabled": True, "changes_readable": False, "decisions_readable": False}
        assert client.get("/authz/audit", headers=_bearer("alice")).status_code == 404
        assert client.get("/authz/decisions", headers=_bearer("alice")).status_code == 404

    def test_audit_without_roles_in_code_is_readable(self, db):
        authorization = Authorization(verification_keys=[SECRET], algorithm="HS256", audience=OS_ID, audit=True)
        app = _os(db, authorization=authorization).get_app()
        client = TestClient(app)
        headers = _bearer("alice", ["agent_os:admin"])
        audit = client.get("/config", headers=headers).json()["audit"]
        # /authz is mounted without a role in code, so both trails have a route
        assert audit == {"enabled": True, "changes_readable": True, "decisions_readable": True}
        assert client.get("/authz/audit", headers=headers).status_code == 200
        assert client.get("/authz/decisions", headers=headers).status_code == 200

    @patch("agno.os.app.setup_tracing_for_os")
    def test_tracing_is_on_only_while_the_agno_tracer_is_active(self, _setup, db):
        agent_os = _os(db, tracing=True)
        with patch("agno.os.router._agno_tracing_is_active", return_value=True):
            assert _config(agent_os).json()["traces"]["enabled"] is True
        # tracing=True whose tracer never became the active one stores no spans.
        with patch("agno.os.router._agno_tracing_is_active", return_value=False):
            assert _config(agent_os).json()["traces"]["enabled"] is False

    def test_scheduler(self, db):
        assert _config(_os(db, scheduler=True)).json()["scheduler"] == {"enabled": True}

    def test_scheduler_without_a_database_does_not_run(self):
        agent_os = AgentOS(id=OS_ID, agents=[Agent(id="cfg-agent", telemetry=False)], scheduler=True, telemetry=False)
        assert _config(agent_os).json()["scheduler"] == {"enabled": False}

    def test_mcp_matches_info(self, db):
        app = _os(db, mcp=True).get_app()
        with TestClient(app) as client:
            assert client.get("/config").json()["mcp"] == {"enabled": True}
            assert client.get("/info").json()["mcp"]["enabled"] is True

    def _public_os(self, **kwargs):
        # A public surface needs a PostgreSQL db; no connection is made for these requests.
        pg = PostgresDb(db_engine=create_engine("postgresql+psycopg://unused:unused@127.0.0.1:1/unused"))
        agent = Agent(id="cfg-agent", name="Cfg Agent", telemetry=False)
        public = PublicSurface(agents=[agent])
        return AgentOS(
            id=OS_ID, agents=[agent], db=pg, public=public, auto_provision_dbs=False, telemetry=False, **kwargs
        )

    def test_public_surface_is_reported_to_administrators_only(self):
        config = AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256")
        agent_os = self._public_os(authorization=True, authorization_config=config)
        assert "public" not in _config(agent_os, _bearer("bob", MEMBER_SCOPES)).json()
        public = _config(agent_os, _bearer("alice", ["agent_os:admin"])).json()["public"]
        assert public == {"enabled": True, "agents": ["cfg-agent"], "teams": [], "workflows": [], "mcp": False}

    def test_report_is_served_while_the_role_store_cannot_be_read(self):
        config = AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256")
        agent_os = self._public_os(authorization=True, authorization_config=config)
        # No admin role can be confirmed for a caller whose token does not carry the admin scope
        member = _config(agent_os, _bearer("bob", MEMBER_SCOPES)).json()
        assert member["authorization"] == {"enabled": True, "mode": "jwt", "user_isolation": False}
        block = _config(agent_os, _bearer("alice", ["agent_os:admin"])).json()["authorization"]
        assert block["managed_roles"] is True
        assert "default_role" not in block

    def test_manager(self, db):
        body = _config(_os(db, manager=OSManager(model=OpenAIResponses(id="offline", api_key="test")))).json()
        assert body["manager"] == {"enabled": True}
        assert any(team.get("metadata", {}).get("_agno", {}).get("internal") for team in body["teams"])

    def test_media_storage_set_on_the_os(self, db, tmp_path):
        agent_os = _os(db, media_storage=LocalMediaStorage(base_path=str(tmp_path / "media")))
        assert _config(agent_os).json()["media_storage"] == {"enabled": True, "backend": "local"}

    def test_media_storage_found_on_an_agent(self, db, tmp_path):
        storage = LocalMediaStorage(base_path=str(tmp_path / "media"))
        agent = Agent(id="media-agent", db=db, media_storage=storage, telemetry=False)
        agent_os = AgentOS(id=OS_ID, agents=[agent], db=db, telemetry=False)
        assert _config(agent_os).json()["media_storage"] == {"enabled": True, "backend": "local"}

    def test_telemetry_from_the_os_launch_ping(self, db):
        agent_os = AgentOS(id=OS_ID, agents=[Agent(id="cfg-agent", db=db, telemetry=False)], db=db)
        assert _config(agent_os).json()["telemetry"] == {"enabled": True}

    def test_telemetry_from_an_agent_when_the_os_ping_is_off(self, db):
        agent_os = AgentOS(id=OS_ID, agents=[Agent(id="cfg-agent", db=db)], db=db, telemetry=False)
        assert _config(agent_os).json()["telemetry"] == {"enabled": True}

    def test_telemetry_env_overrides_each_component(self, db, monkeypatch):
        agent_os = AgentOS(id=OS_ID, agents=[Agent(id="cfg-agent", db=db)], db=db, telemetry=False)
        monkeypatch.setenv("AGNO_TELEMETRY", "false")
        assert _config(agent_os).json()["telemetry"] == {"enabled": False}
        monkeypatch.setenv("AGNO_TELEMETRY", "true")
        assert _config(_os(db)).json()["telemetry"] == {"enabled": True}

    def test_telemetry_from_a_team_member_when_the_team_is_off(self, db):
        member = Agent(id="member-agent", db=db)
        inner = Team(id="inner-team", members=[member], telemetry=False)
        team = Team(id="cfg-team", members=[inner], db=db, telemetry=False)
        agent_os = AgentOS(id=OS_ID, teams=[team], db=db, telemetry=False)
        assert _config(agent_os).json()["telemetry"] == {"enabled": True}

    def test_telemetry_from_an_agent_inside_a_workflow_step(self, db):
        nested = Agent(id="step-agent", db=db)
        quiet = Agent(id="quiet-agent", db=db, telemetry=False)
        workflow = Workflow(
            id="cfg-workflow",
            db=db,
            telemetry=False,
            steps=[Step(name="first", agent=quiet), Parallel(Step(name="second", agent=nested), name="fan-out")],
        )
        agent_os = AgentOS(id=OS_ID, workflows=[workflow], db=db, telemetry=False)
        assert _config(agent_os).json()["telemetry"] == {"enabled": True}

    def test_telemetry_off_when_every_nested_component_is_off(self, db):
        member = Agent(id="member-agent", db=db, telemetry=False)
        team = Team(id="cfg-team", members=[member], db=db, telemetry=False)
        workflow = Workflow(
            id="cfg-workflow",
            db=db,
            telemetry=False,
            steps=[Step(name="first", team=team), Step(name="second", executor=lambda step_input: None)],
        )
        agent_os = AgentOS(id=OS_ID, teams=[team], workflows=[workflow], db=db, telemetry=False)
        assert _config(agent_os).json()["telemetry"] == {"enabled": False}

    def test_member_sees_manager_media_storage_and_telemetry(self, db, tmp_path):
        storage = LocalMediaStorage(base_path=str(tmp_path / "media"))
        agent_os = _os(
            db,
            authorization=_roles(),
            manager=OSManager(model=OpenAIResponses(id="offline", api_key="test")),
            media_storage=storage,
        )
        features = _config(agent_os, _bearer("bob")).json()
        assert features["manager"] == {"enabled": True}
        assert features["media_storage"] == {"enabled": True, "backend": "local"}
        # The manager team keeps its own default run telemetry.
        assert features["telemetry"] == {"enabled": True}

    def test_durable_queue(self, db):
        body = _config(_os(db, queue=QueueConfig(durable=True, db=InMemoryQueueStore()))).json()
        assert body["queue"] == {"durable": True, "queue_per_session": True, "cross_container": False}

    def test_cross_container_needs_both_transports_shared(self, db):
        shared_stream, shared_cancellation = object(), object()
        with (
            patch("agno.os.event_streams.get_event_stream", return_value=shared_stream),
            patch("agno.run.cancel.get_cancellation_manager", return_value=shared_cancellation),
        ):
            assert _config(_os(db)).json()["queue"]["cross_container"] is True
        # A shared event stream beside the in-process cancellation default cannot cancel from another replica.
        with patch("agno.os.event_streams.get_event_stream", return_value=shared_stream):
            assert _config(_os(db)).json()["queue"]["cross_container"] is False

    def test_filesystem_and_knowledge_off(self, db):
        body = _config(_os(db)).json()
        assert body["filesystem"]["enabled"] is False
        assert body["knowledge"]["enabled"] is False

    def test_filesystem_on(self, db):
        agent = Agent(id="fs-agent", db=db, filesystem=True, telemetry=False)
        body = _config(AgentOS(id=OS_ID, agents=[agent], db=db, telemetry=False)).json()
        assert body["filesystem"]["enabled"] is True
        assert [entry["namespace"] for entry in body["filesystem"]["namespaces"]] == ["fs-agent"]

    def test_knowledge_on(self, db):
        knowledge = Knowledge(name="handbook", contents_db=db)
        agent = Agent(id="kb-agent", db=db, knowledge=knowledge, telemetry=False)
        body = _config(AgentOS(id=OS_ID, agents=[agent], db=db, telemetry=False)).json()
        assert body["knowledge"]["enabled"] is True
        assert [entry["name"] for entry in body["knowledge"]["knowledge_instances"]] == ["handbook"]


class TestResponseContract:
    def test_response_varies_by_caller(self, db):
        assert "Authorization" in _config(_os(db)).headers["Vary"]
        resp = _config(_os(db, authorization=_roles()), _bearer("bob"))
        assert "Authorization" in resp.headers["Vary"]

    def test_nothing_secret_is_reported(self, db, tmp_path):
        jwks = tmp_path / "jwks.json"
        jwks.write_text('{"keys": []}')
        authorization = _roles(
            audit=True,
            trust_token_scopes=True,
            verify_audience=True,
            audience="secret-audience-value",
            issuer="https://issuer.secret.example",
            jwks_file=str(jwks),
        )
        agent_os = _os(
            db,
            authorization=authorization,
            user_directory=True,
            cors_allowed_origins=["https://origin.secret.example"],
        )
        claims = {
            "sub": "alice",
            "aud": "secret-audience-value",
            "iss": "https://issuer.secret.example",
            "exp": int(time.time()) + 300,
        }
        headers = {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}
        resp = _config(agent_os, headers)
        body = resp.json()
        assert body["authorization"]["audience_verified"] is True
        blocks = repr(body["authorization"]) + repr(_features(body))
        for secret in (
            SECRET,
            "HS256",
            "jwks",
            str(tmp_path),
            "secret-audience-value",
            "issuer.secret.example",
            "origin.secret.example",
            "sqlite",
            "agent_os:admin",
            "config:read",
            "alice",
        ):
            assert secret not in blocks, secret
        for secret in (SECRET, str(jwks), "secret-audience-value", "issuer.secret.example", "origin.secret.example"):
            assert secret not in resp.text, secret
        # The whole report is these keys and nothing else.
        assert set(body["authorization"]) == {"enabled", "mode", "user_isolation"} | ADMIN_ONLY_FIELDS
        assert set(_features(body)) == set(FEATURES_OFF)

    def test_client_schema_parses_new_and_older_servers(self, db):
        body = _config(_os(db, authorization=_roles()), _bearer("alice")).json()
        parsed = ConfigResponse.model_validate(body)
        assert parsed.authorization is not None and parsed.authorization.default_role == "member"
        assert parsed.audit is not None and parsed.scheduler is not None

        member = ConfigResponse.model_validate(
            _config(_os(db, authorization=_roles()), _bearer("bob")).json()
        ).authorization
        assert member is not None and member.enabled is True and member.managed_roles is None

        older = {k: v for k, v in body.items() if k != "authorization" and k not in FEATURES_OFF}
        older["queue"] = {"durable": False, "queue_per_session": False}
        for block in ("filesystem", "knowledge", "traces"):
            older[block].pop("enabled", None)
        parsed_older = ConfigResponse.model_validate(older)
        assert parsed_older.authorization is None and parsed_older.audit is None
        assert parsed_older.queue is not None and parsed_older.queue.cross_container is False
        assert parsed_older.traces is not None and parsed_older.traces.enabled is None

        # A later server may add fields beside the ones known today.
        body["audit"]["changes_recorded"] = True
        body["new_feature"] = {"enabled": True}
        body["authorization"]["new_setting"] = "x"
        assert ConfigResponse.model_validate(body).audit.changes_readable is False


class TestDatabaseReads:
    """/config is loaded on every connect, so the report's database cost is pinned."""

    def _statements(self, db, agent_os, headers, with_report):
        app = agent_os.get_app()
        client = TestClient(app)
        client.get("/config", headers=headers)  # table creation and other first-request work
        seen = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            seen.append(statement)

        event.listen(db.db_engine, "before_cursor_execute", _record)
        try:
            if with_report:
                resp = client.get("/config", headers=headers)
            else:

                async def _no_authorization(os, request, is_admin):
                    return None

                async def _no_admin_check(os, request):
                    return False

                with (
                    patch("agno.os.router._caller_is_admin", _no_admin_check),
                    patch("agno.os.router._authorization_report", _no_authorization),
                    patch("agno.os.router._feature_blocks", lambda os, request, is_admin: {}),
                ):
                    resp = client.get("/config", headers=headers)
        finally:
            event.remove(db.db_engine, "before_cursor_execute", _record)
        assert resp.status_code == 200, resp.text
        return [s for s in seen if s.lstrip().upper().startswith("SELECT")]

    def _added(self, db, agent_os, headers):
        without = self._statements(db, agent_os, headers, with_report=False)
        with_report = self._statements(db, agent_os, headers, with_report=True)
        return len(with_report) - len(without)

    def test_no_reads_without_managed_roles(self, db):
        assert self._added(db, _os(db, user_directory=True), None) == 0

    def test_non_admin_adds_no_reads(self, db):
        agent_os = _os(db, authorization=_roles(audit=True), user_directory=True)
        assert self._added(db, agent_os, _bearer("bob")) == 0

    def test_admin_adds_one_read_for_the_default_role(self, db):
        agent_os = _os(db, authorization=_roles(audit=True), user_directory=True)
        assert self._added(db, agent_os, _bearer("alice")) == 1
