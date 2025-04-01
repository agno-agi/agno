from os import getenv
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

from requests import post

from agno.agent import Agent
from agno.media import ImageArtifact
from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class AzureOpenAITools(Toolkit):
    """Toolkit for Azure OpenAI services.

    Currently supports:
    - DALL-E image generation
    """

    # Define valid parameter options as class constants
    VALID_MODELS = ["dall-e-3", "dall-e-2"]
    VALID_SIZES = ["256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"]
    VALID_QUALITIES = ["standard", "hd"]
    VALID_STYLES = ["vivid", "natural"]

    def __init__(
        self,
        api_key: Optional[str] = None,
        azure_endpoint: Optional[str] = None,
        api_version: Optional[str] = None,
        dalle_deployment: Optional[str] = None,
        dalle_model: str = "dall-e-3",
    ):
        super().__init__(name="azure_openai")

        # Set credentials from parameters or environment variables
        self.api_key = api_key or getenv("AZURE_OPENAI_API_KEY")
        self.azure_endpoint = azure_endpoint or getenv("AZURE_OPENAI_ENDPOINT")
        self.api_version = api_version or getenv("AZURE_OPENAI_API_VERSION") or "2023-12-01-preview"

        # Log warnings for missing credentials
        if not self.api_key:
            logger.error("AZURE_OPENAI_API_KEY not set")
        if not self.azure_endpoint:
            logger.error("AZURE_OPENAI_ENDPOINT not set")

        # Initialize DALL-E parameters
        self.dalle_deployment = dalle_deployment or getenv("AZURE_OPENAI_IMAGE_DEPLOYMENT")
        self.dalle_model = dalle_model

        # Validate DALL-E parameters
        if self.dalle_deployment and self.dalle_model in self.VALID_MODELS:
            # Create and store the base URL
            self.dalle_base_url = f"{self.azure_endpoint}/openai/deployments/{self.dalle_deployment}/images/generations?api-version={self.api_version}"
            # Register the DALL-E tool
            self.register(self.generate_image)
            logger.info("DALL-E tool initialized successfully")
        else:
            logger.error("Missing required DALL-E parameters or invalid model")

    def _enforce_valid_dalle_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Enforce valid parameters by replacing invalid ones with defaults."""
        enforced = params.copy()

        # Validate size
        if params.get("size") not in self.VALID_SIZES:
            enforced["size"] = "1024x1024"
            log_debug(f"Enforcing valid size: '{params.get('size')}' -> '1024x1024'")

        # Validate quality
        if params.get("quality") not in self.VALID_QUALITIES:
            enforced["quality"] = "standard"
            log_debug(f"Enforcing valid quality: '{params.get('quality')}' -> 'standard'")

        # Validate style
        if params.get("style") not in self.VALID_STYLES:
            enforced["style"] = "vivid"
            log_debug(f"Enforcing valid style: '{params.get('style')}' -> 'vivid'")

        # Validate number of images
        if not isinstance(params.get("n"), int) or params.get("n", 0) <= 0:
            enforced["n"] = 1
            log_debug(f"Enforcing valid n: '{params.get('n')}' -> 1")

        # Special case: dall-e-3 only supports n=1
        if enforced.get("model") == "dall-e-3" and enforced.get("n", 1) > 1:
            enforced["n"] = 1
            log_debug("Enforcing n=1 for dall-e-3 model")

        return enforced

    def generate_image(
        self,
        agent: Agent,
        prompt: str,
        n: int = 1,
        size: Optional[Literal["256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"]] = "1024x1024",
        quality: Literal["standard", "hd"] = "standard",
        style: Literal["vivid", "natural"] = "vivid",
    ) -> str:
        """Generate an image using Azure OpenAI DALL-E.

        Args:
            agent: The agent instance for adding images
            prompt: Text description of the desired image
            n: Number of images to generate (default: 1).
                Note: dall-e-3 only supports n=1, while dall-e-2 supports multiple images.
            size: Image size.
                Valid options: "256x256", "512x512", "1024x1024", "1792x1024", "1024x1792" (default: "1024x1024")
                Note: Not all sizes are available for all models.
            quality: Image quality.
                Valid options: "standard" or "hd" (default: "standard")
                Note: "hd" quality is only available for dall-e-3.
            style: Image style.
                Valid options: "vivid" or "natural" (default: "vivid")
                Note: "vivid" produces more dramatic images, while "natural" produces more realistic ones.

        Returns:
            A message with image URLs or an error message

        Note:
            Invalid parameters will be automatically corrected to valid values. For example:
            - Invalid sizes will be changed to "1024x1024"
            - Invalid quality values will be changed to "standard"
            - Invalid style values will be changed to "vivid"
            - For dall-e-3, n will always be set to 1
        """
        # Check if DALL-E is properly initialized
        if not hasattr(self, "dalle_base_url"):
            return "DALL-E tool not properly initialized. Please check your configuration."

        # Enforce valid parameters
        params = self._enforce_valid_dalle_parameters(
            {
                "n": n,
                "size": size,
                "quality": quality,
                "style": style,
            }
        )

        # Add prompt and model to params - this wasn't included in enforcement because it doesn't need validation
        params["prompt"] = prompt
        params["model"] = self.dalle_model

        try:
            # Make API request using stored base URL
            headers = {"api-key": self.api_key, "Content-Type": "application/json"}
            response = post(self.dalle_base_url, headers=headers, json=params)

            if response.status_code != 200:
                return f"Error {response.status_code}: {response.text}"

            # Process results
            data = response.json()
            log_debug("Image generated successfully")

            # Add images to agent
            response_str = ""
            for img in data.get("data", []):
                image_url = img.get("url")
                revised_prompt = img.get("revised_prompt")

                # Add image to agent
                agent.add_image(
                    ImageArtifact(id=str(uuid4()), url=image_url, original_prompt=prompt, revised_prompt=revised_prompt)
                )

                response_str += f"Image has been generated at the URL {image_url}\n"
            return response_str

        except Exception as e:
            logger.error(f"Failed to generate image: {e}")
            return f"Error: {e}"
