"""`agno db status` / `agno db migrate`: the migration check and apply flow over the API."""

import json

from typer.testing import CliRunner

from agnoctl.main import app
from tests.conftest import FakeAgentOS, install_fake
from tests.conftest import all_output as _all_output

runner = CliRunner()

URL_ARGS = ["--url", "http://localhost:7777"]

PENDING_METRICS = {
    "table_type": "metrics",
    "table_name": "agno_metrics",
    "current_version": "2.0.0",
    "target_version": "3.0.0",
}


def _fake_with_pending(monkeypatch, **kwargs) -> FakeAgentOS:
    fake = FakeAgentOS(**kwargs)
    fake.pending_migrations = {"main-db": [PENDING_METRICS], "other-db": []}
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)
    return fake


def test_db_status_lists_pending_tables_and_changes_nothing(monkeypatch):
    fake = _fake_with_pending(monkeypatch)

    result = runner.invoke(app, ["db", "status"] + URL_ARGS)

    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "main-db: 1 table(s) pending" in out
    assert "agno_metrics [metrics]: 2.0.0 -> 3.0.0" in out
    assert "other-db: up to date" in out
    assert "agno db migrate" in out
    assert fake.migrate_calls == []


def test_db_status_json(monkeypatch):
    _fake_with_pending(monkeypatch)

    result = runner.invoke(app, ["db", "status", "--json"] + URL_ARGS)

    assert result.exit_code == 0, _all_output(result)
    payload = json.loads(result.output)
    assert payload["total_pending"] == 1
    assert payload["databases"][0]["pending"] == [PENDING_METRICS]


def test_db_status_reports_up_to_date(monkeypatch):
    fake = FakeAgentOS()
    fake.pending_migrations = {"main-db": []}
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)

    result = runner.invoke(app, ["db", "status"] + URL_ARGS)

    assert result.exit_code == 0, _all_output(result)
    assert "All databases are up to date" in _all_output(result)


def test_db_migrate_dry_run_does_not_call_migrate(monkeypatch):
    fake = _fake_with_pending(monkeypatch)

    result = runner.invoke(app, ["db", "migrate", "--dry-run"] + URL_ARGS)

    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "Dry run, nothing applied" in out
    assert "agno_metrics [metrics]: 2.0.0 -> 3.0.0" in out
    assert "1 table(s) would be migrated" in out
    assert fake.migrate_calls == []
    assert fake.pending_migrations["main-db"] == [PENDING_METRICS]


def test_db_migrate_applies_to_all_databases(monkeypatch):
    fake = _fake_with_pending(monkeypatch)

    result = runner.invoke(app, ["db", "migrate"] + URL_ARGS)

    assert result.exit_code == 0, _all_output(result)
    assert "All databases migrated successfully to latest version" in _all_output(result)
    assert fake.migrate_calls == [("/databases/all/migrate", None)]
    assert fake.pending_migrations["main-db"] == []


def test_db_migrate_single_database_with_target_version(monkeypatch):
    fake = _fake_with_pending(monkeypatch)

    result = runner.invoke(app, ["db", "migrate", "--db-id", "main-db", "--target-version", "3.0.0"] + URL_ARGS)

    assert result.exit_code == 0, _all_output(result)
    assert fake.migrate_calls == [("/databases/main-db/migrate", "3.0.0")]
    assert fake.pending_migrations["main-db"] == []
    assert fake.pending_migrations["other-db"] == []


def test_db_migrate_unknown_database_is_a_clear_error(monkeypatch):
    _fake_with_pending(monkeypatch)

    result = runner.invoke(app, ["db", "migrate", "--db-id", "nope"] + URL_ARGS)

    assert result.exit_code == 1, _all_output(result)
    assert "No database with id 'nope'" in _all_output(result)


def test_db_migrate_partial_failure_exits_nonzero_and_names_the_database(monkeypatch):
    fake = _fake_with_pending(monkeypatch)
    fake.migrate_failures = {"main-db": "permission denied for ALTER TABLE"}

    result = runner.invoke(app, ["db", "migrate"] + URL_ARGS)

    assert result.exit_code == 1, _all_output(result)
    out = _all_output(result)
    assert "Migrated 1/2 databases" in out
    assert "main-db: permission denied for ALTER TABLE" in out


def test_db_migrate_json_partial_failure(monkeypatch):
    fake = _fake_with_pending(monkeypatch)
    fake.migrate_failures = {"main-db": "boom"}

    result = runner.invoke(app, ["db", "migrate", "--json"] + URL_ARGS)

    assert result.exit_code == 1, _all_output(result)
    payload = json.loads(result.output)
    assert payload["failed"] == {"main-db": "boom"}
    assert "_status_code" not in payload


def test_db_commands_require_a_valid_admin_credential(monkeypatch):
    fake = FakeAgentOS()
    fake.pending_migrations = {"main-db": []}
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", "wrong-token")

    result = runner.invoke(app, ["db", "status"] + URL_ARGS)

    assert result.exit_code == 1, _all_output(result)
    assert "rejected the admin credential" in _all_output(result)


def test_db_status_on_a_pre_3_server_explains_itself(monkeypatch):
    """Older servers have no pending endpoint; the CLI must say so rather than dump a 404."""
    fake = FakeAgentOS()
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)

    def handler(request):
        if request.url.path == "/databases/migrations/pending":
            import httpx

            return httpx.Response(404, json={"detail": "Not Found"})
        return fake.handler(request)

    import httpx

    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(handler))

    result = runner.invoke(app, ["db", "status"] + URL_ARGS)

    assert result.exit_code == 1, _all_output(result)
    assert "agno 3.0+ required" in _all_output(result)


def test_home_screen_lists_db_commands():
    result = runner.invoke(app, [])
    assert "agno db status / migrate" in _all_output(result)
