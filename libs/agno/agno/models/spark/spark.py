from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class Spark(OpenAILike):
    """
    A class for interacting with iFLYTEK Spark (讯飞星火) models.

    Spark exposes an OpenAI-compatible HTTP endpoint at
    https://spark-api-open.xf-yun.com/v1 that authenticates with a single Bearer
    API Password, so it is a thin wrapper over OpenAILike. The default id is
    ``4.0Ultra`` (Spark 4.0 Ultra); other public model ids include ``generalv3.5``
    (Spark Max), ``max-32k``, ``generalv3`` (Spark Pro), ``pro-128k`` and ``lite``.

    Attributes:
        id (str): The model id. Defaults to "4.0Ultra".
        name (str): The model name. Defaults to "Spark".
        provider (str): The provider name. Defaults to "iFLYTEK Spark".
        api_key (Optional[str]): The API Password for the Spark HTTP service.
        base_url (str): The base URL. Defaults to "https://spark-api-open.xf-yun.com/v1".
    """

    id: str = "4.0Ultra"
    name: str = "Spark"
    provider: str = "iFLYTEK Spark"

    api_key: Optional[str] = field(default_factory=lambda: getenv("SPARK_API_KEY"))
    base_url: str = "https://spark-api-open.xf-yun.com/v1"

    # Spark supports JSON mode (response_format={"type": "json_object"}) but not
    # native/json_schema structured outputs, so output_schema needs use_json_mode=True.
    supports_native_structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("SPARK_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="SPARK_API_KEY not set. Please set the SPARK_API_KEY environment variable.",
                    model_name=self.name,
                )

        # Define base client params
        base_params = {
            "api_key": self.api_key,
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
