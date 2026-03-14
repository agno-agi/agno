from os import getenv
from typing import Any, Dict, List, Literal, Optional, Union

from agno.exceptions import CheckTrigger, InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail, OnFailCallback
from agno.run.agent import RunInput, RunOutput
from agno.run.messages import RunMessages
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.utils.guardrails import extract_all_text_from_run_messages
from agno.utils.log import log_debug
from agno.utils.openai import images_to_message


class OpenAIModerationGuardrail(BaseGuardrail):
    """Guardrail using OpenAI's moderation API to detect content policy violations."""

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
        check_output: bool = False,
        dry_run: bool = False,
        on_fail: Optional[OnFailCallback] = None,
    ):
        """Initialize a new OpenAIModerationGuardrail.

        Args:
            moderation_model: The moderation model to use.
            raise_for_categories: Categories to flag. Defaults to all categories.
            api_key: OpenAI API key. Defaults to OPENAI_API_KEY env var.
            check_output: Whether to check output content in post_check.
            dry_run: If True, logs violations without raising errors.
            on_fail: Optional callback invoked when a check fails.
                     Receives (error, input_data, context).
        """
        super().__init__(dry_run=dry_run, on_fail=on_fail)
        self.moderation_model = moderation_model
        self.api_key = api_key or getenv("OPENAI_API_KEY")
        self.raise_for_categories = raise_for_categories
        self.check_output = check_output

    def _check_moderation_result(
        self, result: Any, content_type: Literal["input", "output"], check_type: str, input_data: Any = None
    ) -> None:
        """Check moderation result and raise appropriate error if flagged."""
        if result.flagged:
            moderation_result = {
                "categories": result.categories.model_dump(),
                "category_scores": result.category_scores.model_dump(),
            }

            trigger_validation = False
            triggered_categories = []

            if self.raise_for_categories is not None:
                for category in self.raise_for_categories:
                    if moderation_result["categories"][category]:
                        trigger_validation = True
                        triggered_categories.append(category)
            else:
                trigger_validation = True
                triggered_categories = [cat for cat, flagged in moderation_result["categories"].items() if flagged]

            if trigger_validation:
                additional_info = f"categories={triggered_categories}"
                if content_type == "output":
                    self._handle_violation(
                        OutputCheckError(
                            "OpenAI moderation violation detected in output.",
                            additional_data=moderation_result,
                            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
                        ),
                        "OpenAIModerationGuardrail",
                        check_type,
                        additional_info,
                        input_data=input_data,
                    )
                else:
                    self._handle_violation(
                        InputCheckError(
                            "OpenAI moderation violation detected.",
                            additional_data=moderation_result,
                            check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
                        ),
                        "OpenAIModerationGuardrail",
                        check_type,
                        additional_info,
                        input_data=input_data,
                    )

    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
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

        response = client.moderations.create(model=self.moderation_model, input=model_input)  # type: ignore
        result = response.results[0]
        self._check_moderation_result(result, "input", "pre_check", input_data=run_input)

    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
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

        response = await client.moderations.create(model=self.moderation_model, input=model_input)  # type: ignore
        result = response.results[0]
        self._check_moderation_result(result, "input", "async_pre_check", input_data=run_input)

    def model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Check all messages for content policy violations before model processes them."""
        try:
            from openai import OpenAI as OpenAIClient
        except ImportError:
            raise ImportError("`openai` not installed. Please install using `pip install openai`")

        content = extract_all_text_from_run_messages(run_messages)
        if not content.strip():
            return

        log_debug(f"Moderating model messages using {self.moderation_model}")
        client = OpenAIClient(api_key=self.api_key)

        response = client.moderations.create(model=self.moderation_model, input=content)
        result = response.results[0]
        self._check_moderation_result(result, "input", "model_check", input_data=run_messages)

    async def async_model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Async check all messages for content policy violations before model processes them."""
        try:
            from openai import AsyncOpenAI as OpenAIClient
        except ImportError:
            raise ImportError("`openai` not installed. Please install using `pip install openai`")

        content = extract_all_text_from_run_messages(run_messages)
        if not content.strip():
            return

        log_debug(f"Moderating model messages using {self.moderation_model}")
        client = OpenAIClient(api_key=self.api_key)

        response = await client.moderations.create(model=self.moderation_model, input=content)
        result = response.results[0]
        self._check_moderation_result(result, "input", "async_model_check", input_data=run_messages)

    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Check output content for violations of OpenAI's content policy."""
        if not self.check_output:
            return

        try:
            from openai import OpenAI as OpenAIClient
        except ImportError:
            raise ImportError("`openai` not installed. Please install using `pip install openai`")

        content = str(run_output.content) if run_output.content else ""
        if not content.strip():
            return

        log_debug(f"Moderating output using {self.moderation_model}")
        client = OpenAIClient(api_key=self.api_key)

        response = client.moderations.create(model=self.moderation_model, input=content)
        result = response.results[0]
        self._check_moderation_result(result, "output", "post_check", input_data=run_output)

    async def async_post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Async check output content for violations of OpenAI's content policy."""
        if not self.check_output:
            return

        try:
            from openai import AsyncOpenAI as OpenAIClient
        except ImportError:
            raise ImportError("`openai` not installed. Please install using `pip install openai`")

        content = str(run_output.content) if run_output.content else ""
        if not content.strip():
            return

        log_debug(f"Moderating output using {self.moderation_model}")
        client = OpenAIClient(api_key=self.api_key)

        response = await client.moderations.create(model=self.moderation_model, input=content)
        result = response.results[0]
        self._check_moderation_result(result, "output", "async_post_check", input_data=run_output)
