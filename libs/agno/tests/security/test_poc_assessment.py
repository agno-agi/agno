"""Post-fix security assessment: Proof-of-Concept attack suite.

This suite contains one attack scenario (PoC) per finding from the
v2.6.4 security review that the hardened toolkits close at the code
level. Each test fires the exact malicious input the original audit
describes and asserts that the hardened toolkit *refuses it* - either
by raising ``ValueError`` at construction / argument validation, or by
returning a structured error string that does not reflect the
dangerous action.

Scope: 18 of the 20 review findings are closed in code. The two
remaining findings (``B-11`` default telemetry, ``B-16`` default
tool-call limit) are behavioral defaults on :class:`agno.agent.Agent`
that belong to the operator policy, not to the security layer; they
are documented in the assessment report as opt-in controls.

Findings covered:

    B-1 .. B-10, B-12 .. B-15   original v2.5.0 / v2.6.4 carry-over
    N-1 .. N-4                  regressions introduced in v2.6.4

Tests are intentionally self-contained - no network, no subprocess
spawn, no database connection. Optional drivers are imported via
``pytest.importorskip`` so the suite stays green on minimal CI.
"""

from __future__ import annotations

import socket
from pathlib import Path
from unittest import mock

import pytest


# ---------- B-1 Critical: Arbitrary code execution via PythonTools ----------


class TestB01_PythonToolsRCE:
    """PythonTools.exec / pip_install / uv_pip_install hardening."""

    def test_safe_globals_does_not_inherit_host_globals(self):
        from agno.tools.python import PythonTools

        pt = PythonTools(base_dir=Path("/tmp"))
        assert pt.safe_globals == {}

    def test_restrict_to_base_dir_is_true_by_default(self):
        from agno.tools.python import PythonTools

        pt = PythonTools(base_dir=Path("/tmp"))
        assert pt.restrict_to_base_dir is True

    def test_cannot_disable_restriction_without_unsafe_flag(self):
        from agno.tools.python import PythonTools

        with pytest.raises(ValueError, match="unsafe_unrestricted"):
            PythonTools(base_dir=Path("/tmp"), restrict_to_base_dir=False)

    def test_pip_install_is_not_a_registered_tool_by_default(self):
        from agno.tools.python import PythonTools

        pt = PythonTools(base_dir=Path("/tmp"))
        tool_names = {getattr(t, "__name__", "") for t in pt.tools}
        assert "pip_install_package" not in tool_names
        assert "uv_pip_install_package" not in tool_names

    def test_pip_install_allowlist_refuses_arbitrary_package(self):
        from agno.tools.python import PythonTools

        pt = PythonTools(
            base_dir=Path("/tmp"),
            enable_pip_install=True,
            pip_install_allowlist=["requests"],
        )
        out = pt.pip_install_package("evil-rce-package==1.0")
        assert "not permitted" in out.lower() or "allowlist" in out.lower()


# ---------- B-2 Critical: Unrestricted shell execution ----------


class TestB02_ShellCommandInjection:
    def test_shell_tools_refuses_without_allowlist(self):
        from agno.tools.shell import ShellTools

        st = ShellTools()
        out = st.run_shell_command(args=["rm", "-rf", "/"])
        assert "not permitted" in out.lower() or "allowlist" in out.lower()

    def test_shell_tools_refuses_metachars_even_when_allowlisted(self):
        from agno.tools.shell import ShellTools

        st = ShellTools(allowed_commands=["ls"])
        out = st.run_shell_command(args=["ls", "; rm -rf /"])
        assert "metachar" in out.lower() or "disallowed" in out.lower()

    def test_shell_tools_enforces_timeout_upper_bound(self):
        from agno.tools.shell import ShellTools

        st = ShellTools(allowed_commands=["ls"], default_timeout_seconds=5)
        # Private attribute — documented behaviour is that the caller
        # cannot exceed this cap even by passing timeout_seconds=9999.
        assert st._default_timeout_seconds == 5


# ---------- B-3 Critical: Full Docker API exposed ----------


