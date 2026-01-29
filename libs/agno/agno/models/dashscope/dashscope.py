from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class DashScope(OpenAILike):
    """
    A class for interacting with Qwen models via DashScope API or local vLLM/Ollama deployments.

    Optimizations based on Qwen-Agent (https://github.com/QwenLM/Qwen-Agent):
    - Parallel function calls with optimized templates
    - Reasoning content separation (Qwen2.5+, QvQ models)
    - Auto-configuration per model variant (Qwen3, Qwen3-VL, Qwen3-Coder, QvQ)
    - vLLM native tool parsing support
    - Long context optimization (up to 1M tokens)

    Attributes:
        id (str): The model id. Defaults to "qwen-plus".
        name (str): The model name. Defaults to "Qwen".
        provider (str): The provider name. Defaults to "Dashscope".
        api_key (Optional[str]): The DashScope API key or local server key.
        base_url (str): The base URL. Defaults to DashScope official endpoint.

        # Thinking/Reasoning parameters
        enable_thinking (bool): Enable thinking process (QvQ models). Defaults to False.
        include_thoughts (Optional[bool]): Include thinking in response (alternative). Defaults to None.
        thinking_budget (Optional[int]): Control thinking depth. Defaults to None.
        use_reasoning_content (bool): Use reasoning_content field (Qwen2.5+). Defaults to True.

        # Function calling optimization
        fncall_prompt_type (str): Function call template type ('qwen', 'nous', 'glm4'). Auto-detected.
        max_parallel_calls (int): Max parallel function calls. Defaults to 5.

        # vLLM native parsing
        use_vllm_native_parsing (bool): Use vLLM native tool parsing. Defaults to False.

        # Long context
        max_input_tokens (Optional[int]): Max input tokens limit. Auto-configured per model.

        # Auto-configuration
        auto_configure (bool): Auto-detect model variant and apply best settings. Defaults to True.
    """

    id: str = "qwen-plus"
    name: str = "Qwen"
    provider: str = "Dashscope"

    api_key: Optional[str] = getenv("DASHSCOPE_API_KEY") or getenv("QWEN_API_KEY")
    base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    # Thinking/Reasoning parameters
    enable_thinking: bool = False
    include_thoughts: Optional[bool] = None
    thinking_budget: Optional[int] = None
    use_reasoning_content: bool = True  # NEW: Qwen2.5+ reasoning content field

    # Function calling optimization (NEW)
    fncall_prompt_type: str = "qwen"  # 'qwen', 'nous', 'glm4'
    max_parallel_calls: int = 5  # Parallel function calls limit

    # vLLM native parsing (NEW)
    use_vllm_native_parsing: bool = False  # Enable vLLM native tool parsing

    # Long context optimization (NEW)
    max_input_tokens: Optional[int] = None  # Auto-configured per model

    # Auto-configuration (NEW)
    auto_configure: bool = True  # Auto-detect model variant

    # Internal state
    _model_variant: Optional[str] = None  # 'qwen3', 'qwen3-vl', 'qwen3-coder', 'qvq'

    # DashScope supports structured outputs
    supports_native_structured_outputs: bool = True
    supports_json_schema_outputs: bool = True

    def __post_init__(self):
        """Initialize and auto-configure model based on variant."""
        super().__post_init__()
        if self.auto_configure:
            self._auto_configure_model()

    def _auto_configure_model(self):
        """
        Auto-detect model variant and apply optimal configurations.

        Based on Qwen-Agent best practices:
        - QvQ/QwQ: reasoning models, enable thinking
        - Qwen3-VL: vision models
        - Qwen3-Coder: code models, use 'nous' template
        - Qwen3: general models, use 'nous' template
        """
        model_lower = self.id.lower()

        # Detect QvQ/QwQ reasoning models
        if "qvq" in model_lower or "qwq" in model_lower:
            self._model_variant = "qvq"
            self.enable_thinking = True
            self.use_reasoning_content = True
            self.fncall_prompt_type = "qwen"

        # Detect vision models
        elif "vl" in model_lower or "vision" in model_lower:
            self._model_variant = "qwen3-vl"
            self.fncall_prompt_type = "qwen"

        # Detect coder models
        elif "coder" in model_lower or "code" in model_lower:
            self._model_variant = "qwen3-coder"
            self.fncall_prompt_type = "nous"
            # vLLM native parsing is optimal for coder models
            if self._is_local_deployment():
                self.use_vllm_native_parsing = True

        # Detect Qwen3 models
        elif "qwen3" in model_lower or "qwen-3" in model_lower:
            self._model_variant = "qwen3"
            self.fncall_prompt_type = "nous"

        # Detect Qwen2.5 models
        elif "qwen2.5" in model_lower or "qwen-2.5" in model_lower:
            self._model_variant = "qwen2.5"
            self.use_reasoning_content = True

        # Configure max input tokens based on model tier
        if self.max_input_tokens is None:
            if "max" in model_lower:
                self.max_input_tokens = 128000
            elif "turbo" in model_lower or "long" in model_lower:
                self.max_input_tokens = 1000000  # 1M context
            elif "plus" in model_lower:
                self.max_input_tokens = 32768

    def _is_local_deployment(self) -> bool:
        """Check if using local deployment (vLLM/Ollama/LM Studio)."""
        return (
            "localhost" in self.base_url
            or "127.0.0.1" in self.base_url
            or "0.0.0.0" in self.base_url
            or ":8000" in self.base_url  # vLLM default
            or ":11434" in self.base_url  # Ollama default
            or ":1234" in self.base_url  # LM Studio default
        )

    def _get_client_params(self) -> Dict[str, Any]:
        # Allow empty API key for local deployments
        if not self.api_key and not self._is_local_deployment():
            self.api_key = getenv("DASHSCOPE_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="DASHSCOPE_API_KEY not set. Please set the DASHSCOPE_API_KEY environment variable.",
                    model_name=self.name,
                )

        # Define base client params
        base_params = {
            "api_key": self.api_key or "EMPTY",  # vLLM accepts "EMPTY" for local
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Get request parameters with Qwen-specific optimizations.

        Enhancements:
        - Parallel function calls support
        - Reasoning content field (Qwen2.5+)
        - Function call template optimization
        - vLLM native parsing integration
        - Max input tokens enforcement
        """
        params = super().get_request_params(response_format=response_format, tools=tools, tool_choice=tool_choice)

        # Initialize extra_body if not present
        if "extra_body" not in params:
            params["extra_body"] = {}

        # === THINKING/REASONING PARAMETERS ===
        if self.include_thoughts is not None:
            self.enable_thinking = self.include_thoughts

        if self.enable_thinking:
            params["extra_body"]["enable_thinking"] = True

            if self.thinking_budget is not None:
                params["extra_body"]["thinking_budget"] = self.thinking_budget

        # === REASONING CONTENT (Qwen2.5+, QvQ) ===
        if self.use_reasoning_content and self._model_variant in ["qwen2.5", "qwen3", "qvq"]:
            params["extra_body"]["reasoning_content"] = True

        # === FUNCTION CALLING OPTIMIZATION ===
        if tools:
            # Set function call template type
            if self.fncall_prompt_type != "qwen":  # Only if non-default
                params["extra_body"]["fncall_prompt_type"] = self.fncall_prompt_type

            # Enable parallel function calls
            if self.max_parallel_calls > 1:
                params["extra_body"]["max_parallel_calls"] = self.max_parallel_calls

            # vLLM native tool parsing (for local deployments)
            if self.use_vllm_native_parsing and self._is_local_deployment():
                params["extra_body"]["use_raw_api"] = True
                # vLLM expects "guided_json" for structured outputs
                if self._model_variant == "qwen3-coder":
                    params["extra_body"]["guided_decoding_backend"] = "outlines"

        # === MAX INPUT TOKENS ===
        if self.max_input_tokens:
            # Ensure we don't exceed model limits
            if "max_tokens" in params:
                params["max_tokens"] = min(params["max_tokens"], self.max_input_tokens)

        # Clean up empty extra_body
        if not params["extra_body"]:
            del params["extra_body"]

        return params
