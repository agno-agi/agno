"""Credentials for calling the GitHub API as a GitHub App.

A GitHub App signs a short-lived JWT with its private key and exchanges it for an installation token
(valid for an hour), scoped to the repositories and permissions the installation grants. Tokens are
cached per installation until a minute before they expire.
"""

import asyncio
import threading
import time
from datetime import datetime
from os import getenv
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import httpx

GITHUB_API_URL = "https://api.github.com"
_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Agno"}
# Refresh a cached installation token this many seconds before it expires.
_EXPIRY_MARGIN = 60


def _is_file(value: str) -> bool:
    # A long string that isn't a path (e.g. a base64-encoded key) makes is_file() raise instead of returning False.
    try:
        return Path(value).expanduser().is_file()
    except (OSError, ValueError):
        return False


class GitHubAppCredentials:
    """A GitHub App's installation tokens, minted from its App ID and private key."""

    def __init__(
        self,
        app_id: Optional[Union[int, str]] = None,
        private_key: Optional[str] = None,
        api_url: str = GITHUB_API_URL,
    ):
        """
        Args:
            app_id: The App ID from the App's settings page. Defaults to GITHUB_APP_ID.
            private_key: The App's private key (PEM), or a path to the .pem file. Defaults to
                GITHUB_APP_PRIVATE_KEY, then the file named by GITHUB_APP_PRIVATE_KEY_PATH.
            api_url: The GitHub API root, for GitHub Enterprise Server.
        """
        resolved_id = app_id if app_id is not None else getenv("GITHUB_APP_ID")
        if not resolved_id:
            raise ValueError("A GitHub App ID is required: pass app_id or set GITHUB_APP_ID")
        key = private_key or getenv("GITHUB_APP_PRIVATE_KEY")
        if not key and getenv("GITHUB_APP_PRIVATE_KEY_PATH"):
            key = Path(getenv("GITHUB_APP_PRIVATE_KEY_PATH", "")).expanduser().read_text()
        if key and "-----BEGIN" not in key and _is_file(key):
            key = Path(key).expanduser().read_text()
        if key and "-----BEGIN" in key and "\\n" in key and "\n" not in key.strip():
            # A PEM kept on one line in a .env file, with its line breaks written as \n.
            key = key.replace("\\n", "\n")
        if not key or "-----BEGIN" not in key:
            raise ValueError(
                "A GitHub App private key (PEM) is required: pass private_key or set GITHUB_APP_PRIVATE_KEY "
                "or GITHUB_APP_PRIVATE_KEY_PATH"
            )
        self.app_id = str(resolved_id)
        self._private_key = key
        self.api_url = api_url.rstrip("/")
        self._tokens: Dict[int, Tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._async_lock: Optional[asyncio.Lock] = None

    def app_jwt(self) -> str:
        """A JWT that authenticates as the App itself, valid for ten minutes."""
        try:
            import jwt
        except ImportError:
            raise ImportError("GitHub App authentication requires PyJWT: pip install PyJWT cryptography")
        now = int(time.time())
        # Backdated a minute to allow for clock drift, as GitHub recommends.
        payload = {"iat": now - 60, "exp": now + 540, "iss": self.app_id}
        try:
            return jwt.encode(payload, self._private_key, algorithm="RS256")
        except NotImplementedError:
            raise ImportError("GitHub App authentication requires cryptography: pip install cryptography")

    def _cached(self, installation_id: int) -> Optional[str]:
        cached = self._tokens.get(installation_id)
        if cached is not None and time.time() < cached[1] - _EXPIRY_MARGIN:
            return cached[0]
        return None

    def _store(self, installation_id: int, data: Dict[str, Any]) -> str:
        token = data["token"]
        try:
            expires_at = datetime.fromisoformat(str(data.get("expires_at")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            expires_at = time.time() + 3600
        self._tokens[installation_id] = (token, expires_at)
        return token

    def _exchange(self, installation_id: int) -> Tuple[str, Dict[str, str]]:
        url = f"{self.api_url}/app/installations/{installation_id}/access_tokens"
        return url, {**_HEADERS, "Authorization": f"Bearer {self.app_jwt()}"}

    def token(self, installation_id: Optional[int] = None) -> str:
        """An installation token, from the cache while it has more than a minute left."""
        if installation_id is None:
            raise ValueError("A GitHub App token needs the installation ID")
        cached = self._cached(installation_id)
        if cached is not None:
            return cached
        with self._lock:
            cached = self._cached(installation_id)
            if cached is not None:
                return cached
            url, headers = self._exchange(installation_id)
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, headers=headers)
                response.raise_for_status()
                return self._store(installation_id, response.json())

    async def atoken(self, installation_id: Optional[int] = None) -> str:
        """An installation token, from the cache while it has more than a minute left."""
        if installation_id is None:
            raise ValueError("A GitHub App token needs the installation ID")
        cached = self._cached(installation_id)
        if cached is not None:
            return cached
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        async with self._async_lock:
            cached = self._cached(installation_id)
            if cached is not None:
                return cached
            url, headers = self._exchange(installation_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers)
                response.raise_for_status()
                return self._store(installation_id, response.json())

    def installation_id(self, repository: str) -> int:
        """The installation that covers a repository ("owner/name"), for work that has no event to read it from."""
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self.api_url}/repos/{repository}/installation",
                headers={**_HEADERS, "Authorization": f"Bearer {self.app_jwt()}"},
            )
            response.raise_for_status()
            return int(response.json()["id"])

    async def ainstallation_id(self, repository: str) -> int:
        """The installation that covers a repository ("owner/name"), for work that has no event to read it from."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.api_url}/repos/{repository}/installation",
                headers={**_HEADERS, "Authorization": f"Bearer {self.app_jwt()}"},
            )
            response.raise_for_status()
            return int(response.json()["id"])
