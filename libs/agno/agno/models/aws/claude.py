from dataclasses import dataclass
from os import getenv
from typing import Optional

import httpx

from agno.models.anthropic import Claude as AnthropicClaude
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_warning

try:
    from anthropic import AnthropicBedrock, AsyncAnthropicBedrock
except ImportError:
    raise ImportError("`anthropic[bedrock]` not installed. Please install using `pip install anthropic[bedrock]`")

try:
    from boto3.session import Session
except ImportError:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`")


@dataclass
class Claude(AnthropicClaude):
    """
    AWS Bedrock Claude model.

    For more information, see: https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic.html
    """

    id: str = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    name: str = "AwsBedrockAnthropicClaude"
    provider: str = "AwsBedrock"

    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    aws_region: Optional[str] = None
    api_key: Optional[str] = None
    session: Optional[Session] = None

    client: Optional[AnthropicBedrock] = None  # type: ignore
    async_client: Optional[AsyncAnthropicBedrock] = None  # type: ignore

    def _build_client_params(self) -> Dict[str, Any]:
        if self.session:
            credentials = self.session.get_credentials()
            client_params: Dict[str, Any] = {
                "aws_access_key": credentials.access_key,
                "aws_secret_key": credentials.secret_key,
                "aws_session_token": credentials.token,
                "aws_region": self.session.region_name,
            }
        else:
            self.api_key = self.api_key or getenv("AWS_BEDROCK_API_KEY")
            if self.api_key:
                self.aws_region = self.aws_region or getenv("AWS_REGION")
                client_params = {
                    "api_key": self.api_key,
                }
                if self.aws_region:
                    client_params["aws_region"] = self.aws_region
            else:
                self.aws_access_key = self.aws_access_key or getenv("AWS_ACCESS_KEY")
                self.aws_secret_key = self.aws_secret_key or getenv("AWS_SECRET_KEY")
                self.aws_region = self.aws_region or getenv("AWS_REGION")

                client_params = {
                    "aws_secret_key": self.aws_secret_key,
                    "aws_access_key": self.aws_access_key,
                    "aws_region": self.aws_region,
                }

        if self.timeout is not None:
            client_params["timeout"] = self.timeout

        if self.client_params:
            client_params.update(self.client_params)

        return client_params

    def get_client(self):
        """
        Get the Bedrock client.

        Returns:
            AnthropicBedrock: The Bedrock client.
        """
        if self.client is not None and not self.client.is_closed():
            return self.client

        client_params = self._build_client_params()

        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Using default global httpx.Client.")
                # Use global sync client when user http_client is invalid
                client_params["http_client"] = get_default_sync_client()
        else:
            # Use global sync client when no custom http_client is provided
            client_params["http_client"] = get_default_sync_client()

        self.client = AnthropicBedrock(
            **client_params,  # type: ignore
        )
        return self.client

    def get_async_client(self):
        """
        Get the Bedrock async client.

        Returns:
            AsyncAnthropicBedrock: The Bedrock async client.
        """
        if self.async_client is not None:
            return self.async_client

        client_params = self._build_client_params()

        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                client_params["http_client"] = self.http_client
            else:
                log_warning(
                    "http_client is not an instance of httpx.AsyncClient. Using default global httpx.AsyncClient."
                )
                # Use global async client when user http_client is invalid
                client_params["http_client"] = get_default_async_client()
        else:
            # Use global async client when no custom http_client is provided
            client_params["http_client"] = get_default_async_client()

        self.async_client = AsyncAnthropicBedrock(
            **client_params,  # type: ignore
        )
        return self.async_client
