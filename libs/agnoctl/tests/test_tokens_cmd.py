"""`agno tokens` command behavior."""

import json

from typer.testing import CliRunner

from agnoctl.main import app

runner = CliRunner()

URL_ARGS = ["--url", "http://localhost:7777"]


def _run(args, **kwargs):
    return runner.invoke(app, args, **kwargs)


def test_create_json_includes_token_once(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["name"] == "ci-runner"
    assert payload["token"].startswith("agno_pat_")
    assert payload["principal"] == "sa:ci-runner"


def test_create_human_output_prints_token(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _run(["tokens", "create", "ci-runner"] + URL_ARGS)
    assert result.exit_code == 0, result.output
    token = fake_os.accounts["ci-runner"]["token"]
    assert token in result.output
    assert "shown once" in result.output


def test_create_conflict_errors_with_tokens_hint(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    result = _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "already exists" in payload["error"]
    # The hint must reference flags this command actually has.
    assert "agno tokens revoke ci-runner" in payload["hint"]
    assert "--rotate" not in payload["hint"]


def test_list_never_exposes_tokens(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    result = _run(["tokens", "list", "--json"] + URL_ARGS)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload["service_accounts"]) == 1
    assert "token" not in payload["service_accounts"][0]
    assert payload["service_accounts"][0]["token_prefix"]


def test_list_refuses_remote_env_file_url_in_json(monkeypatch, tmp_path, fake_os):
    """A reachable but non-loopback AGENTOS_URL from a cwd .env file is refused in --json runs."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    (tmp_path / ".env.production").write_text("AGENTOS_URL=https://evil.example\n")
    result = _run(["tokens", "list", "--json"])  # no --url: resolve from the env file
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert "remote host" in payload["error"]
    assert "--url" in payload["hint"] and "--yes" in payload["hint"]


def test_list_trusts_remote_env_file_url_with_yes(monkeypatch, tmp_path, fake_os):
    """--yes opts into a non-loopback env-file URL; the call then proceeds against it."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    (tmp_path / ".env.production").write_text("AGENTOS_URL=https://evil.example\n")
    result = _run(["tokens", "list", "--json", "--yes"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "service_accounts" in payload


def test_revoke_by_name(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    result = _run(["tokens", "revoke", "ci-runner", "--json"] + URL_ARGS)
    assert result.exit_code == 0
    assert fake_os.accounts["ci-runner"]["revoked_at"] is not None


def test_revoke_json_body_shows_revoked_at(monkeypatch, fake_os):
    """Regression: the revoke response body must reflect the post-revoke state.

    Before the fix, the CLI emitted the pre-revoke snapshot (fetched before the
    DELETE call), so ``revoked.revoked_at`` was ``None`` in the JSON body even
    though the account was in fact revoked on the server.
    """
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    result = _run(["tokens", "revoke", "ci-runner", "--json"] + URL_ARGS)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["revoked"]["revoked_at"] is not None


def test_revoke_unknown_name(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _run(["tokens", "revoke", "ghost", "--json"] + URL_ARGS)
    assert result.exit_code == 1
    assert "No service account named" in json.loads(result.output)["error"]


def test_missing_admin_credential_fails_with_hint(monkeypatch, fake_os):
    result = _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "AGNO_ADMIN_TOKEN" in payload["hint"]


def test_expires_never(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _run(["tokens", "create", "ci-runner", "--expires", "never", "--json"] + URL_ARGS)
    assert result.exit_code == 0
    assert json.loads(result.output)["expires_at"] is None


def test_expires_invalid(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _run(["tokens", "create", "ci-runner", "--expires", "soon", "--json"] + URL_ARGS)
    assert result.exit_code == 1
    assert "Invalid --expires" in json.loads(result.output)["error"]


REMOTE_HTTP = ["--url", "http://os.example.com:7777"]


def test_create_refuses_plaintext_http_to_remote_host(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _run(["tokens", "create", "ci-runner", "--json"] + REMOTE_HTTP)
    assert result.exit_code == 1
    assert "plaintext HTTP" in json.loads(result.output)["error"]
    # Nothing was minted.
    assert fake_os.create_calls == 0


def test_create_allow_http_override_permits_remote_http(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _run(["tokens", "create", "ci-runner", "--json", "--allow-http"] + REMOTE_HTTP)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["token"].startswith("agno_pat_")


def test_list_refuses_plaintext_http_with_admin_credential(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _run(["tokens", "list", "--json"] + REMOTE_HTTP)
    assert result.exit_code == 1
    assert "plaintext HTTP" in json.loads(result.output)["error"]


def test_revoke_interactive_decline_aborts(monkeypatch, fake_os):
    """A TTY user who answers 'no' cancels the revoke; the account stays active."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    monkeypatch.setattr("agnoctl.commands.tokens.stdin_is_interactive", lambda: True)
    result = _run(["tokens", "revoke", "ci-runner"] + URL_ARGS, input="n\n")
    assert result.exit_code == 0, result.output
    assert fake_os.accounts["ci-runner"]["revoked_at"] is None


def test_revoke_interactive_accept_revokes(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    monkeypatch.setattr("agnoctl.commands.tokens.stdin_is_interactive", lambda: True)
    result = _run(["tokens", "revoke", "ci-runner"] + URL_ARGS, input="y\n")
    assert result.exit_code == 0, result.output
    assert fake_os.accounts["ci-runner"]["revoked_at"] is not None


def test_revoke_yes_skips_confirmation(monkeypatch, fake_os):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    monkeypatch.setattr("agnoctl.commands.tokens.stdin_is_interactive", lambda: True)
    result = _run(["tokens", "revoke", "ci-runner", "--yes"] + URL_ARGS)
    assert result.exit_code == 0, result.output
    assert fake_os.accounts["ci-runner"]["revoked_at"] is not None


def test_create_on_open_plane_without_credential_fails_naming_the_server_gap(monkeypatch, fake_os):
    """An OS whose only auth is the OAuth provider on /mcp refuses anonymous mints, and
    its open REST plane would "accept" any credential right up to the failing POST;
    create must fail before resolving a credential, naming what the server is missing."""
    from tests.conftest import FakeAgentOS, install_fake

    fake = FakeAgentOS(auth_mode="none", oauth=True)
    install_fake(monkeypatch, fake)

    result = _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "no authentication configured" in payload["error"]
    assert "OS_SECURITY_KEY" in payload["hint"]
    assert fake.create_calls == 0


def test_create_on_open_plane_with_non_pat_credential_names_the_mismatch(monkeypatch, fake_os):
    from tests.conftest import FakeAgentOS, install_fake

    fake = FakeAgentOS(auth_mode="none", oauth=True)
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", "any-typed-value")

    result = _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    assert result.exit_code == 1
    assert "only a service-account token" in json.loads(result.output)["error"]
    assert fake.create_calls == 0


def test_create_on_open_plane_with_admin_pat_mints(monkeypatch, fake_os):
    """The anonymous-mint refusal is anonymous-only: a verified service-account bearer
    holding a minting scope mints even on an open REST plane."""
    from tests.conftest import FakeAgentOS, install_fake

    fake = FakeAgentOS(auth_mode="none", oauth=True)
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.seed_account("ops", ["admin"]))

    result = _run(["tokens", "create", "ci-runner", "--json"] + URL_ARGS)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["name"] == "ci-runner"
    assert "ci-runner" in fake.accounts
