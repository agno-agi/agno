"""Security regression tests for the hardened agno tools.

Each test group mirrors one of the hardening changes shipped in this
build and guards against accidental regressions. Tests run entirely
in-process and avoid real network or database calls. Optional
drivers (``duckdb``, ``neo4j``) are imported lazily via
``pytest.importorskip`` so the suite stays green on minimal CI
images that don't install those extras.
"""

from __future__ import annotations

import socket
from pathlib import Path
from unittest import mock

import pytest

from agno.tools._security import (
    assert_read_only_sql,
    redact_password,
    resolve_within,
    sanitize_shell_arg,
    unwrap_secret,
    validate_glob_pattern,
    validate_public_url,
    validate_sql_identifier,
)


# ---------- _security helpers (used by many toolkits) ---------------


class TestSQLValidators:
    def test_identifier_ok(self):
        assert validate_sql_identifier("my_table") == "my_table"

    @pytest.mark.parametrize(
        "bad",
        ["1abc", "a-b", "'; DROP TABLE users;--", "", "a" * 100],
    )
    def test_identifier_rejects(self, bad):
        with pytest.raises(ValueError):
            validate_sql_identifier(bad)

    def test_identifier_rejects_none(self):
        with pytest.raises(ValueError):
            validate_sql_identifier(None)  # type: ignore[arg-type]

    def test_select_accepted(self):
        assert assert_read_only_sql("SELECT 1").startswith("SELECT")
        assert assert_read_only_sql("WITH x AS (SELECT 1) SELECT * FROM x").startswith("WITH")

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET x = 1",
            "DELETE FROM t",
            "DROP TABLE t",
            "SELECT 1; DELETE FROM t",
            "CREATE TABLE t (x INT)",
            "ATTACH 'foo'",
        ],
    )
    def test_non_select_rejected(self, bad):
        with pytest.raises(ValueError):
            assert_read_only_sql(bad)


class TestShellSanitizer:
    def test_safe_arg(self):
        assert sanitize_shell_arg("/tmp/file.txt") == "/tmp/file.txt"

    @pytest.mark.parametrize(
        "bad",
        ["foo;bar", "a|b", "`id`", "$(whoami)", "a && b", "a\nb"],
    )
    def test_metachar_rejected(self, bad):
        with pytest.raises(ValueError):
            sanitize_shell_arg(bad)


class TestSSRFValidator:
    def test_scheme_allowlist(self):
        with pytest.raises(ValueError):
            validate_public_url("file:///etc/passwd")
        with pytest.raises(ValueError):
            validate_public_url("gopher://example.com/")

    def test_blocks_private(self):
        with mock.patch.object(
            socket,
            "getaddrinfo",
            return_value=[(None, None, None, "", ("127.0.0.1", 0))],
        ):
            with pytest.raises(ValueError):
                validate_public_url("http://localhost/")
        with mock.patch.object(
            socket,
            "getaddrinfo",
            return_value=[(None, None, None, "", ("10.1.2.3", 0))],
        ):
            with pytest.raises(ValueError):
                validate_public_url("http://internal/")

    def test_allows_public(self):
        with mock.patch.object(
            socket,
            "getaddrinfo",
            return_value=[(None, None, None, "", ("8.8.8.8", 0))],
        ):
            assert validate_public_url("https://example.com/foo") == "https://example.com/foo"

    def test_private_networks_opt_in(self):
        assert validate_public_url("http://localhost/", allow_private_networks=True) == "http://localhost/"


class TestGlobValidator:
    def test_ok(self):
        assert validate_glob_pattern("**/*.py") == "**/*.py"

    @pytest.mark.parametrize(
        "bad",
        ["../etc/*", "/etc/passwd", "a/../b", ""],
    )
    def test_rejects(self, bad):
        with pytest.raises(ValueError):
            validate_glob_pattern(bad)


class TestResolveWithin:
    def test_contained(self, tmp_path: Path):
        (tmp_path / "x.txt").write_text("hi")
        ok, p = resolve_within("x.txt", tmp_path)
        assert ok and p == (tmp_path / "x.txt").resolve()

    def test_escape(self, tmp_path: Path):
        ok, _ = resolve_within("../secret", tmp_path)
        assert ok is False


class TestSecretHelpers:
    def test_redact_password_none(self):
        assert redact_password(None) == ""

    def test_redact_password_empty(self):
        assert redact_password("") == ""

    def test_redact_password_nonempty(self):
        assert redact_password("hunter2") == "***REDACTED***"

    def test_unwrap_secret_none(self):
        assert unwrap_secret(None) is None

    def test_unwrap_secret_plain_string(self):
        assert unwrap_secret("plain") == "plain"

    def test_unwrap_secret_duck_typed(self):
        class _FakeSecret:
            def get_secret_value(self) -> str:
                return "sensitive"

        assert unwrap_secret(_FakeSecret()) == "sensitive"