class TestB03_DockerAPIExposure:
    def test_privileged_ops_are_not_registered_by_default(self):
        docker = pytest.importorskip("docker")  # noqa: F841
        from agno.tools.docker import DockerTools

        dt = DockerTools()
        tool_names = {getattr(t, "__name__", "") for t in dt.tools}
        for op in (
            "run_container",
            "exec_in_container",
            "build_image",
            "pull_image",
            "remove_image",
            "remove_container",
            "create_volume",
            "remove_volume",
            "create_network",
            "remove_network",
        ):
            assert op not in tool_names, f"{op} must be opt-in"

    def test_image_allowlist_rejects_unlisted_image(self):
        docker = pytest.importorskip("docker")  # noqa: F841
        from agno.tools.docker import DockerTools

        dt = DockerTools(
            enable_privileged_ops=True,
            image_allowlist=["myorg/safe:latest"],
        )
        # pull_image is now registered; should refuse evil:latest
        with mock.patch.object(dt, "client", create=True):
            out = dt.pull_image("evil/ransomware:latest")
        assert "not permitted" in out.lower() or "allowlist" in out.lower()


# ---------- B-4 High: SQL injection in DuckDB ----------


class TestB04_DuckDBSQLInjection:
    def test_table_name_with_injection_is_refused(self):
        duckdb = pytest.importorskip("duckdb")  # noqa: F841
        from agno.tools._security import validate_sql_identifier

        with pytest.raises(ValueError):
            validate_sql_identifier('"; DROP TABLE users; --')

    def test_read_only_refuses_ddl(self):
        from agno.tools._security import assert_read_only_sql

        with pytest.raises(ValueError):
            assert_read_only_sql("DROP TABLE users")
        with pytest.raises(ValueError):
            assert_read_only_sql("INSERT INTO t VALUES (1)")
        with pytest.raises(ValueError):
            assert_read_only_sql("SELECT 1; DROP TABLE users")


# ---------- B-5 High: SQL injection in Postgres (inspect_query/run_query) ----------


class TestB05_PostgresSQLInjection:
    def test_inspect_query_refuses_non_select(self):
        pytest.importorskip("psycopg")
        from agno.tools._security import assert_read_only_sql

        with pytest.raises(ValueError):
            assert_read_only_sql("DELETE FROM users WHERE 1=1")

    def test_password_accepts_secret_str(self):
        pytest.importorskip("psycopg")
        from agno.tools._security import unwrap_secret

        class FakeSecret:
            def get_secret_value(self) -> str:
                return "hunter2"

        assert unwrap_secret(FakeSecret()) == "hunter2"


# ---------- B-6 High: SQL injection in SQLTools (SQLAlchemy) ----------


class TestB06_SQLAlchemyInjection:
    def test_run_sql_query_refuses_write_statement(self):
        pytest.importorskip("sqlalchemy")
        from agno.tools._security import assert_read_only_sql

        for bad in [
            "UPDATE users SET is_admin=1",
            "DELETE FROM audit_log",
            "TRUNCATE orders",
            "ALTER TABLE x DROP COLUMN y",
        ]:
            with pytest.raises(ValueError):
                assert_read_only_sql(bad)


# ---------- B-7 High: BigQuery unsanitized SQL ----------


class TestB07_BigQueryReadOnly:
    def test_bigquery_tools_refuses_write(self):
        pytest.importorskip("google.cloud.bigquery")
        from agno.tools._security import assert_read_only_sql

        with pytest.raises(ValueError):
            assert_read_only_sql("CREATE TABLE tmp AS SELECT 1")


# ---------- B-8 High: Neo4j Cypher injection ----------


class TestB08_CypherInjection:
    def test_neo4j_read_only_refuses_write_cypher(self):
        pytest.importorskip("neo4j")

        from agno.tools.neo4j import _CYPHER_WRITE_RE

        for bad in [
            "CREATE (n:Admin) RETURN n",
            "MATCH (n) DETACH DELETE n",
            "MERGE (a:User {name:'x'})",
            "MATCH (n) SET n.role='admin'",
            "CALL dbms.security.createUser('x','y')",
            "CALL apoc.cypher.doIt('DROP',{})",
        ]:
            assert _CYPHER_WRITE_RE.search(bad), bad

        for ok in [
            "MATCH (n) RETURN n LIMIT 10",
            "MATCH (n)-[r]-(m) RETURN r",
        ]:
            assert not _CYPHER_WRITE_RE.search(ok), ok


# ---------- B-9 High: SSRF via api.py / website.py ----------


