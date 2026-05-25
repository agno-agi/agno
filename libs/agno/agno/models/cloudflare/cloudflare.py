from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError, ModelProviderError
from agno.models.openai.like import OpenAILike
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_warning

# Default: Workers AI binding id as shown in the catalog "copy" box (see Workers AI docs).
DEFAULT_GATEWAY_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


def normalize_cloudflare_gateway_model_id(model_id: str) -> str:
    """
    Map user input to the AI Gateway ``model`` string.

    Workers AI models in the dashboard catalog use binding ids like ``@cf/google/gemma-4-26b-a4b-it``.
    The unified compat API expects ``workers-ai/<binding>``. If ``model_id`` starts with ``@cf/``,
    ``workers-ai/`` is prepended. Values that already start with ``workers-ai/``, or other gateway
    routes (``openai/...``, ``google/...``, ``dynamic/...``), are left unchanged (aside from ``strip``).
    """
    mid = model_id.strip()
    if not mid:
        return mid
    if mid.lower().startswith("workers-ai/"):
        return mid
    if mid.startswith("@cf/"):
        return f"workers-ai/{mid}"
    return mid


@dataclass
class Cloudflare(OpenAILike):
    """
    A class for using models through Cloudflare AI Gateway's OpenAI-compatible unified API.

    The default model runs on **Workers AI** and only needs ``CLOUDFLARE_API_TOKEN`` and
    ``CLOUDFLARE_ACCOUNT_ID``. You can switch to other vendors with ``{provider}/{model}`` (for example
    ``openai/gpt-5.4-mini``); those typically require **BYOK** keys in the Cloudflare dashboard. See:
    https://developers.cloudflare.com/ai-gateway/usage/chat-completion/

    **Compared to :class:`~agno.models.openrouter.OpenRouter`:** both use a slash-separated ``id`` string
    that selects the upstream route (OpenRouter model id vs AI Gateway ``vendor/model``). OpenRouter
    also accepts ``models=[...]`` for provider-side fallbacks via ``extra_body``; the Cloudflare compat
    endpoint sends a single OpenAI ``model`` field taken from ``id``. For fallbacks or A/B flows on
    Cloudflare, configure Dynamic routes (see https://developers.cloudflare.com/ai-gateway/features/dynamic-routing/)
    and set ``id`` to ``dynamic/<route-name>``.

    Attributes:
        id (str): Gateway ``model`` id (same role as ``OpenRouter.id``). For Workers AI you may paste the
            catalog binding (e.g. ``@cf/google/gemma-4-26b-a4b-it``); it is normalized to
            ``workers-ai/@cf/...``. Defaults to ``DEFAULT_GATEWAY_MODEL``.
        models (Optional[List[str]]): Same name as OpenRouter for a familiar API. **Not sent** to the
            gateway (compat API has no OpenRouter-style multi-model body). Leave ``None``. If set, a
            one-time warning is logged.
        name (str): The model class name. Defaults to ``Cloudflare``.
        provider (str): The provider label. Defaults to ``Cloudflare``.
        api_key (Optional[str]): Cloudflare API token with AI Gateway access. Reads ``CLOUDFLARE_API_TOKEN``.
        account_id (Optional[str]): Cloudflare account id for the gateway URL. Reads ``CLOUDFLARE_ACCOUNT_ID``.
        gateway_id (Optional[str]): AI Gateway id, or ``default`` for the auto-created gateway.
            Reads ``CLOUDFLARE_AI_GATEWAY_ID`` when unset.
        base_url (Optional[str]): Full OpenAI client base URL (``.../compat``). When set, ``account_id`` and
            ``gateway_id`` are not used to build the URL.
        max_tokens (Optional[int]): Maximum tokens for completions. Defaults to None (omitted from request).
    """

    id: str = DEFAULT_GATEWAY_MODEL
    name: str = "Cloudflare"
    provider: str = "Cloudflare"

    api_key: Optional[str] = None
    account_id: Optional[str] = None
    gateway_id: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: Optional[int] = None
    models: Optional[List[str]] = None

    _models_field_warned: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.id = normalize_cloudflare_gateway_model_id(self.id)

    def _get_client_params(self) -> Dict[str, Any]:
        # OpenAILike defaults api_key to "not-provided"; treat as unset so we load CLOUDFLARE_API_TOKEN.
        if not self.api_key or self.api_key == "not-provided":
            self.api_key = getenv("CLOUDFLARE_API_TOKEN")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message=(
                        "CLOUDFLARE_API_TOKEN not set. Please set the CLOUDFLARE_API_TOKEN environment variable "
                        "with a Cloudflare API token that can access AI Gateway."
                    ),
                    model_name=self.name,
                )

        if self.base_url is None:
            account = self.account_id or getenv("CLOUDFLARE_ACCOUNT_ID")
            if not account:
                raise ModelProviderError(
                    message=(
                        "CLOUDFLARE_ACCOUNT_ID not set. Set it (or pass account_id=...) to build the AI Gateway "
                        "base URL, or pass base_url=... explicitly."
                    ),
                    model_name=self.name,
                    model_id=self.id,
                )
            gateway = self.gateway_id or getenv("CLOUDFLARE_AI_GATEWAY_ID") or "default"
            self.base_url = f"https://gateway.ai.cloudflare.com/v1/{account}/{gateway}/compat"

        return super()._get_client_params()

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
    ) -> Dict[str, Any]:
        if self.models and not self._models_field_warned:
            log_warning(
                "Cloudflare AI Gateway compat uses a single `model` per request (the `id` field). "
                "The `models` list is not forwarded to the gateway (unlike OpenRouter). "
                "Use Dynamic Routes in the Cloudflare dashboard and set id='dynamic/<route>' for fallbacks."
            )
            self._models_field_warned = True

        return super().get_request_params(
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        )
