import platform
from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno import __version__ as _AGNO_VERSION
from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


def _default_user_agent() -> str:
    return f"agno/{_AGNO_VERSION} Python/{platform.python_version()}"


@dataclass
class Sarvam(OpenAILike):
    """
    A class for interacting with Sarvam AI Token Factory models.

    Sarvam exposes an OpenAI-compatible Chat Completions API at
    https://api.sarvam.ai/v2. Reasoning is returned in `reasoning_content` and
    controlled with `reasoning_effort`; the accepted values depend on the model.
    See https://docs.sarvam.ai/api/token-factory/chat-completions for the model
    list and the per-model reasoning levels.

    Attributes:
        id (str): The model id. Defaults to "sarvam-105b".
        name (str): The model name. Defaults to "Sarvam".
        provider (str): The provider name. Defaults to "Sarvam".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.sarvam.ai/v2".
        user_agent (Optional[str]): The User-Agent sent to Sarvam. Defaults to
            `agno/<version> Python/<python-version>`, or `AGNO_USER_AGENT` when set.
    """

    id: str = "sarvam-105b"
    name: str = "Sarvam"
    provider: str = "Sarvam"

    api_key: Optional[str] = field(default_factory=lambda: getenv("SARVAM_API_KEY"))
    base_url: str = "https://api.sarvam.ai/v2"
    user_agent: Optional[str] = field(default_factory=lambda: getenv("AGNO_USER_AGENT") or _default_user_agent())

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("SARVAM_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="SARVAM_API_KEY not set. Please set the SARVAM_API_KEY environment variable.",
                    model_name=self.name,
                )

        client_params = super()._get_client_params()

        # Identify Agno-originated traffic to Sarvam. A User-Agent the caller
        # set in `default_headers` or `client_params` still wins, in either
        # spelling. Normalize the key to `User-Agent` so the OpenAI SDK's own
        # default does not win on a case-sensitive dict merge.
        headers = dict(client_params.get("default_headers") or {})
        caller_user_agent = None
        for key in list(headers):
            if key.lower() == "user-agent":
                caller_user_agent = headers.pop(key)
                break
        headers["User-Agent"] = caller_user_agent or self.user_agent or _default_user_agent()
        client_params["default_headers"] = headers

        return client_params
