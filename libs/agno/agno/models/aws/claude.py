from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

import httpx

from agno.models.anthropic import Claude as AnthropicClaude
from agno.utils.log import log_warning
from agno.utils.models.claude import supports_bedrock_structured_outputs

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
    aws_session_token: Optional[str] = None
    aws_region: Optional[str] = None
    api_key: Optional[str] = None
    session: Optional[Session] = None

    client: Optional[AnthropicBedrock] = None  # type: ignore
    async_client: Optional[AsyncAnthropicBedrock] = None  # type: ignore

    def _supports_structured_outputs(self) -> bool:
        return supports_bedrock_structured_outputs(self.id)

    def _get_client_params(self) -> Dict[str, Any]:
        if self.session:
            # Use get_frozen_credentials() for an atomic snapshot so that
            # a credential refresh between property reads cannot produce a
            # mismatched access-key / secret-key / token tuple.
            resolved = self.session.get_credentials()
            if resolved is None:
                raise ValueError(
                    "boto3 session has no credentials. Check your AWS configuration "
                    "(environment variables, config files, IAM role, etc.)."
                )
            credentials = resolved.get_frozen_credentials()
            client_params: Dict[str, Any] = {
                "aws_access_key": credentials.access_key,
                "aws_secret_key": credentials.secret_key,
                "aws_session_token": credentials.token,
                "aws_region": self.aws_region or self.session.region_name,
            }
        else:
            self.api_key = self.api_key or getenv("AWS_BEDROCK_API_KEY")
            if self.api_key:
                raise ValueError(
                    "AWS_BEDROCK_API_KEY authentication is not currently supported by AnthropicBedrock. "
                    "Use IAM credentials (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY[/AWS_SESSION_TOKEN]) "
                    "or provide a boto3 session instead."
                )

            self.aws_access_key = self.aws_access_key or getenv("AWS_ACCESS_KEY_ID") or getenv("AWS_ACCESS_KEY")
            self.aws_secret_key = self.aws_secret_key or getenv("AWS_SECRET_ACCESS_KEY") or getenv("AWS_SECRET_KEY")
            self.aws_session_token = self.aws_session_token or getenv("AWS_SESSION_TOKEN")
            self.aws_region = self.aws_region or getenv("AWS_REGION")

            client_params = {
                "aws_secret_key": self.aws_secret_key,
                "aws_access_key": self.aws_access_key,
                "aws_session_token": self.aws_session_token,
                "aws_region": self.aws_region,
            }

            if not (self.aws_access_key and self.aws_secret_key):
                log_warning(
                    "AWS credentials not found. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables or provide a boto3 session."
                )

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
        # When using a boto3 session, always recreate the client so
        # session.get_credentials() can return rotated credentials
        # (IAM roles, EKS pod identity, instance profiles, STS).
        if not self.session and self.client is not None and not self.client.is_closed():
            return self.client

        client_params = self._get_client_params()

        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Ignoring and using SDK default.")
        # When no custom http_client is provided, let the SDK use its own default client.
        # Each model instance gets its own connection, preventing HTTP/2 stream saturation
        # when multiple models (main agent, MemoryManager, etc.) run concurrently.

        # Close the previous client before creating a new one to avoid leaking
        # connection pools when session-based credential refresh forces recreation.
        if self.session and self.client is not None and not self.client.is_closed():
            self.client.close()

        # Use a local variable so concurrent callers on the same model
        # instance cannot overwrite each other's client via self.client.
        client = AnthropicBedrock(
            **client_params,  # type: ignore
        )
        if not self.session:
            self.client = client
        return client

    def get_async_client(self):
        """
        Get the Bedrock async client.

        Returns:
            AsyncAnthropicBedrock: The Bedrock async client.
        """
        # When using a boto3 session, always recreate the client so
        # session.get_credentials() can return rotated credentials.
        if not self.session and self.async_client is not None and not self.async_client.is_closed():
            return self.async_client

        client_params = self._get_client_params()

        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.AsyncClient. Ignoring and using SDK default.")
        # When no custom http_client is provided, let the SDK use its own default client.
        # Each model instance gets its own connection, preventing HTTP/2 stream saturation
        # when multiple models (main agent, MemoryManager, etc.) run concurrently.

        # Close the previous client before creating a new one to avoid leaking
        # connection pools when session-based credential refresh forces recreation.
        if self.session and self.async_client is not None and not self.async_client.is_closed():
            self.async_client.close()

        # Use a local variable so concurrent callers on the same model
        # instance cannot overwrite each other's client via self.async_client.
        async_client = AsyncAnthropicBedrock(
            **client_params,  # type: ignore
        )
        if not self.session:
            self.async_client = async_client
        return async_client
