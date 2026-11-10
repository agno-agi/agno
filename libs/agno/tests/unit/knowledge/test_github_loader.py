"""Tests for GitHubLoader authentication helpers."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.loaders.github import GitHubLoader
from agno.knowledge.remote_content.github import GitHubConfig


@pytest.fixture
def loader():
    loader = GitHubLoader.__new__(GitHubLoader)
    # Reset the class-level cache before each test
    GitHubLoader._github_app_token_cache = {}
    return loader


@pytest.fixture
def token_config():
    return GitHubConfig(
        id="test",
        name="Test",
        repo="owner/repo",
        token="ghp_test_token",
    )


@pytest.fixture
def app_config():
    return GitHubConfig(
        id="test-app",
        name="Test App",
        repo="org/repo",
        app_id=12345,
        installation_id=67890,
        private_key="-----BEGIN RSA PRIVATE KEY-----\nfake_key\n-----END RSA PRIVATE KEY-----",
    )


class TestBuildGitHubHeaders:
    def test_with_token(self, loader, token_config):
        """Test that _build_github_headers uses the token."""
        headers = loader._build_github_headers(token_config)
        assert headers["Authorization"] == "Bearer ghp_test_token"
        assert headers["Accept"] == "application/vnd.github.v3+json"

    def test_without_auth(self, loader):
        """Test headers for public repos (no auth)."""
        config = GitHubConfig(id="pub", name="Pub", repo="owner/public-repo")
        headers = loader._build_github_headers(config)
        assert "Authorization" not in headers
        assert headers["Accept"] == "application/vnd.github.v3+json"

    def test_with_app_auth(self, loader, app_config):
        """Test that _build_github_headers uses app auth when app_id is set."""
        with patch.object(loader, "_get_github_app_token", return_value="ghs_installation_token") as mock_get:
            headers = loader._build_github_headers(app_config)
            assert headers["Authorization"] == "Bearer ghs_installation_token"
            mock_get.assert_called_once_with(app_config)

    def test_app_auth_takes_precedence_over_token(self, loader):
        """Test that app auth is used when both token and app fields are set."""
        config = GitHubConfig(
            id="both",
            name="Both",
            repo="owner/repo",
            token="ghp_pat_token",
            app_id=111,
            installation_id=222,
            private_key="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
        )
        with patch.object(loader, "_get_github_app_token", return_value="ghs_app_token"):
            headers = loader._build_github_headers(config)
            assert headers["Authorization"] == "Bearer ghs_app_token"


class TestGetGitHubAppToken:
    @patch("agno.knowledge.loaders.github.httpx.Client")
    @patch("jwt.encode", return_value="fake_jwt_token")
    def test_generates_token(self, mock_jwt_encode, mock_client_cls, loader, app_config):
        """Test JWT generation and token exchange."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "ghs_installation_abc",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        token = loader._get_github_app_token(app_config)

        assert token == "ghs_installation_abc"
        mock_jwt_encode.assert_called_once()
        call_args = mock_jwt_encode.call_args
        assert call_args[0][0]["iss"] == "12345"
        assert call_args[1]["algorithm"] == "RS256"

    @patch("agno.knowledge.loaders.github.httpx.Client")
    @patch("jwt.encode", return_value="fake_jwt")
    def test_caches_token(self, mock_jwt_encode, mock_client_cls, loader, app_config):
        """Test that the token is cached and reused."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "ghs_cached",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        # First call generates token
        token1 = loader._get_github_app_token(app_config)
        # Second call should use cache
        token2 = loader._get_github_app_token(app_config)

        assert token1 == token2 == "ghs_cached"
        # JWT should only be generated once
        assert mock_jwt_encode.call_count == 1

    @patch("agno.knowledge.loaders.github.httpx.Client")
    @patch("jwt.encode", return_value="fake_jwt")
    def test_refreshes_expired_token(self, mock_jwt_encode, mock_client_cls, loader, app_config):
        """Test that an expired cached token is refreshed."""
        # Pre-populate cache with expired token
        cache_key = f"{app_config.app_id}:{app_config.installation_id}"
        GitHubLoader._github_app_token_cache[cache_key] = ("old_token", time.time() - 100)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "ghs_refreshed",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        token = loader._get_github_app_token(app_config)
        assert token == "ghs_refreshed"
        mock_jwt_encode.assert_called_once()

    def test_missing_pyjwt_raises(self, loader, app_config):
        """Test that missing PyJWT raises ImportError with install instructions."""
        with patch.dict("sys.modules", {"jwt": None}):
            with pytest.raises(ImportError, match="PyJWT"):
                loader._get_github_app_token(app_config)


class TestAsyncBuildGitHubHeaders:
    @pytest.mark.asyncio
    async def test_with_token(self, loader, token_config):
        """Test that _abuild_github_headers uses the token."""
        headers = await loader._abuild_github_headers(token_config)
        assert headers["Authorization"] == "Bearer ghp_test_token"
        assert headers["Accept"] == "application/vnd.github.v3+json"

    @pytest.mark.asyncio
    async def test_without_auth(self, loader):
        """Test async headers for public repos (no auth)."""
        config = GitHubConfig(id="pub", name="Pub", repo="owner/public-repo")
        headers = await loader._abuild_github_headers(config)
        assert "Authorization" not in headers
        assert headers["Accept"] == "application/vnd.github.v3+json"

    @pytest.mark.asyncio
    async def test_with_app_auth(self, loader, app_config):
        """Test that _abuild_github_headers uses async app auth when app_id is set."""
        with patch.object(
            loader, "_aget_github_app_token", new_callable=AsyncMock, return_value="ghs_async_token"
        ) as mock_get:
            headers = await loader._abuild_github_headers(app_config)
            assert headers["Authorization"] == "Bearer ghs_async_token"
            mock_get.assert_called_once_with(app_config)


class TestAsyncGetGitHubAppToken:
    @pytest.mark.asyncio
    @patch("jwt.encode", return_value="fake_jwt_token")
    async def test_generates_token(self, mock_jwt_encode, loader, app_config):
        """Test async JWT generation and token exchange."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "ghs_async_install",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("agno.knowledge.loaders.github.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await loader._aget_github_app_token(app_config)

        assert token == "ghs_async_install"
        mock_jwt_encode.assert_called_once()
        call_args = mock_jwt_encode.call_args
        assert call_args[0][0]["iss"] == "12345"
        assert call_args[1]["algorithm"] == "RS256"

    @pytest.mark.asyncio
    @patch("jwt.encode", return_value="fake_jwt")
    async def test_caches_token(self, mock_jwt_encode, loader, app_config):
        """Test that the async token is cached and reused."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "ghs_async_cached",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("agno.knowledge.loaders.github.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            token1 = await loader._aget_github_app_token(app_config)
            token2 = await loader._aget_github_app_token(app_config)

        assert token1 == token2 == "ghs_async_cached"
        assert mock_jwt_encode.call_count == 1

    @pytest.mark.asyncio
    @patch("jwt.encode", return_value="fake_jwt")
    async def test_refreshes_expired_token(self, mock_jwt_encode, loader, app_config):
        """Test that an expired cached token is refreshed in async path."""
        cache_key = f"{app_config.app_id}:{app_config.installation_id}"
        GitHubLoader._github_app_token_cache[cache_key] = ("old_token", time.time() - 100)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "ghs_async_refreshed",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("agno.knowledge.loaders.github.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await loader._aget_github_app_token(app_config)

        assert token == "ghs_async_refreshed"
        mock_jwt_encode.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_pyjwt_raises(self, loader, app_config):
        """Test that missing PyJWT raises ImportError in async path."""
        with patch.dict("sys.modules", {"jwt": None}):
            with pytest.raises(ImportError, match="PyJWT"):
                await loader._aget_github_app_token(app_config)


class TestLoadFromGithubMissingRepo:
    """When neither GitHubConfig nor GitHubContent supplies a repo, the loader
    must raise rather than silently return — otherwise direct SDK callers
    (Knowledge.insert / ainsert) treat a misconfigured upload as successful.
    """

    @pytest.fixture
    def content_without_repo(self):
        from agno.knowledge.content import Content
        from agno.knowledge.remote_content.remote_content import GitHubContent

        return Content(
            name="README.md",
            remote_content=GitHubContent(config_id="gh", file_path="README.md"),
        )

    def test_sync_raises_when_repo_missing(self, loader, content_without_repo):
        config = GitHubConfig(id="gh", name="GH")
        with pytest.raises(ValueError, match="GitHub repo not specified"):
            loader._load_from_github(content_without_repo, upsert=False, skip_if_exists=False, config=config)

    @pytest.mark.asyncio
    async def test_async_raises_when_repo_missing(self, loader, content_without_repo):
        config = GitHubConfig(id="gh", name="GH")
        with pytest.raises(ValueError, match="GitHub repo not specified"):
            await loader._aload_from_github(content_without_repo, upsert=False, skip_if_exists=False, config=config)
