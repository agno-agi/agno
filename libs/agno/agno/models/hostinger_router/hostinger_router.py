from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class HostingerRouter(OpenAILike):
    """
    A class for interacting with Hostinger Router, an OpenAI-compatible gateway that serves
    models from OpenAI, Anthropic, Google and others.

    Attributes:
        id (str): The id of the Hostinger Router model to use. Default is "gpt-5-mini".
            Model ids carry no vendor prefix (for example "gpt-5-mini", "claude-sonnet-5",
            "gemini-3.5-flash"); some models also have "-eu" / "-us" regional variants.
        name (str): The name of this chat model instance. Default is "HostingerRouter".
        provider (str): The provider of the model. Default is "HostingerRouter".
        api_key (str): The api key to authorize request to Hostinger Router.
        base_url (str): The base url to which the requests are sent.
            Defaults to "https://router.hostinger.com/v1".
    """

    id: str = "gpt-5-mini"
    name: str = "HostingerRouter"
    provider: str = "HostingerRouter"
    api_key: Optional[str] = field(default_factory=lambda: getenv("HOSTINGER_ROUTER_API_KEY"))
    base_url: str = "https://router.hostinger.com/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for HOSTINGER_ROUTER_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("HOSTINGER_ROUTER_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="HOSTINGER_ROUTER_API_KEY not set. Please set the HOSTINGER_ROUTER_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