# ---------- PythonTools ---------------------------------------------


class TestPythonTools:
    def test_pip_not_registered_by_default(self, tmp_path: Path):
        from agno.tools.python import PythonTools

        pt = PythonTools(base_dir=tmp_path)
        names = {getattr(t, "name", getattr(t, "__name__", "")) for t in pt.tools}
        assert "pip_install_package" not in names
        assert "uv_pip_install_package" not in names

    def test_unsafe_unrestricted_required(self):
        from agno.tools.python import PythonTools

        with pytest.raises(ValueError):
            PythonTools(restrict_to_base_dir=False)

    def test_pip_allowlist_blocks_unknown(self, tmp_path: Path):
        from agno.tools.python import PythonTools

        pt = PythonTools(
            base_dir=tmp_path,
            enable_pip_install=True,
            pip_install_allowlist=["requests"],
        )
        msg = pt.pip_install_package("malicious==1.0")
        assert "allowlist" in msg.lower() or "Error" in msg

    def test_exec_does_not_mutate_toolkit_state(self, tmp_path: Path):
        from agno.tools.python import PythonTools

        pt = PythonTools(base_dir=tmp_path)
        pt.run_python_code("x = 42", variable_to_return="x")
        assert "x" not in pt.safe_locals
        assert "x" not in pt.safe_globals


# ---------- ShellTools ----------------------------------------------


class TestShellTools:
    def test_default_empty_allowlist(self, tmp_path: Path):
        from agno.tools.shell import ShellTools

        st = ShellTools(base_dir=tmp_path)
        out = st.run_shell_command(["/bin/echo", "hi"])
        assert "not in the allowlist" in out

    def test_allowlisted_command_runs(self, tmp_path: Path):
        from agno.tools.shell import ShellTools

        st = ShellTools(base_dir=tmp_path, allowed_commands=["echo"])
        out = st.run_shell_command(["echo", "hi"])
        assert "hi" in out

    def test_metachars_rejected(self, tmp_path: Path):
        from agno.tools.shell import ShellTools

        st = ShellTools(base_dir=tmp_path, allowed_commands=["echo"])
        out = st.run_shell_command(["echo", "a; rm -rf /"])
        assert "Error" in out and "metacharacter" in out.lower()


# ---------- LocalFileSystemTools ------------------------------------


class TestLocalFileSystemTools:
    def test_refuses_directory_escape(self, tmp_path: Path):
        from agno.tools.local_file_system import LocalFileSystemTools

        tgt = tmp_path / "target"
        tgt.mkdir()
        lfs = LocalFileSystemTools(target_directory=str(tgt))
        res = lfs.write_file(
            content="pwned",
            filename="evil",
            directory="../../../etc",
        )
        assert "outside the configured target_directory" in res

    def test_refuses_path_separator_in_filename(self, tmp_path: Path):
        from agno.tools.local_file_system import LocalFileSystemTools

        lfs = LocalFileSystemTools(target_directory=str(tmp_path))
        res = lfs.write_file(content="x", filename="a/b")
        assert "path separators" in res

    def test_writes_inside(self, tmp_path: Path):
        from agno.tools.local_file_system import LocalFileSystemTools

        lfs = LocalFileSystemTools(target_directory=str(tmp_path))
        res = lfs.write_file(content="hello", filename="note.txt")
        assert "Successfully wrote" in res
        assert (tmp_path / "note.txt").read_text() == "hello"


# ---------- FileTools glob ------------------------------------------


class TestFileToolsGlob:
    def test_parent_pattern_rejected(self, tmp_path: Path):
        from agno.tools.file import FileTools

        ft = FileTools(base_dir=tmp_path)
        out = ft.search_files("../**/*.py")
        assert "Error" in out


# ---------- CustomApiTools ------------------------------------------


class TestCustomApiTools:
    def test_verify_ssl_false_requires_ack(self):
        from agno.tools.api import CustomApiTools

        with pytest.raises(ValueError):
            CustomApiTools(verify_ssl=False)
        CustomApiTools(verify_ssl=False, acknowledge_mitm_risk=True)


# ---------- DuckDB identifier quoting (needs duckdb driver) ---------


class TestDuckDbQuoting:
    def _mod(self):
        duckdb = pytest.importorskip("duckdb")
        del duckdb  # only used for skip
        from agno.tools import duckdb as mod

        return mod

    def test_q_rejects_bad_ident(self):
        mod = self._mod()
        with pytest.raises(ValueError):
            mod._q("a; DROP TABLE x;--")

    def test_q_ok(self):
        mod = self._mod()
        assert mod._q("my_table") == '"my_table"'


