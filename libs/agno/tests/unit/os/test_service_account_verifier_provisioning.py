"""Provisioning of the service-account verifier is decoupled from db presence.

Previously the verifier was created whenever an AgentOS had a db, which meant a
stale ``agno_pat_...`` in a browser could 401 an otherwise-open instance because
"I have a db" was silently being read as "I want PAT auth". The verifier is now
only provisioned when the operator actually configured a base auth mechanism
(JWT or security key).
"""

import pytest

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
    def test_db_alone_does_not_install_verifier(self, sqlite_db):
        """Regression: db + no auth = no verifier on app.state, no auth middleware.

        Before this fix, AgentOS(agents=[...], db=db) would silently attach a
        service-account verifier to app.state and install the AuthMiddleware to
        run it -- meaning a stale ``agno_pat_...`` in a client would 401 even
        though the operator never configured auth.
        """
        os_instance = AgentOS(agents=[_agent()], db=sqlite_db, telemetry=False)
        app = os_instance.get_app()
        assert getattr(app.state, "service_account_verifier", None) is None

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
        """The AuthMiddleware itself must not install when only a db is present.

        Ayush's symptom: stale ``agno_pat_...`` in browser -> 401 -> confused user.
        Root cause: AuthMiddleware installed to run the verifier. Fix: don't install
        the middleware at all when the operator did not opt into auth.
        """
        from agno.os.middleware.jwt import AuthMiddleware

        os_instance = AgentOS(agents=[_agent()], db=sqlite_db, telemetry=False)
        app = os_instance.get_app()

        auth_middleware_present = any(
            isinstance(getattr(mw, "cls", None), type) and issubclass(mw.cls, AuthMiddleware)
            for mw in app.user_middleware
        )
        assert not auth_middleware_present
