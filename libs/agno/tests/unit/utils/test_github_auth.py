"""A GitHub App's installation tokens are minted with a JWT signed by the App's key and cached per installation."""

import asyncio
import time
from datetime import datetime, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agno.utils.github_auth import GitHubAppCredentials, GitHubToken


@pytest.fixture(scope="module")
def key_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


def expiring_in(seconds):
    return datetime.fromtimestamp(time.time() + seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def github(monkeypatch, key_pair):
    """Answers the token exchange and installation lookup, verifying the App JWT on each call."""
    calls = []
    lifetimes = {"seconds": 3600}

    def answer(method, url, headers):
        claims = jwt.decode(headers["Authorization"].removeprefix("Bearer "), key_pair[1], algorithms=["RS256"])
        calls.append((method, url, claims["iss"]))
        request = httpx.Request(method, url)
        if url.endswith("/installation"):
            return httpx.Response(200, json={"id": 77}, request=request)
        installation = url.split("/installations/")[1].split("/")[0]
        token = f"token-{installation}-{len(calls)}"
        return httpx.Response(
            201, json={"token": token, "expires_at": expiring_in(lifetimes["seconds"])}, request=request
        )

    monkeypatch.setattr(httpx.Client, "post", lambda self, url, headers: answer("POST", url, headers))
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, headers: answer("GET", url, headers))

    async def apost(self, url, headers):
        return answer("POST", url, headers)

    async def aget(self, url, headers):
        return answer("GET", url, headers)

    monkeypatch.setattr(httpx.AsyncClient, "post", apost)
    monkeypatch.setattr(httpx.AsyncClient, "get", aget)
    return calls, lifetimes


def test_installation_tokens_are_minted_once_per_installation_and_reused(github, key_pair):
    calls, _ = github
    credentials = GitHubAppCredentials(app_id=123, private_key=key_pair[0])
    first = credentials.token(1)
    assert credentials.token(1) == first
    assert credentials.token(2) != first
    assert asyncio.run(credentials.atoken(1)) == first
    assert calls == [
        ("POST", "https://api.github.com/app/installations/1/access_tokens", "123"),
        ("POST", "https://api.github.com/app/installations/2/access_tokens", "123"),
    ]
    assert credentials.installation_id("kausmeows/agno-webhook-test") == 77
    assert asyncio.run(credentials.ainstallation_id("kausmeows/agno-webhook-test")) == 77


def test_a_token_close_to_expiry_is_replaced(github, key_pair):
    calls, lifetimes = github
    lifetimes["seconds"] = 30
    credentials = GitHubAppCredentials(app_id=123, private_key=key_pair[0])
    assert asyncio.run(credentials.atoken(5)) != asyncio.run(credentials.atoken(5))
    assert len(calls) == 2


def test_the_app_jwt_is_short_lived_and_signed_by_the_apps_key(key_pair):
    claims = jwt.decode(GitHubAppCredentials(app_id="9", private_key=key_pair[0]).app_jwt(), key_pair[1], ["RS256"])
    now = time.time()
    assert claims["iss"] == "9" and claims["iat"] < now and now + 500 < claims["exp"] <= now + 600


def test_configuration_comes_from_arguments_files_or_the_environment(monkeypatch, tmp_path, key_pair):
    for name in ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_PRIVATE_KEY_PATH", "GITHUB_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="App ID"):
        GitHubAppCredentials(private_key=key_pair[0])
    with pytest.raises(ValueError, match="private key"):
        GitHubAppCredentials(app_id=1)
    with pytest.raises(ValueError, match="private key"):
        GitHubAppCredentials(app_id=1, private_key="not a key")
    with pytest.raises(ValueError, match="installation ID"):
        GitHubAppCredentials(app_id=1, private_key=key_pair[0]).token()

    pem = tmp_path / "app.pem"
    pem.write_text(key_pair[0])
    assert GitHubAppCredentials(app_id=1, private_key=str(pem)).app_id == "1"
    monkeypatch.setenv("GITHUB_APP_ID", "55")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", str(pem))
    assert GitHubAppCredentials().app_id == "55"

    with pytest.raises(ValueError, match="GITHUB_ACCESS_TOKEN"):
        GitHubToken()
    monkeypatch.setenv("GITHUB_ACCESS_TOKEN", "pat")
    assert GitHubToken().token() == "pat" and asyncio.run(GitHubToken().atoken(3)) == "pat"