# ---------- Neo4j read-only gate (no driver import required) --------


class TestNeo4jReadOnly:
    def test_write_cypher_regex(self):
        pytest.importorskip("neo4j")
        from agno.tools.neo4j import _CYPHER_WRITE_RE

        assert _CYPHER_WRITE_RE.search("CREATE (n:Person)")
        assert _CYPHER_WRITE_RE.search("MATCH (n) DELETE n")
        assert _CYPHER_WRITE_RE.search("CALL apoc.cypher.doIt('...')")
        assert not _CYPHER_WRITE_RE.search("MATCH (n:Person {name: $name}) RETURN n")


# ---------- Docker DOCKER_CONFIG wipe is gone -----------------------


class TestDockerConfigWipe:
    def test_docker_tools_no_longer_wipes_docker_config(self):
        docker_py = Path(__file__).resolve().parents[3] / "agno/tools/docker.py"
        text = docker_py.read_text()
        assert 'os.environ["DOCKER_CONFIG"] = ""' not in text
        assert "os.environ['DOCKER_CONFIG'] = ''" not in text


# ---------- v2.6.5-hardened.3 additions -----------------------------


class TestPythonToolsUnsafeExecGate:
    """Code-execution tools must be opt-in under ``unsafe_exec``."""

    def test_exec_tools_not_registered_by_default(self, tmp_path: Path):
        from agno.tools.python import PythonTools

        pt = PythonTools(base_dir=tmp_path)
        names = {getattr(t, "name", getattr(t, "__name__", "")) for t in pt.tools}
        assert "run_python_code" not in names
        assert "save_to_file_and_run" not in names
        assert "run_python_file_return_variable" not in names

    def test_exec_tools_registered_when_unsafe_exec_true(self, tmp_path: Path):
        from agno.tools.python import PythonTools

        pt = PythonTools(base_dir=tmp_path, unsafe_exec=True)
        names = {getattr(t, "name", getattr(t, "__name__", "")) for t in pt.tools}
        assert "run_python_code" in names

    def test_safe_builtins_applied_by_default(self, tmp_path: Path):
        from agno.tools.python import PythonTools

        pt = PythonTools(base_dir=tmp_path, unsafe_exec=True)
        builtins_ns = pt.safe_globals["__builtins__"]
        assert "open" not in builtins_ns
        assert "exec" not in builtins_ns
        assert "__import__" not in builtins_ns
        assert "len" in builtins_ns

    def test_unsafe_exec_full_builtins_requires_unsafe_exec(self, tmp_path: Path):
        from agno.tools.python import PythonTools

        with pytest.raises(ValueError):
            PythonTools(
                base_dir=tmp_path,
                unsafe_exec=False,
                unsafe_exec_full_builtins=True,
            )

    def test_fresh_exec_globals_is_isolated(self, tmp_path: Path):
        from agno.tools.python import PythonTools

        pt = PythonTools(base_dir=tmp_path, unsafe_exec=True)
        g1 = pt._fresh_exec_globals()
        g1["__builtins__"]["len"] = "mutated"
        g2 = pt._fresh_exec_globals()
        assert g2["__builtins__"]["len"] is len


class TestDockerRunContainerHardening:
    def _tools(self, **kw):
        from unittest.mock import patch

        with patch("agno.tools.docker.docker.DockerClient") as mc:
            mc.return_value.ping.return_value = True
            from agno.tools.docker import DockerTools

            return DockerTools(
                enable_privileged_ops=True,
                image_allowlist=["nginx:latest"],
                **kw,
            )

    def test_blanket_denies_root_bind(self):
        d = self._tools()
        out = d.run_container(
            "nginx:latest",
            volumes={"/": {"bind": "/h", "mode": "rw"}},
        )
        assert "blanket-denied" in out

    def test_blanket_denies_docker_sock(self):
        d = self._tools()
        out = d.run_container(
            "nginx:latest",
            volumes={
                "/var/run/docker.sock": {"bind": "/s", "mode": "rw"},
            },
        )
        assert "blanket-denied" in out

    def test_blanket_denies_host_network(self):
        d = self._tools()
        out = d.run_container("nginx:latest", network="host")
        assert "blanket-denied" in out

    def test_requires_bind_mount_allowlist(self):
        d = self._tools()
        out = d.run_container(
            "nginx:latest",
            volumes={"/tmp/s": {"bind": "/d", "mode": "ro"}},
        )
        assert "allowed_bind_mounts" in out

    def test_requires_env_allowlist(self):
        d = self._tools()
        out = d.run_container("nginx:latest", environment={"F": "b"})
        assert "allowed_env_keys" in out

    def test_operator_allowlist_cannot_override_blanket_deny(self):
        d = self._tools(allowed_bind_mounts=["/etc"])
        out = d.run_container(
            "nginx:latest",
            volumes={"/etc": {"bind": "/x", "mode": "ro"}},
        )
        assert "blanket-denied" in out


