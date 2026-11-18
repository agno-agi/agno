from dataclasses import dataclass
from os import getenv
from platform import python_version
from typing import Any, Dict, Optional

from agno import __version__
from agno.models.base import Model
from agno.models.openai.chat import OpenAIChat


@dataclass
class OpenAILike(OpenAIChat):
    """
    A class for interacting with providers that use the OpenAI API schema.

    New clients send ``agno/<version> Python/<python-version>`` as their User-Agent.
    Set ``AGNO_USER_AGENT`` to change the default. A User-Agent supplied in
    ``default_headers`` or ``client_params["default_headers"]`` takes precedence.

    Args:
        id (str): The id of the OpenAI model to use. Defaults to "not-provided".
        name (str): The name of the OpenAI model to use. Defaults to "OpenAILike".
        api_key (Optional[str]): The API key to use. Defaults to "not-provided".
    """

    id: str = "not-provided"
    name: str = "OpenAILike"
    api_key: Optional[str] = "not-provided"

    default_role_map = {
        "system": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
    }

    def get_provider(self) -> str:
        return Model.get_provider(self)

    def _with_client_defaults(self, client_params: Dict[str, Any]) -> Dict[str, Any]:
        headers = {
            "User-Agent" if name.lower() == "user-agent" else name: value
            for name, value in (client_params.get("default_headers") or {}).items()
        }
        if "User-Agent" not in headers:
            headers["User-Agent"] = getenv("AGNO_USER_AGENT", f"agno/{__version__} Python/{python_version()}")
        return {**client_params, "default_headers": headers}
