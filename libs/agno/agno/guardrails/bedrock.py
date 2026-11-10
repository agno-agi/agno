from os import getenv
from typing import Any, Literal, Optional, Union

from agno.exceptions import CheckTrigger, InputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput
from agno.utils.log import log_debug, log_error

try:
    from boto3 import client as AwsClient
    from boto3.session import Session
except ImportError:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`")

try:
    import aioboto3

    AIOBOTO3_AVAILABLE = True
except ImportError:
    aioboto3 = None
    AIOBOTO3_AVAILABLE = False


class BedrockGuardrail(BaseGuardrail):
    """Guardrail definition for BedrockGuardrails.

    Args:
        guardrail_id (str): The unique identifier for the Bedrock guardrail.
        guardrail_version (str): The version of the guardrail to use.
    """

    def __init__(
        self,
        guardrail_id: str,
        guardrail_version: str,
        output_scope: Optional[Literal["INTERVENTIONS", "FULL"]] = "INTERVENTIONS",
        aws_sso_auth: bool = False,
        aws_region: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        session: Optional[Session] = None,
    ):
        """
        Initialize the BedrockGuardrail.

        Args:
            guardrail_id: The unique identifier for the Bedrock guardrail.
            guardrail_version: The version of the guardrail to use.
            aws_sso_auth: Whether to use AWS SSO for authentication (defaults to False).
            aws_region: AWS region to use for the client.
            aws_access_key_id: AWS access key id (optional if using session or env vars).
            aws_secret_access_key: AWS secret access key (optional if using session or env vars).
            session: Optional boto3 Session to use for creating sync clients.
        """
        self.guardrail_id = guardrail_id
        self.guardrail_version = guardrail_version
        self.output_scope = output_scope
        # Correctly typed and initialized AWS configuration
        self.aws_sso_auth: bool = aws_sso_auth
        self.aws_region: Optional[str] = aws_region
        self.aws_access_key_id: Optional[str] = aws_access_key_id
        self.aws_secret_access_key: Optional[str] = aws_secret_access_key
        self.session: Optional[Session] = session
        # Clients are created lazily by get_client / get_async_client
        self.client: Optional[AwsClient] = None
        self.async_client: Optional[Any] = None
        self.async_session: Optional[Any] = None

    def get_client(self) -> AwsClient:
        """
        Get the Bedrock client.

        Returns:
            AwsClient: The Bedrock client.
        """
        if self.client is not None:
            return self.client

        if self.session:
            self.client = self.session.client("bedrock-runtime")
            return self.client

        self.aws_access_key_id = self.aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = self.aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = self.aws_region or getenv("AWS_REGION")

        if self.aws_sso_auth:
            self.client = AwsClient(service_name="bedrock-runtime", region_name=self.aws_region)
        else:
            if not self.aws_access_key_id or not self.aws_secret_access_key:
                log_error(
                    "AWS credentials not found. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables or provide a boto3 session."
                )

            self.client = AwsClient(
                service_name="bedrock-runtime",
                region_name=self.aws_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            )
        return self.client

    def get_async_client(self):
        """
        Get the async Bedrock client context manager.

        Returns:
            The async Bedrock client context manager.
        """
        if not AIOBOTO3_AVAILABLE:
            raise ImportError(
                "`aioboto3` not installed. Please install using `pip install aioboto3` for async support."
            )

        if self.async_session is None:
            self.aws_access_key_id = self.aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
            self.aws_secret_access_key = self.aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
            self.aws_region = self.aws_region or getenv("AWS_REGION")

            self.async_session = aioboto3.Session()

        client_kwargs = {
            "service_name": "bedrock-runtime",
            "region_name": self.aws_region,
        }

        if self.aws_sso_auth:
            pass
        else:
            if not self.aws_access_key_id or not self.aws_secret_access_key:
                import os

                env_access_key = os.environ.get("AWS_ACCESS_KEY_ID")
                env_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
                env_region = os.environ.get("AWS_REGION")

                if env_access_key and env_secret_key:
                    self.aws_access_key_id = env_access_key
                    self.aws_secret_access_key = env_secret_key
                    if env_region:
                        self.aws_region = env_region
                        client_kwargs["region_name"] = self.aws_region

            if self.aws_access_key_id and self.aws_secret_access_key:
                client_kwargs.update(
                    {
                        "aws_access_key_id": self.aws_access_key_id,
                        "aws_secret_access_key": self.aws_secret_access_key,
                    }
                )

        return self.async_session.client(**client_kwargs)

    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check for content that violates your Guardrail policy."""

        content = run_input.input_content_string()

        log_debug(f"Moderating content using {self.guardrail_id} version {self.guardrail_version}")

        response = self.get_client().apply_guardrail(
            guardrailIdentifier=self.guardrail_id,
            guardrailVersion=self.guardrail_version,
            source="INPUT",
            content=[
                {
                    "text": {
                        "text": content,
                        "qualifiers": [
                            "query",
                        ],
                    }
                },
            ],
            outputScope=self.output_scope,
        )

        if getattr(response, "action", None) == "GUARDRAIL_INTERVENED" or (
            isinstance(response, dict) and response.get("action") == "GUARDRAIL_INTERVENED"
        ):
            raise InputCheckError(
                "Bedrock guardrail violation detected.",
                additional_data=response,
                check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
            )

    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check for content that violates your Guardrail policy."""

        content = run_input.input_content_string()

        log_debug(f"Moderating content using {self.guardrail_id} version {self.guardrail_version}")

        async with self.get_async_client() as client:
            response = await client.apply_guardrail(
                guardrailIdentifier=self.guardrail_id,
                guardrailVersion=self.guardrail_version,
                source="INPUT",
                content=[
                    {
                        "text": {
                            "text": content,
                            "qualifiers": [
                                "guard_content",
                            ],
                        }
                    },
                ],
                outputScope=self.output_scope,
            )

        if getattr(response, "action", None) == "GUARDRAIL_INTERVENED" or (
            isinstance(response, dict) and response.get("action") == "GUARDRAIL_INTERVENED"
        ):
            raise InputCheckError(
                "Bedrock guardrail violation detected.",
                additional_data=response,
                check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
            )
