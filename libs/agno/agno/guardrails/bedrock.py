"""
AWS Bedrock Guardrail for Agno agents.

Uses the Amazon Bedrock ApplyGuardrail API to check agent input and output
against configurable content policies (hate, violence, PII, denied topics, etc.).

Requirements:
    ``pip install boto3`` (or use ``agno[aws-bedrock]``)

Setup:
    1. Create a guardrail in AWS Console > Bedrock > Guardrails
    2. Configure content filters, denied topics, PII policies, etc.
    3. Note the guardrail ID and version

Authentication:
    AWS credentials are resolved by boto3 in this order:
    1. Explicit ``aws_access_key_id`` / ``aws_secret_access_key`` params
    2. Environment variables (``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``)
    3. AWS credentials file (~/.aws/credentials)
    4. IAM role (EC2, Lambda, ECS)

Usage:
    from agno.guardrails import BedrockGuardrail

    # Check input before agent processes it
    agent = Agent(
        tools=[...],
        pre_hooks=[BedrockGuardrail(guardrail_id="abc123")],
    )

    # Check output after agent generates it
    agent = Agent(
        tools=[...],
        post_hooks=[BedrockGuardrail(guardrail_id="abc123", source="OUTPUT")],
    )

    # Both input and output
    agent = Agent(
        tools=[...],
        pre_hooks=[BedrockGuardrail(guardrail_id="abc123", source="INPUT")],
        post_hooks=[BedrockGuardrail(guardrail_id="abc123", source="OUTPUT")],
    )
"""

from os import getenv
from typing import Any, Dict, List, Literal, Optional, Union

from agno.exceptions import CheckTrigger, InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput
from agno.utils.log import log_debug, logger


class BedrockGuardrail(BaseGuardrail):
    """Guardrail that uses AWS Bedrock ApplyGuardrail API for content filtering.

    Supports checking both input (pre_hook) and output (post_hook) content
    against AWS Bedrock guardrail policies including content filters, denied
    topics, word filters, PII detection, and contextual grounding.

    Args:
        guardrail_id: The Bedrock guardrail identifier (from AWS Console).
        guardrail_version: The guardrail version. Use "DRAFT" for testing or a
            numeric version like "1" for production. Default "DRAFT".
        source: Whether this guardrail checks "INPUT" or "OUTPUT" content.
            Use "INPUT" for pre_hooks, "OUTPUT" for post_hooks. Default "INPUT".
        region: AWS region. Falls back to AWS_DEFAULT_REGION env var.
        aws_access_key_id: Explicit AWS access key. Falls back to env/IAM.
        aws_secret_access_key: Explicit AWS secret key. Falls back to env/IAM.
        aws_session_token: Explicit session token for temporary credentials.
        timeout: Timeout in seconds for the API call. Default 10.
        fail_closed: If True, block the request when the Bedrock API call fails
            (timeout, network error, service unavailable). Default False (fail-open).
            Set to True for compliance-critical scenarios.
    """

    def __init__(
        self,
        guardrail_id: str,
        guardrail_version: str = "DRAFT",
        source: Literal["INPUT", "OUTPUT"] = "INPUT",
        region: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        timeout: int = 10,
        fail_closed: bool = False,
    ):
        self.guardrail_id = guardrail_id
        self.guardrail_version = guardrail_version
        self.source = source
        self.region = region or getenv("AWS_DEFAULT_REGION", "us-east-1")
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_session_token = aws_session_token
        self.timeout = timeout
        self.fail_closed = fail_closed
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        """Get or create the Bedrock Runtime client."""
        if self._client is not None:
            return self._client

        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise ImportError(
                "`boto3` not installed. Please install using `pip install boto3` or `pip install agno[aws-bedrock]`."
            )

        client_kwargs: Dict[str, Any] = {
            "service_name": "bedrock-runtime",
            "region_name": self.region,
            "config": Config(read_timeout=self.timeout, connect_timeout=self.timeout),
        }
        if self.aws_access_key_id and self.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = self.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = self.aws_secret_access_key
            if self.aws_session_token:
                client_kwargs["aws_session_token"] = self.aws_session_token

        self._client = boto3.client(**client_kwargs)
        return self._client

    def _apply_guardrail(self, content: str) -> Dict[str, Any]:
        """Call the Bedrock ApplyGuardrail API."""
        client = self._get_client()
        log_debug(f"Applying Bedrock guardrail {self.guardrail_id} (source={self.source})")

        response = client.apply_guardrail(
            guardrailIdentifier=self.guardrail_id,
            guardrailVersion=self.guardrail_version,
            source=self.source,
            content=[{"text": {"text": content}}],
        )
        return response

    def _extract_violations(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract violation details from the Bedrock response."""
        violations: List[Dict[str, Any]] = []
        for assessment in response.get("assessments", []):
            for policy_type, policy_data in assessment.items():
                if isinstance(policy_data, dict):
                    for filter_item in policy_data.get("filters", []):
                        if filter_item.get("action") == "BLOCKED":
                            violations.append({"policy": policy_type, **filter_item})
                    for topic in policy_data.get("topics", []):
                        if topic.get("action") == "BLOCKED":
                            violations.append({"policy": policy_type, **topic})
                elif isinstance(policy_data, list):
                    for item in policy_data:
                        if isinstance(item, dict) and item.get("action") == "BLOCKED":
                            violations.append({"policy": policy_type, **item})
        return violations

    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check content against the Bedrock guardrail.

        Sends the input text to the AWS Bedrock ApplyGuardrail API. If the content
        violates any configured policy, raises InputCheckError (for INPUT source)
        or OutputCheckError (for OUTPUT source) with violation details.

        If the API call fails and fail_closed is False (default), logs a warning
        and allows the request. If fail_closed is True, raises InputCheckError.

        Args:
            run_input: The agent or team run input to check.
        """
        content = run_input.input_content_string()
        if not content:
            return

        try:
            response = self._apply_guardrail(content)
        except ImportError:
            raise
        except Exception as e:
            if self.fail_closed:
                raise InputCheckError(
                    f"Bedrock guardrail unavailable and fail_closed is enabled: {e}",
                    check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
                    additional_data={"guardrail_id": self.guardrail_id, "error": str(e)},
                )
            logger.warning(f"BedrockGuardrail: API call failed: {e}")
            return

        action = response.get("action", "")
        if action == "GUARDRAIL_INTERVENED":
            violations = self._extract_violations(response)
            output_text = ""
            for output in response.get("outputs", []):
                output_text = output.get("text", "")
                break

            additional_data = {
                "guardrail_id": self.guardrail_id,
                "source": self.source,
                "violations": violations,
                "guardrail_response": output_text,
            }

            if self.source == "OUTPUT":
                raise OutputCheckError(
                    output_text or "Content blocked by AWS Bedrock guardrail.",
                    check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
                    additional_data=additional_data,
                )
            else:
                raise InputCheckError(
                    output_text or "Content blocked by AWS Bedrock guardrail.",
                    check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
                    additional_data=additional_data,
                )

    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Async version of check().

        Delegates to the sync check() since boto3 does not support async natively.
        For true async, aioboto3 support can be added in a future version.

        Args:
            run_input: The agent or team run input to check.
        """
        self.check(run_input)