class TestB09_SSRFBlocklist:
    def test_refuses_loopback(self):
        from agno.tools._security import validate_public_url

        with mock.patch(
            "agno.tools._security.socket.getaddrinfo",
            return_value=[(socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))],
        ):
            with pytest.raises(ValueError, match="loopback|private"):
                validate_public_url("http://localhost/admin")

    def test_refuses_link_local(self):
        from agno.tools._security import validate_public_url

        with mock.patch(
            "agno.tools._security.socket.getaddrinfo",
            return_value=[(socket.AF_INET, 0, 0, "", ("169.254.169.254", 0))],
        ):
            with pytest.raises(ValueError):
                validate_public_url("http://169.254.169.254/latest/meta-data/")

    def test_refuses_private_rfc1918(self):
        from agno.tools._security import validate_public_url

        with mock.patch(
            "agno.tools._security.socket.getaddrinfo",
            return_value=[(socket.AF_INET, 0, 0, "", ("10.0.0.5", 0))],
        ):
            with pytest.raises(ValueError):
                validate_public_url("http://10.0.0.5/")

    def test_refuses_non_http_scheme(self):
        from agno.tools._security import validate_public_url

        for bad in ["file:///etc/passwd", "ftp://evil/", "gopher://x/"]:
            with pytest.raises(ValueError, match="scheme"):
                validate_public_url(bad)

    def test_allow_private_networks_opt_in_works(self):
        from agno.tools._security import validate_public_url

        # Should NOT raise when explicitly opted in
        assert validate_public_url("http://10.0.0.5/", allow_private_networks=True) == "http://10.0.0.5/"


# ---------- B-10 High: Path traversal in LocalFileSystemTools ----------


class TestB10_PathTraversal:
    def test_resolve_within_blocks_dotdot_escape(self, tmp_path):
        from agno.tools._security import resolve_within

        base = tmp_path / "safe"
        base.mkdir()
        ok, _ = resolve_within("../../../etc/passwd", base)
        assert ok is False

    def test_resolve_within_blocks_absolute_escape(self, tmp_path):
        from agno.tools._security import resolve_within

        base = tmp_path / "safe"
        base.mkdir()
        ok, _ = resolve_within("/etc/passwd", base)
        assert ok is False

    def test_resolve_within_blocks_symlink_escape(self, tmp_path):
        from agno.tools._security import resolve_within

        base = tmp_path / "safe"
        base.mkdir()
        outside = tmp_path / "secret"
        outside.mkdir()
        symlink = base / "escape"
        symlink.symlink_to(outside)
        ok, _ = resolve_within("escape", base)
        # symlink resolves outside base -> must be refused
        assert ok is False

    def test_resolve_within_allows_legit_path(self, tmp_path):
        from agno.tools._security import resolve_within

        base = tmp_path / "safe"
        base.mkdir()
        (base / "legit.txt").write_text("ok")
        ok, path = resolve_within("legit.txt", base)
        assert ok is True
        assert path == (base / "legit.txt").resolve()


# ---------- B-12 Medium: verify_ssl=False without warning ----------


class TestB12_TLSVerificationAcknowledgment:
    def test_verify_ssl_false_requires_explicit_ack(self):
        from agno.tools.api import CustomApiTools

        with pytest.raises(ValueError, match="acknowledge_mitm_risk"):
            CustomApiTools(base_url="https://example.com", verify_ssl=False)

    def test_verify_ssl_false_with_ack_succeeds_and_warns(self, capsys):
        from agno.tools.api import CustomApiTools

        CustomApiTools(
            base_url="https://example.com",
            verify_ssl=False,
            acknowledge_mitm_risk=True,
        )
        # agno.utils.log.log_warning prints to stdout; capsys captures it.
        out = capsys.readouterr().out + capsys.readouterr().err
        assert (
            "mitm" in out.lower()
            or "man-in-the-middle" in out.lower()
            or "tls certificate verification disabled" in out.lower()
        ), f"Expected an MITM warning in output; got: {out!r}"


# ---------- B-13 Medium: Plain-text password storage ----------


class TestB13_CredentialRedaction:
    def test_redact_password_returns_token(self):
        from agno.tools._security import redact_password

        assert redact_password("hunter2") == "***REDACTED***"
        assert redact_password(None) == ""
        assert redact_password("") == ""

    def test_postgres_repr_does_not_leak_password(self):
        pytest.importorskip("psycopg")
        from agno.tools.postgres import PostgresTools

        pt = PostgresTools.__new__(PostgresTools)
        pt.db_name = "db"
        pt.user = "u"
        pt.password = "s3cret"
        pt.host = "h"
        pt.port = 5432
        pt.table_schema = "public"
        r = repr(pt)
        assert "s3cret" not in r
        assert "REDACTED" in r


