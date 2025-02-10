from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from git import List

from agno.models.anthropic import Claude as AnthropicClaude
from agno.utils.log import logger

try:
    from anthropic import AnthropicBedrock, AsyncAnthropicBedrock
except ImportError:
    logger.error("`anthropic[bedrock]` not installed. Please install it via `pip install anthropic[bedrock]`.")
    raise


@dataclass
class Claude(AnthropicClaude):
    """
    AWS Bedrock Claude model.

    Args:
        aws_region (Optional[str]): The AWS region to use.
        aws_access_key (Optional[str]): The AWS access key to use.
        aws_secret_key (Optional[str]): The AWS secret key to use.
    """

    id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    name: str = "AwsBedrockAnthropicClaude"
    provider: str = "AwsBedrock"

    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    aws_region: Optional[str] = None

    # -*- Request parameters
    max_tokens: int = 4096
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[List[str]] = None

    # -*- Request parameters
    request_params: Optional[Dict[str, Any]] = None
    # -*- Client parameters
    client_params: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = super().to_dict()
        _dict["max_tokens"] = self.max_tokens
        _dict["temperature"] = self.temperature
        _dict["top_p"] = self.top_p
        _dict["top_k"] = self.top_k
        _dict["stop_sequences"] = self.stop_sequences
        return _dict

    _client: Optional[AnthropicBedrock] = None
    _async_client: Optional[AsyncAnthropicBedrock] = None

    def get_client(self):
        if self._client is not None:
            return self._client

        self.aws_access_key = self.aws_access_key or getenv("AWS_ACCESS_KEY")
        self.aws_secret_key = self.aws_secret_key or getenv("AWS_SECRET_KEY")
        self.aws_region = self.aws_region or getenv("AWS_REGION")

        self._client = AnthropicBedrock(
            aws_secret_key=self.aws_secret_key,
            aws_access_key=self.aws_access_key,
            aws_region=self.aws_region,
        )
        return self._client

    def get_async_client(self):
        if self._async_client is not None:
            return self._async_client

        self._async_client = AsyncAnthropicBedrock(
            aws_secret_key=self.aws_secret_key,
            aws_access_key=self.aws_access_key,
            aws_region=self.aws_region,
        )
        return self._async_client

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Generate keyword arguments for API requests.
        """
        _request_params: Dict[str, Any] = {}
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.stop_sequences:
            _request_params["stop_sequences"] = self.stop_sequences
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.top_k:
            _request_params["top_k"] = self.top_k
        if self.request_params:
            _request_params.update(self.request_params)
        return _request_params
