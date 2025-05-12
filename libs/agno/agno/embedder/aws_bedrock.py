import json
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from agno.embedder.base import Embedder
from agno.exceptions import AgnoError, ModelProviderError
from agno.utils.log import log_error, logger

try:
    from boto3 import client as AwsClient
    from boto3.session import Session
    from botocore.exceptions import ClientError
except ImportError:
    log_error("`boto3` not installed. Please install it via `pip install boto3`.")
    raise


@dataclass
class AwsBedrockEmbedder(Embedder):
    """
    AWS Bedrock embedder.

    To use this embedder, you need to either:
    1. Set the following environment variables:
       - AWS_ACCESS_KEY_ID
       - AWS_SECRET_ACCESS_KEY
       - AWS_REGION
    2. Or provide a boto3 Session object

    Args:
        id (str): The model ID to use. Default is 'cohere.embed-multilingual-v3'.
        dimensions (Optional[int]): The dimensions of the embeddings. Default is 1024.
        input_type (str): Prepends special tokens to differentiate types. Options:
            'search_document', 'search_query', 'classification', 'clustering'. Default is 'search_query'.
        truncate (Optional[str]): How to handle inputs longer than the maximum token length.
            Options: 'NONE', 'START', 'END'. Default is 'NONE'.
        embedding_types (Optional[List[str]]): Types of embeddings to return. Options:
            'float', 'int8', 'uint8', 'binary', 'ubinary'. Default is ['float'].
        aws_region (Optional[str]): The AWS region to use.
        aws_access_key_id (Optional[str]): The AWS access key ID to use.
        aws_secret_access_key (Optional[str]): The AWS secret access key to use.
        session (Optional[Session]): A boto3 Session object to use for authentication.
        request_params (Optional[Dict[str, Any]]): Additional parameters to pass to the API requests.
        client_params (Optional[Dict[str, Any]]): Additional parameters to pass to the boto3 client.
    """

    id: str = "cohere.embed-multilingual-v3"
    dimensions: int = 1024  # Cohere models have 1024 dimensions by default
    input_type: str = "search_query"
    truncate: Optional[str] = None  # 'NONE', 'START', or 'END'
    # 'float', 'int8', 'uint8', etc.
    embedding_types: Optional[List[str]] = None

    aws_region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    session: Optional[Session] = None

    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    client: Optional[AwsClient] = None

    def get_client(self) -> AwsClient:
        """
        Returns an AWS Bedrock client.

        Returns:
            AwsClient: An instance of the AWS Bedrock client.
        """
        if self.client is not None:
            return self.client

        if self.session:
            self.client = self.session.client("bedrock-runtime")
            return self.client

        self.aws_access_key_id = self.aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = self.aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = self.aws_region or getenv("AWS_REGION")

        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise AgnoError(
                message="AWS credentials not found. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables or provide a boto3 session.",
                status_code=400,
            )

        self.client = AwsClient(
            service_name="bedrock-runtime",
            region_name=self.aws_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            **(self.client_params or {}),
        )
        return self.client

    def _format_request_body(self, text: str) -> str:
        """
        Format the request body for the embedder.

        Args:
            text (str): The text to embed.

        Returns:
            str: The formatted request body as a JSON string.
        """
        request_body = {
            "texts": [text],
            "input_type": self.input_type,
        }

        if self.truncate:
            request_body["truncate"] = self.truncate

        if self.embedding_types:
            request_body["embedding_types"] = self.embedding_types

        # Add additional request parameters if provided
        if self.request_params:
            request_body.update(self.request_params)

        return json.dumps(request_body)

    def response(self, text: str) -> Dict[str, Any]:
        """
        Get embeddings from AWS Bedrock for the given text.

        Args:
            text (str): The text to embed.

        Returns:
            Dict[str, Any]: The response from the API.
        """
        try:
            body = self._format_request_body(text)
            response = self.get_client().invoke_model(
                modelId=self.id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            response_body = json.loads(response["body"].read().decode("utf-8"))
            return response_body
        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name="AwsBedrockEmbedder", model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name="AwsBedrockEmbedder", model_id=self.id) from e

    def get_embedding(self, text: str) -> List[float]:
        """
        Get embeddings for the given text.

        Args:
            text (str): The text to embed.

        Returns:
            List[float]: The embedding vector.
        """
        response = self.response(text=text)
        try:
            # Check if response contains embeddings or embeddings by type
            if "embeddings" in response:
                if isinstance(response["embeddings"], list):
                    # Default 'float' embeddings response format
                    return response["embeddings"][0]
                elif isinstance(response["embeddings"], dict):
                    # If embeddings_types parameter was used, select float embeddings
                    if "float" in response["embeddings"]:
                        return response["embeddings"]["float"][0]
                    # Fallback to the first available embedding type
                    for embedding_type in response["embeddings"]:
                        return response["embeddings"][embedding_type][0]
            logger.warning("No embeddings found in response")
            return []
        except Exception as e:
            logger.warning(f"Error extracting embeddings: {e}")
            return []

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        """
        Get embeddings and usage information for the given text.

        Args:
            text (str): The text to embed.

        Returns:
            Tuple[List[float], Optional[Dict[str, Any]]]: The embedding vector and usage information.
        """
        response = self.response(text=text)

        embedding: List[float] = []
        # Extract embeddings
        if "embeddings" in response:
            if isinstance(response["embeddings"], list):
                embedding = response["embeddings"][0]
            elif isinstance(response["embeddings"], dict):
                if "float" in response["embeddings"]:
                    embedding = response["embeddings"]["float"][0]
                # Fallback to the first available embedding type
                else:
                    for embedding_type in response["embeddings"]:
                        embedding = response["embeddings"][embedding_type][0]
                        break

        # Extract usage metrics if available
        usage = None
        if "usage" in response:
            usage = response["usage"]

        return embedding, usage
