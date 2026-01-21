import json
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Tuple

from agno.exceptions import AgnoError, ModelProviderError
from agno.knowledge.embedder.base import Embedder
from agno.utils.log import log_error, log_warning

try:
    from boto3 import client as AwsClient
    from boto3.session import Session
    from botocore.exceptions import ClientError
except ImportError:
    log_error("`boto3` not installed. Please install it via `pip install boto3`.")
    raise

try:
    import aioboto3
except ImportError:
    log_warning("`aioboto3` not installed. Async methods will not be available. Install via `pip install aioboto3`.")
    aioboto3 = None


# Type aliases for clarity
InputType = Literal["search_document", "search_query", "classification", "clustering"]
EmbeddingType = Literal["float", "int8", "uint8", "binary", "ubinary"]
TruncateV3 = Literal["NONE", "START", "END"]
TruncateV4 = Literal["NONE", "LEFT", "RIGHT"]
OutputDimension = Literal[256, 512, 1024, 1536]


@dataclass
class AwsBedrockEmbedder(Embedder):
    """
    AWS Bedrock embedder supporting Cohere Embed v3 and v4 models.

    To use this embedder, you need to either:
    1. Set the following environment variables:
       - AWS_ACCESS_KEY_ID
       - AWS_SECRET_ACCESS_KEY
       - AWS_REGION
    2. Or provide a boto3 Session object

    Args:
        id (str): The model ID to use. Default is 'cohere.embed-multilingual-v3'.
            - v3 models: 'cohere.embed-multilingual-v3', 'cohere.embed-english-v3'
            - v4 model: 'cohere.embed-v4:0'
        dimensions (Optional[int]): The dimensions of the embeddings.
            - v3: Fixed at 1024
            - v4: Configurable via output_dimension (256, 512, 1024, 1536). Default 1536.
        input_type (str): Prepends special tokens to differentiate types. Options:
            'search_document', 'search_query', 'classification', 'clustering'. Default is 'search_query'.
        truncate (Optional[str]): How to handle inputs longer than the maximum token length.
            - v3: 'NONE', 'START', 'END'
            - v4: 'NONE', 'LEFT', 'RIGHT'
        embedding_types (Optional[List[str]]): Types of embeddings to return. Options:
            'float', 'int8', 'uint8', 'binary', 'ubinary'. Default is ['float'].
        output_dimension (Optional[int]): (v4 only) Vector length. Options: 256, 512, 1024, 1536.
            Default is 1536 if unspecified.
        max_tokens (Optional[int]): (v4 only) Truncation budget per input object.
            The model supports up to ~128,000 tokens.
        aws_region (Optional[str]): The AWS region to use.
        aws_access_key_id (Optional[str]): The AWS access key ID to use.
        aws_secret_access_key (Optional[str]): The AWS secret access key to use.
        session (Optional[Session]): A boto3 Session object to use for authentication.
        request_params (Optional[Dict[str, Any]]): Additional parameters to pass to the API requests.
        client_params (Optional[Dict[str, Any]]): Additional parameters to pass to the boto3 client.
    """

    id: str = "cohere.embed-multilingual-v3"
    dimensions: int = 1024  # v3: 1024, v4: 1536 default (set in __post_init__)
    input_type: InputType = "search_query"
    truncate: Optional[str] = None  # v3: 'NONE'|'START'|'END', v4: 'NONE'|'LEFT'|'RIGHT'
    embedding_types: Optional[List[EmbeddingType]] = None  # 'float', 'int8', 'uint8', etc.

    # v4-specific parameters
    output_dimension: Optional[OutputDimension] = None  # 256, 512, 1024, 1536
    max_tokens: Optional[int] = None  # Up to 128000 for v4

    aws_region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    session: Optional[Session] = None

    request_params: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None
    client: Optional[AwsClient] = None

    def __post_init__(self):
        if self.enable_batch:
            log_warning("AwsBedrockEmbedder does not support batch embeddings, setting enable_batch to False")
            self.enable_batch = False

        # Set appropriate default dimensions based on model version
        if self._is_v4_model():
            # v4 default is 1536, but can be overridden by output_dimension
            if self.output_dimension:
                self.dimensions = self.output_dimension
            else:
                self.dimensions = 1536
        else:
            # v3 models are fixed at 1024
            self.dimensions = 1024

    def _is_v4_model(self) -> bool:
        """Check if the current model is a Cohere Embed v4 model."""
        return "embed-v4" in self.id.lower()

    def get_client(self) -> AwsClient:
        """
        Returns an AWS Bedrock client.

        Credentials are resolved in the following order:
        1. Explicit session parameter
        2. Explicit aws_access_key_id and aws_secret_access_key parameters
        3. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        4. Default boto3 credential chain (~/.aws/credentials, SSO, IAM role, etc.)

        Returns:
            AwsClient: An instance of the AWS Bedrock client.
        """
        if self.client is not None:
            return self.client

        if self.session:
            self.client = self.session.client("bedrock-runtime")
            return self.client

        # Try explicit credentials or environment variables
        self.aws_access_key_id = self.aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = self.aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
        self.aws_region = self.aws_region or getenv("AWS_REGION")

        if self.aws_access_key_id and self.aws_secret_access_key:
            # Use explicit credentials
            self.client = AwsClient(
                service_name="bedrock-runtime",
                region_name=self.aws_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                **(self.client_params or {}),
            )
        else:
            # Fall back to default credential chain (SSO, credentials file, IAM role, etc.)
            self.client = AwsClient(
                service_name="bedrock-runtime",
                region_name=self.aws_region,
                **(self.client_params or {}),
            )
        return self.client

    def get_async_client(self):
        """
        Returns an async AWS Bedrock client using aioboto3.

        Credentials are resolved in the following order:
        1. Explicit session parameter
        2. Explicit aws_access_key_id and aws_secret_access_key parameters
        3. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        4. Default credential chain (~/.aws/credentials, SSO, IAM role, etc.)

        Returns:
            An aioboto3 bedrock-runtime client context manager.
        """
        if aioboto3 is None:
            raise AgnoError(
                message="aioboto3 not installed. Please install it via `pip install aioboto3`.",
                status_code=400,
            )

        if self.session:
            # Convert boto3 session to aioboto3 session
            aio_session = aioboto3.Session(
                aws_access_key_id=self.session.get_credentials().access_key,
                aws_secret_access_key=self.session.get_credentials().secret_key,
                aws_session_token=self.session.get_credentials().token,
                region_name=self.session.region_name,
            )
        else:
            # Try explicit credentials or environment variables
            self.aws_access_key_id = self.aws_access_key_id or getenv("AWS_ACCESS_KEY_ID")
            self.aws_secret_access_key = self.aws_secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
            self.aws_region = self.aws_region or getenv("AWS_REGION")

            if self.aws_access_key_id and self.aws_secret_access_key:
                # Use explicit credentials
                aio_session = aioboto3.Session(
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                    region_name=self.aws_region,
                )
            else:
                # Fall back to default credential chain (SSO, credentials file, IAM role, etc.)
                aio_session = aioboto3.Session(region_name=self.aws_region)

        return aio_session.client("bedrock-runtime", **(self.client_params or {}))

    def _format_request_body(self, text: str) -> str:
        """
        Format the request body for the embedder.

        Args:
            text (str): The text to embed.

        Returns:
            str: The formatted request body as a JSON string.
        """
        request_body: Dict[str, Any] = {
            "texts": [text],
            "input_type": self.input_type,
        }

        if self.truncate:
            request_body["truncate"] = self.truncate

        if self.embedding_types:
            request_body["embedding_types"] = self.embedding_types

        # v4-specific parameters
        if self._is_v4_model():
            if self.output_dimension:
                request_body["output_dimension"] = self.output_dimension
            if self.max_tokens:
                request_body["max_tokens"] = self.max_tokens

        # Add additional request parameters if provided
        if self.request_params:
            request_body.update(self.request_params)

        return json.dumps(request_body)

    def _format_multimodal_request_body(
        self,
        texts: Optional[List[str]] = None,
        images: Optional[List[str]] = None,
        inputs: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Format a multimodal request body for v4 models.

        Args:
            texts: List of text strings to embed (text-only mode)
            images: List of base64 data URIs for images (image-only mode)
            inputs: List of interleaved content items for mixed modality

        Returns:
            str: The formatted request body as a JSON string.
        """
        if not self._is_v4_model():
            raise AgnoError(
                message="Multimodal embeddings are only supported with Cohere Embed v4 models.",
                status_code=400,
            )

        request_body: Dict[str, Any] = {
            "input_type": self.input_type,
        }

        # Set the appropriate input field
        if inputs:
            request_body["inputs"] = inputs
        elif images:
            request_body["images"] = images
        elif texts:
            request_body["texts"] = texts
        else:
            raise AgnoError(
                message="At least one of texts, images, or inputs must be provided.",
                status_code=400,
            )

        if self.truncate:
            request_body["truncate"] = self.truncate

        if self.embedding_types:
            request_body["embedding_types"] = self.embedding_types

        if self.output_dimension:
            request_body["output_dimension"] = self.output_dimension

        if self.max_tokens:
            request_body["max_tokens"] = self.max_tokens

        if self.request_params:
            request_body.update(self.request_params)

        return json.dumps(request_body)

    def _extract_embeddings(self, response_body: Dict[str, Any]) -> List[float]:
        """
        Extract embeddings from the response body, handling both v3 and v4 formats.

        Args:
            response_body: The parsed response body from the API.

        Returns:
            List[float]: The embedding vector.
        """
        try:
            if "embeddings" in response_body:
                embeddings = response_body["embeddings"]

                # Handle list format (single embedding type or v3 default)
                if isinstance(embeddings, list):
                    return embeddings[0] if embeddings else []

                # Handle dict format (multiple embedding types requested)
                if isinstance(embeddings, dict):
                    # Prefer float embeddings
                    if "float" in embeddings:
                        return embeddings["float"][0]
                    # Fallback to first available type
                    for embedding_type in embeddings:
                        if embeddings[embedding_type]:
                            return embeddings[embedding_type][0]

            log_warning("No embeddings found in response")
            return []
        except Exception as e:
            log_warning(f"Error extracting embeddings: {e}")
            return []

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
        return self._extract_embeddings(response)

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        """
        Get embeddings and usage information for the given text.

        Args:
            text (str): The text to embed.

        Returns:
            Tuple[List[float], Optional[Dict[str, Any]]]: The embedding vector and usage information.
        """
        response = self.response(text=text)
        embedding = self._extract_embeddings(response)
        usage = response.get("usage")
        return embedding, usage

    def get_image_embedding(self, image_data_uri: str) -> List[float]:
        """
        Get embeddings for an image (v4 only).

        Args:
            image_data_uri (str): Base64 data URI of the image
                (e.g., "data:image/png;base64,...")

        Returns:
            List[float]: The embedding vector.
        """
        if not self._is_v4_model():
            raise AgnoError(
                message="Image embeddings are only supported with Cohere Embed v4 models.",
                status_code=400,
            )

        try:
            body = self._format_multimodal_request_body(images=[image_data_uri])
            response = self.get_client().invoke_model(
                modelId=self.id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            response_body = json.loads(response["body"].read().decode("utf-8"))
            return self._extract_embeddings(response_body)
        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name="AwsBedrockEmbedder", model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name="AwsBedrockEmbedder", model_id=self.id) from e

    def get_multimodal_embedding(
        self,
        content: List[Dict[str, str]],
    ) -> List[float]:
        """
        Get embeddings for interleaved text and image content (v4 only).

        Args:
            content: List of content parts, each being either:
                - {"type": "text", "text": "..."}
                - {"type": "image_url", "image_url": "data:image/png;base64,..."}

        Returns:
            List[float]: The embedding vector.

        Example:
            embedder.get_multimodal_embedding([
                {"type": "text", "text": "Product description"},
                {"type": "image_url", "image_url": "data:image/png;base64,..."}
            ])
        """
        if not self._is_v4_model():
            raise AgnoError(
                message="Multimodal embeddings are only supported with Cohere Embed v4 models.",
                status_code=400,
            )

        try:
            inputs = [{"content": content}]
            body = self._format_multimodal_request_body(inputs=inputs)
            response = self.get_client().invoke_model(
                modelId=self.id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            response_body = json.loads(response["body"].read().decode("utf-8"))
            return self._extract_embeddings(response_body)
        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name="AwsBedrockEmbedder", model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name="AwsBedrockEmbedder", model_id=self.id) from e

    async def async_get_embedding(self, text: str) -> List[float]:
        """
        Async version of get_embedding() using native aioboto3 async client.
        """
        try:
            body = self._format_request_body(text)
            async with self.get_async_client() as client:
                response = await client.invoke_model(
                    modelId=self.id,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                response_body = json.loads((await response["body"].read()).decode("utf-8"))
                return self._extract_embeddings(response_body)
        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name="AwsBedrockEmbedder", model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name="AwsBedrockEmbedder", model_id=self.id) from e

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict[str, Any]]]:
        """
        Async version of get_embedding_and_usage() using native aioboto3 async client.
        """
        try:
            body = self._format_request_body(text)
            async with self.get_async_client() as client:
                response = await client.invoke_model(
                    modelId=self.id,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                response_body = json.loads((await response["body"].read()).decode("utf-8"))
                embedding = self._extract_embeddings(response_body)
                usage = response_body.get("usage")
                return embedding, usage
        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name="AwsBedrockEmbedder", model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name="AwsBedrockEmbedder", model_id=self.id) from e

    async def async_get_image_embedding(self, image_data_uri: str) -> List[float]:
        """
        Async version of get_image_embedding() (v4 only).
        """
        if not self._is_v4_model():
            raise AgnoError(
                message="Image embeddings are only supported with Cohere Embed v4 models.",
                status_code=400,
            )

        try:
            body = self._format_multimodal_request_body(images=[image_data_uri])
            async with self.get_async_client() as client:
                response = await client.invoke_model(
                    modelId=self.id,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                response_body = json.loads((await response["body"].read()).decode("utf-8"))
                return self._extract_embeddings(response_body)
        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name="AwsBedrockEmbedder", model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name="AwsBedrockEmbedder", model_id=self.id) from e

    async def async_get_multimodal_embedding(
        self,
        content: List[Dict[str, str]],
    ) -> List[float]:
        """
        Async version of get_multimodal_embedding() (v4 only).
        """
        if not self._is_v4_model():
            raise AgnoError(
                message="Multimodal embeddings are only supported with Cohere Embed v4 models.",
                status_code=400,
            )

        try:
            inputs = [{"content": content}]
            body = self._format_multimodal_request_body(inputs=inputs)
            async with self.get_async_client() as client:
                response = await client.invoke_model(
                    modelId=self.id,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                response_body = json.loads((await response["body"].read()).decode("utf-8"))
                return self._extract_embeddings(response_body)
        except ClientError as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e.response), model_name="AwsBedrockEmbedder", model_id=self.id) from e
        except Exception as e:
            log_error(f"Unexpected error calling Bedrock API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name="AwsBedrockEmbedder", model_id=self.id) from e
