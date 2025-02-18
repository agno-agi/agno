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

    client: Optional[AnthropicBedrock] = None  # type: ignore
    async_client: Optional[AsyncAnthropicBedrock] = None  # type: ignore

    def get_client(self):
        if self.client is not None:
            return self.client

        self.aws_access_key = self.aws_access_key or getenv("AWS_ACCESS_KEY")
        self.aws_secret_key = self.aws_secret_key or getenv("AWS_SECRET_KEY")
        self.aws_region = self.aws_region or getenv("AWS_REGION")

        client_params = {
            "aws_secret_key": self.aws_secret_key,
            "aws_access_key": self.aws_access_key,
            "aws_region": self.aws_region,
        }
        if self.client_params:
            client_params.update(self.client_params)

        self.client = AnthropicBedrock(
            **client_params,  # type: ignore
        )
        return self.client

    def get_async_client(self):
        if self.async_client is not None:
            return self.async_client

        client_params = {
            "aws_secret_key": self.aws_secret_key,
            "aws_access_key": self.aws_access_key,
            "aws_region": self.aws_region,
        }
        if self.client_params:
            client_params.update(self.client_params)

        self.async_client = AsyncAnthropicBedrock(
            **client_params,  # type: ignore
        )
        return self.async_client

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
