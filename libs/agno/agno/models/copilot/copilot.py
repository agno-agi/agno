import time
from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

import httpx

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.utils.log import log_debug

# Default headers required by the GitHub Copilot API
_COPILOT_HEADERS = {
    "editor-version": "vscode/1.104.0",
    "editor-plugin-version": "copilot.vim/1.16.0",
    "user-agent": "GithubCopilot/1.155.0",
    "Copilot-Vision-Request": "true",
}


@dataclass
class CopilotChat(OpenAILike):
    """
    A class for interacting with GitHub Copilot models via the Copilot API.

    The provider automatically exchanges a GitHub token for a short-lived
    Copilot access token, caching and refreshing it as needed.

    Attributes:
        id: The model id to use. Default is "gpt-4.1".
        name: Display name for the model. Default is "CopilotChat".
        provider: Provider identifier. Default is "Copilot".
        github_token: A GitHub personal access token with Copilot access.
            Falls back to GITHUB_COPILOT_TOKEN environment variable.
        base_url: The Copilot API endpoint.
    """

    id: str = "gpt-4.1"
    name: str = "CopilotChat"
    provider: str = "Copilot"

    # The user provides their GitHub token; the access token is managed internally.
    github_token: Optional[str] = None
    base_url: str = "https://api.githubcopilot.com/"

    # Internal token state — not user-facing.
    _copilot_token: str = field(default="", init=False, repr=False)
    _copilot_token_expires_at: float = field(default=0.0, init=False, repr=False)

    def _resolve_github_token(self) -> str:
        """Return the GitHub token, reading from env if not set explicitly."""
        if self.github_token:
            return self.github_token

        token = getenv("GITHUB_COPILOT_TOKEN")
        if not token:
            raise ModelAuthenticationError(
                message=(
                    "GitHub token not provided. "
                    "Set github_token on CopilotChat or the GITHUB_COPILOT_TOKEN environment variable."
                ),
                model_name=self.name,
            )
        self.github_token = token
        return token

    def _refresh_copilot_token(self) -> str:
        """Exchange the GitHub token for a short-lived Copilot access token.

        The token is cached and only refreshed when it expires (with a 60-second buffer).
        """
        now = time.time()
        if self._copilot_token and now < (self._copilot_token_expires_at - 60):
            return self._copilot_token

        github_token = self._resolve_github_token()
        log_debug("Refreshing Copilot access token")

        response = httpx.get(
            "https://api.github.com/copilot_internal/v2/token",
            headers={
                "authorization": f"token {github_token}",
                **_COPILOT_HEADERS,
            },
            timeout=10,
        )
        if response.status_code != 200:
            raise ModelAuthenticationError(
                message=(f"Failed to obtain Copilot access token: {response.status_code} - {response.text}"),
                model_name=self.name,
            )

        payload = response.json()
        self._copilot_token = payload.get("token", "")
        self._copilot_token_expires_at = float(payload.get("expires_at", 0))

        if not self._copilot_token:
            raise ModelAuthenticationError(
                message="Copilot token response did not contain a token.",
                model_name=self.name,
            )
        return self._copilot_token

    def _get_client_params(self) -> Dict[str, Any]:
        """Refresh the Copilot access token, then build client params."""
        self.api_key = self._refresh_copilot_token()
        self.default_headers = {**(self.default_headers or {}), **_COPILOT_HEADERS}
        return super()._get_client_params()

    def get_client(self):  # type: ignore[override]
        """Return a sync OpenAI client, refreshing the access token if needed."""
        token = self._refresh_copilot_token()
        # Invalidate cached client when the token has changed
        if self.client is not None and self.api_key != token:
            if not self.client.is_closed():
                self.client.close()
            self.client = None
        return super().get_client()

    def get_async_client(self):  # type: ignore[override]
        """Return an async OpenAI client, refreshing the access token if needed."""
        token = self._refresh_copilot_token()
        # Invalidate cached client when the token has changed
        if self.async_client is not None and self.api_key != token:
            self.async_client = None
        return super().get_async_client()
