from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

from agno.aws.api_client import AwsApiClient  # type: ignore
from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ProviderResponse
from agno.utils.log import logger

try:
    from boto3 import session  # noqa: F401
except ImportError:
    logger.error("`boto3` not installed. Please install it via `pip install boto3`.")
    raise


@dataclass
class AwsBedrock(Model, ABC):
    """
    AWS Bedrock model.

    Args:
        aws_region (Optional[str]): The AWS region to use.
        aws_profile (Optional[str]): The AWS profile to use.
        aws_client (Optional[AwsApiClient]): The AWS client to use.
    """

    aws_region: Optional[str] = None
    aws_profile: Optional[str] = None
    aws_client: Optional[AwsApiClient] = None

    _bedrock_runtime_client: Optional[Any] = None

    def _get_aws_region(self) -> Optional[str]:
        # Priority 1: Use aws_region from model
        if self.aws_region is not None:
            return self.aws_region

        # Priority 2: Get aws_region from env
        from os import getenv

        from agno.constants import AWS_REGION_ENV_VAR

        aws_region_env = getenv(AWS_REGION_ENV_VAR)
        if aws_region_env is not None:
            self.aws_region = aws_region_env
        return self.aws_region

    def _get_aws_profile(self) -> Optional[str]:
        # Priority 1: Use aws_region from resource
        if self.aws_profile is not None:
            return self.aws_profile

        # Priority 2: Get aws_profile from env
        from os import getenv

        from agno.constants import AWS_PROFILE_ENV_VAR

        aws_profile_env = getenv(AWS_PROFILE_ENV_VAR)
        if aws_profile_env is not None:
            self.aws_profile = aws_profile_env
        return self.aws_profile

    def _get_aws_client(self) -> AwsApiClient:
        if self.aws_client is not None:
            return self.aws_client

        self.aws_client = AwsApiClient(aws_region=self._get_aws_region(), aws_profile=self._get_aws_profile())
        return self.aws_client

    def get_client(self):
        if self._bedrock_runtime_client is not None:
            return self._bedrock_runtime_client

        boto3_session: session = self._get_aws_client().boto3_session
        self._bedrock_runtime_client = boto3_session.client(service_name="bedrock-runtime")
        return self._bedrock_runtime_client

    def invoke(self, messages: List[Message]) -> Dict[str, Any]:
        """
        Invoke the Bedrock API.

        Args:
            messages (List[Message]): The messages to include in the request.

        Returns:
            Dict[str, Any]: The response from the Bedrock API.
        """
        body = self.format_messages(messages)
        try:
            return self.get_client().converse(**body)
        except Exception as e:
            logger.error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e

    def invoke_stream(self, messages: List[Message]) -> Iterator[Dict[str, Any]]:
        """
        Invoke the Bedrock API with streaming.

        Args:
            messages (List[Message]): The messages to include in the request.

        Returns:
            Iterator[Dict[str, Any]]: The streamed response.
        """
        body = self.format_messages(messages)
        try:
            response = self.get_client().converse_stream(**body)
            stream = response.get("stream")
            if stream:
                for event in stream:
                    yield event
        except Exception as e:
            logger.error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e

    @abstractmethod
    def format_messages(self, messages: List[Message]) -> Dict[str, Any]:
        raise NotImplementedError("Please use a subclass of AwsBedrock")

    @abstractmethod
    def parse_provider_response(self, response: Dict[str, Any]) -> ProviderResponse:
        raise NotImplementedError("Please use a subclass of AwsBedrock")

    async def ainvoke(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    async def ainvoke_stream(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f"Async not supported on {self.name}.")

    def parse_provider_response_delta(
        self, response: Any
    ) -> Iterator[ProviderResponse]:
        pass
