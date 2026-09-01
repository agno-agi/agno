"""Service-account verifier capability vs auth-enforcement policy.

The verifier (the *capability* to check ``agno_pat_`` tokens) lives on app.state
whenever the AgentOS has a db: the WS authenticate action, the REST dependency,
and manually added JWTMiddleware all resolve it at request time. Enforcement is
a separate decision: the auth middleware only installs when the operator
configured a base auth mechanism (JWT or security key), and on an open instance
an unverifiable PAT falls through to anonymous access. A stale ``agno_pat_...``
in a browser must never 401 an instance the operator meant to be open.
"""

import pytest
from starlette.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.settings import AgnoAPISettings

JWT_SECRET = "test-jwt-secret"


@pytest.fixture(autouse=True)
def clean_auth_env(monkeypatch):
    monkeypatch.delenv("OS_SECURITY_KEY", raising=False)
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    monkeypatch.delenv("JWT_JWKS_FILE", raising=False)


@pytest.fixture
def sqlite_db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "provisioning.db"))


def _agent():
    return Agent(id="a", name="a", telemetry=False)


class TestSAVerifierProvisioning:
    def test_db_alone_exposes_verifier_without_enforcement(self, sqlite_db):
        """A db is enough to *have* the verifier -- request-time consumers (the WS
        authenticate action, manually added JWTMiddleware) need it even when
        AgentOS itself installs no auth. Enforcement stays off: see
        TestOpenInstanceStaysOpen for the no-middleware / stale-PAT-ignored pins.
        """
        os_instance = AgentOS(agents=[_agent()], db=sqlite_db, telemetry=False)
        app = os_instance.get_app()
        assert getattr(app.state, "service_account_verifier", None) is not None

    def test_authorization_true_installs_verifier(self, sqlite_db):
        os_instance = AgentOS(
            agents=[_agent()],
            db=sqlite_db,
            telemetry=False,
            authorization=True,
            authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
        )
        app = os_instance.get_app()
        assert getattr(app.state, "service_account_verifier", None) is not None

    def test_security_key_installs_verifier(self, sqlite_db):
        os_instance = AgentOS(
            agents=[_agent()],
            db=sqlite_db,
            telemetry=False,
            settings=AgnoAPISettings(os_security_key="root-key"),
        )
        app = os_instance.get_app()
        assert getattr(app.state, "service_account_verifier", None) is not None

    def test_jwt_env_var_installs_verifier(self, sqlite_db, monkeypatch):
        """Env-var-configured JWT (manual middleware path) auto-enables the verifier."""
        monkeypatch.setenv("JWT_VERIFICATION_KEY", JWT_SECRET)
        os_instance = AgentOS(agents=[_agent()], db=sqlite_db, telemetry=False)
        app = os_instance.get_app()
        assert getattr(app.state, "service_account_verifier", None) is not None


class TestOpenInstanceStaysOpen:
    def test_no_auth_middleware_on_db_only_instance(self, sqlite_db):
        """The AuthMiddleware must not install when only a db is present: having
        the means to verify tokens is not the same as requiring them. An instance
        with no security key and no JWT stays open, db or not.
        """
        from agno.os.middleware.jwt import AuthMiddleware

        os_instance = AgentOS(agents=[_agent()], db=sqlite_db, telemetry=False)
        app = os_instance.get_app()

        auth_middleware_present = any(
            isinstance(getattr(mw, "cls", None), type) and issubclass(mw.cls, AuthMiddleware)
            for mw in app.user_middleware
        )
        assert not auth_middleware_present

    def test_stale_pat_ignored_on_open_rest_route(self, sqlite_db):
        """End-to-end pin of the open-instance rule: a stale ``agno_pat_`` bearer
        on a db-only (open) instance is ignored and the request proceeds
        anonymously, exactly as if no token had been sent.
        """
        os_instance = AgentOS(agents=[_agent()], db=sqlite_db, telemetry=False)
        client = TestClient(os_instance.get_app())

        no_token = client.get("/agents")
        stale_pat = client.get("/agents", headers={"Authorization": "Bearer agno_pat_stale00000000000000000000"})
        assert no_token.status_code == 200
        assert stale_pat.status_code == 200
