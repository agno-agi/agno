from os import getenv
from typing import Any, Dict, List, Literal, Optional, Union

from agno.exceptions import CheckTrigger, InputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunInput
from agno.run.team import TeamRunInput
from agno.utils.log import log_debug
from agno.utils.openai import images_to_message


class OpenAIModerationGuardrail(BaseGuardrail):
    """Guardrail for detecting content that violates OpenAI's content policy.

    Args:
        moderation_model (str): The model to use for moderation. Defaults to "omni-moderation-latest".
        raise_for_categories (List[str]): The categories to raise for.
                                          Options are: "sexual", "sexual/minors", "harassment",
                                          "harassment/threatening", "hate", "hate/threatening",
                                          "illicit", "illicit/violent", "self-harm", "self-harm/intent",
                                          "self-harm/instructions", "violence", "violence/graphic".
                                          Defaults to include all categories.
        api_key (str): The API key to use for moderation. Defaults to the OPENAI_API_KEY environment variable.
    """

    def __init__(
        self,
        moderation_model: str = "omni-moderation-latest",
        raise_for_categories: Optional[
            List[
                Literal[
                    "sexual",
                    "sexual/minors",
                    "harassment",
                    "harassment/threatening",
                    "hate",
                    "hate/threatening",
                    "illicit",
                    "illicit/violent",
                    "self-harm",
                    "self-harm/intent",
                    "self-harm/instructions",
                    "violence",
                    "violence/graphic",
                ]
            ]
        ] = None,
        api_key: Optional[str] = None,
    ):
        self.moderation_model = moderation_model
        self.api_key = api_key or getenv("OPENAI_API_KEY")
        self.raise_for_categories = raise_for_categories

    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check for content that violates OpenAI's content policy."""
        try:
            from openai import OpenAI as OpenAIClient
        except ImportError:
            raise ImportError("`openai` not installed. Please install using `pip install openai`")

        content = run_input.input_content_string()
        images = run_input.images

        log_debug(f"Moderating content using {self.moderation_model}")
        client = OpenAIClient(api_key=self.api_key)

        model_input: Union[str, List[Dict[str, Any]]] = content

        if images is not None:
            model_input = [{"type": "text", "text": content}, *images_to_message(images=images)]

        # Prepare input based on content type
        response = client.moderations.create(model=self.moderation_model, input=model_input)  # type: ignore

        result = response.results[0]

        if result.flagged:
            moderation_result = {
                "categories": result.categories.model_dump(),
                "category_scores": result.category_scores.model_dump(),
            }

            trigger_validation = False

            if self.raise_for_categories is not None:
                for category in self.raise_for_categories:
                    if moderation_result["categories"][category]:
                        trigger_validation = True
            else:
                # Since at least one category is flagged, we need to raise the check
                trigger_validation = True

            if trigger_validation:
                raise InputCheckError(
                    "OpenAI moderation violation detected.",
                    additional_data=moderation_result,
                    check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
                )

    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check for content that violates OpenAI's content policy."""
        try:
            from openai import AsyncOpenAI as OpenAIClient
        except ImportError:
            raise ImportError("`openai` not installed. Please install using `pip install openai`")

        content = run_input.input_content_string()
        images = run_input.images

        log_debug(f"Moderating content using {self.moderation_model}")
        client = OpenAIClient(api_key=self.api_key)

        model_input: Union[str, List[Dict[str, Any]]] = content

        if images is not None:
            model_input = [{"type": "text", "text": content}, *images_to_message(images=images)]

        # Prepare input based on content type
        response = await client.moderations.create(model=self.moderation_model, input=model_input)  # type: ignore

        result = response.results[0]

        if result.flagged:
            moderation_result = {
                "categories": result.categories.model_dump(),
                "category_scores": result.category_scores.model_dump(),
            }

            trigger_validation = False

            if self.raise_for_categories is not None:
                for category in self.raise_for_categories:
                    if moderation_result["categories"][category]:
                        trigger_validation = True
            else:
                # Since at least one category is flagged, we need to raise the check
                trigger_validation = True

            if trigger_validation:
                raise InputCheckError(
                    "OpenAI moderation violation detected.",
                    additional_data=moderation_result,
                    check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
                )