class TestDockerInspectionGate:
    def test_inspection_tools_hidden_by_default(self):
        from unittest.mock import patch

        with patch("agno.tools.docker.docker.DockerClient") as mc:
            mc.return_value.ping.return_value = True
            from agno.tools.docker import DockerTools

            d = DockerTools()
            names = sorted(f.name for f in d.functions.values())
            assert "list_volumes" not in names
            assert "inspect_volume" not in names
            assert "list_networks" not in names
            assert "inspect_network" not in names

    def test_inspection_tools_surface_when_opted_in(self):
        from unittest.mock import patch

        with patch("agno.tools.docker.docker.DockerClient") as mc:
            mc.return_value.ping.return_value = True
            from agno.tools.docker import DockerTools

            d = DockerTools(enable_inspection_ops=True)
            names = sorted(f.name for f in d.functions.values())
            for expected in (
                "list_volumes",
                "inspect_volume",
                "list_networks",
                "inspect_network",
            ):
                assert expected in names


class TestCustomApiToolsRedirect:
    def test_redirect_to_private_network_is_blocked(self):
        from unittest.mock import MagicMock, patch

        from agno.tools.api import CustomApiTools

        api = CustomApiTools(base_url="https://example.com")
        redirect = MagicMock(
            status_code=302,
            headers={"Location": "http://169.254.169.254/latest/meta-data/"},
        )

        def _gai(host, *args, **kwargs):
            # Honor IP literals so the metadata IP validates as itself;
            # everything else resolves to a public test address.
            try:
                import ipaddress as _ip

                _ip.ip_address(host)
                return [(None, None, None, "", (host, 0))]
            except ValueError:
                return [(None, None, None, "", ("8.8.8.8", 0))]

        with patch(
            "agno.tools.api.requests.request",
            return_value=redirect,
        ) as mock_req:
            with mock.patch.object(socket, "getaddrinfo", side_effect=_gai):
                out = api.make_request("/redirector")
        assert "private" in out.lower() or "blocked" in out.lower()
        assert mock_req.call_count == 1

    def test_max_redirects_exhaustion(self):
        from unittest.mock import MagicMock, patch

        from agno.tools.api import CustomApiTools

        api = CustomApiTools(
            base_url="https://example.com",
            max_redirects=2,
        )
        loop = MagicMock(
            status_code=302,
            headers={"Location": "https://example.com/loop"},
        )
        with patch(
            "agno.tools.api.requests.request",
            return_value=loop,
        ) as mock_req:
            with mock.patch.object(
                socket,
                "getaddrinfo",
                return_value=[
                    (None, None, None, "", ("8.8.8.8", 0)),
                ],
            ):
                out = api.make_request("/loop")
        assert "max_redirects" in out
        assert mock_req.call_count == 3


class TestSQLEngineReadOnly:
    def test_sqlite_engine_ro_blocks_insert(self, tmp_path: Path):
        from sqlalchemy import create_engine, text

        from agno.tools.sql import SQLTools

        db = tmp_path / "t.db"
        seed = create_engine(f"sqlite:///{db}")
        with seed.begin() as c:
            c.execute(text("CREATE TABLE t(x INTEGER)"))
            c.execute(text("INSERT INTO t VALUES (1)"))

        st = SQLTools(db_url=f"sqlite:///{db}", read_only=True)

        with pytest.raises(Exception) as exc:
            st.run_sql("INSERT INTO t VALUES (2)")
        assert "readonly" in str(exc.value).lower()

        with seed.begin() as c:
            count = c.execute(text("SELECT count(*) FROM t")).scalar()
        assert count == 1

    def test_engine_ro_not_applied_when_read_only_false(self, tmp_path: Path):
        from sqlalchemy import create_engine, text

        from agno.tools.sql import SQLTools

        db = tmp_path / "t.db"
        seed = create_engine(f"sqlite:///{db}")
        with seed.begin() as c:
            c.execute(text("CREATE TABLE t(x INTEGER)"))

        st = SQLTools(db_url=f"sqlite:///{db}", read_only=False)
        st.run_sql("INSERT INTO t VALUES (1)")

        with seed.begin() as c:
            count = c.execute(text("SELECT count(*) FROM t")).scalar()
        assert count == 1