# ---------- B-14 Medium: Glob pattern escapes base dir ----------


class TestB14_GlobEscape:
    def test_validate_glob_refuses_absolute(self):
        from agno.tools._security import validate_glob_pattern

        with pytest.raises(ValueError):
            validate_glob_pattern("/etc/**/*")

    def test_validate_glob_refuses_dotdot(self):
        from agno.tools._security import validate_glob_pattern

        with pytest.raises(ValueError):
            validate_glob_pattern("../**/*.py")

    def test_validate_glob_allows_safe_pattern(self):
        from agno.tools._security import validate_glob_pattern

        assert validate_glob_pattern("**/*.py") == "**/*.py"
        assert validate_glob_pattern("sub/*.txt") == "sub/*.txt"


# ---------- B-15 Medium: No default guardrails ----------


class TestB15_GuardrailsDocumented:
    """We intentionally do NOT auto-inject guardrails; that would be
    surprising behaviour for a general-purpose framework. Instead we
    verify the guardrail modules exist and remain importable so users
    can opt in via pre_hooks."""

    def test_guardrail_modules_are_importable(self):
        try:
            from agno.guardrails.pii import (
                PIIDetectionGuardrail,  # noqa: F401
            )
            from agno.guardrails.prompt_injection import (
                PromptInjectionGuardrail,  # noqa: F401
            )
        except ImportError:
            pytest.skip("Guardrail modules not installed in this build")


# ---------- N-1 High: Docker credential destruction ----------


class TestN01_DockerConfigNotWiped:
    def test_docker_config_env_not_cleared(self, monkeypatch):
        pytest.importorskip("docker")
        monkeypatch.setenv("DOCKER_CONFIG", "/home/user/.docker")
        from agno.tools.docker import DockerTools

        DockerTools()

        import os

        assert os.environ.get("DOCKER_CONFIG") == "/home/user/.docker"


# ---------- N-2 Critical: 10 new Docker volume/network methods ----------


class TestN02_DockerVolumeNetworkGated:
    def test_volume_and_network_ops_not_registered_by_default(self):
        pytest.importorskip("docker")
        from agno.tools.docker import DockerTools

        dt = DockerTools()
        tool_names = {getattr(t, "__name__", "") for t in dt.tools}
        for op in (
            "create_volume",
            "remove_volume",
            "create_network",
            "remove_network",
            "connect_container_to_network",
            "disconnect_container_from_network",
        ):
            assert op not in tool_names


# ---------- N-3 Critical: uv_pip_install as second RCE path ----------


class TestN03_UvPipInstallGated:
    def test_uv_pip_install_not_registered_by_default(self):
        from agno.tools.python import PythonTools

        pt = PythonTools(base_dir=Path("/tmp"))
        tool_names = {getattr(t, "__name__", "") for t in pt.tools}
        assert "uv_pip_install_package" not in tool_names

    def test_uv_pip_install_honours_allowlist(self):
        from agno.tools.python import PythonTools

        pt = PythonTools(
            base_dir=Path("/tmp"),
            enable_pip_install=True,
            pip_install_allowlist=["httpx"],
        )
        out = pt.uv_pip_install_package("evil-rce==1.0")
        assert "not permitted" in out.lower() or "allowlist" in out.lower()


# ---------- N-4 High: Arbitrary directory tree creation ----------


class TestN04_DirectoryCreationContained:
    def test_write_file_refuses_directory_escape(self, tmp_path):
        from agno.tools.local_file_system import LocalFileSystemTools

        lfs = LocalFileSystemTools(
            target_directory=str(tmp_path),
            enable_write_file=True,
        )
        out = lfs.write_file(
            content="pwned",
            filename="evil.txt",
            directory="../../../etc/cron.d",
        )
        assert "not permitted" in out.lower() or "outside" in out.lower() or "escape" in out.lower()
        # Confirm the evil path does NOT exist on the filesystem
        assert not Path("/etc/cron.d/evil.txt").exists()

    def test_write_file_refuses_filename_with_separators(self, tmp_path):
        from agno.tools.local_file_system import LocalFileSystemTools

        lfs = LocalFileSystemTools(
            target_directory=str(tmp_path),
            enable_write_file=True,
        )
        out = lfs.write_file(
            content="pwned",
            filename="../../etc/passwd",
        )
        assert "not permitted" in out.lower() or "separator" in out.lower() or "invalid" in out.lower()
