from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.banavo.models.anthropic.claude import Claude as AnthropicClaude

try:
    from anthropic import AnthropicBedrock, AsyncAnthropicBedrock
except ImportError as e:
    raise ImportError(
        "`anthropic[bedrock]` not installed. Please install using `pip install anthropic[bedrock]`"
    ) from e

try:
    from boto3.session import Session
except ImportError as e:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`") from e


@dataclass
class Claude(AnthropicClaude):
    """
    AWS Bedrock Claude model.

    For more information, see: https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic.html
    """

    id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    name: str = "AwsBedrockAnthropicClaude"
    provider: str = "AwsBedrock"

    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    aws_region: Optional[str] = None
    session: Optional[Session] = None
    client_params: Optional[Dict[str, Any]] = None

    client: Optional[AnthropicBedrock] = None  # type: ignore
    async_client: Optional[AsyncAnthropicBedrock] = None  # type: ignore

    def get_client(self) -> AnthropicBedrock:
        """Get AWS Bedrock client with credential management."""
        if self.client is not None and not self.client.is_closed():
            return self.client

        if self.session:
            creds = self.session.get_credentials()
            params = {
                "aws_access_key": creds.access_key,
                "aws_secret_key": creds.secret_key,
                "aws_session_token": creds.token,
                "aws_region": self.session.region_name,
            }
        else:
            params = {
                "aws_access_key": self.aws_access_key or getenv("AWS_ACCESS_KEY"),
                "aws_secret_key": self.aws_secret_key or getenv("AWS_SECRET_KEY"),
                "aws_region": self.aws_region or getenv("AWS_REGION"),
            }

        if self.client_params:
            params.update(self.client_params)

        self.client = AnthropicBedrock(**params)  # type: ignore
        return self.client

    def get_async_client(self) -> AsyncAnthropicBedrock:
        """Get async AWS Bedrock client with credential management."""
        if self.async_client is not None:
            return self.async_client

        if self.session:
            creds = self.session.get_credentials()
            params = {
                "aws_access_key": creds.access_key,
                "aws_secret_key": creds.secret_key,
                "aws_session_token": creds.token,
                "aws_region": self.session.region_name,
            }
        else:
            params = {
                "aws_access_key": self.aws_access_key,
                "aws_secret_key": self.aws_secret_key,
                "aws_region": self.aws_region,
            }

        if self.client_params:
            params.update(self.client_params)

        self.async_client = AsyncAnthropicBedrock(**params)  # type: ignore
        return self.async_client
