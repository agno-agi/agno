import asyncio
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from textwrap import dedent
from typing import Any, Dict, List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.base import RunContext
from agno.tools import Toolkit
from agno.utils.log import logger


class ModelFeedbackTools(Toolkit):
    """Toolkit that sends the current conversation to one or more secondary models for feedback/critique.

    Use this to get a "second opinion" from a different model mid-session. Supports parallel
    feedback from multiple models (e.g. Gemini + Claude at the same time).

    Args:
        model: A single Model instance to use for feedback.
        models: A list of Model instances for parallel feedback from multiple models.
        aspects: Aspects to evaluate (e.g. ["accuracy", "completeness", "tone"]).
        system_prompt: Override the default critique system prompt.
        include_system_messages: Whether to include system messages in the conversation context.
        max_messages: Limit how many messages are sent to the feedback model(s).
        add_instructions: Whether to add tool instructions to the agent.
    """

    def __init__(
        self,
        model: Optional[Model] = None,
        models: Optional[List[Model]] = None,
        aspects: Optional[List[str]] = None,
        system_prompt: Optional[str] = None,
        include_system_messages: bool = False,
        max_messages: Optional[int] = None,
        add_instructions: bool = True,
        **kwargs: Any,
    ):
        self.feedback_models: List[Model] = self._resolve_models(model, models)
        self.aspects = aspects or ["accuracy", "completeness", "clarity"]
        self.custom_system_prompt = system_prompt
        self.include_system_messages = include_system_messages
        self.max_messages = max_messages

        super().__init__(
            name="model_feedback_tools",
            tools=[self.get_feedback],
            async_tools=[(self.aget_feedback, "get_feedback")],
            instructions=dedent("""\
                Use the `get_feedback` tool to get a second opinion on your response from another AI model.
                You can pass an optional `focus` parameter to direct the review to a specific area.
                Review the feedback and incorporate relevant suggestions before giving your final answer.
                You do not need to follow every suggestion -- use your judgment.\
            """),
            add_instructions=add_instructions,
            **kwargs,
        )

    def _resolve_models(self, model: Optional[Model], models: Optional[List[Model]]) -> List[Model]:
        """Resolve the list of feedback models from the provided arguments."""
        if models:
            return models
        if model:
            return [model]
        raise ValueError("Either `model` or `models` must be provided.")

    def _format_conversation(self, messages: List[Message]) -> str:
        """Format conversation messages into a readable transcript."""
        filtered = []
        for msg in messages:
            if msg.role == "system" and not self.include_system_messages:
                continue
            if msg.role in ("user", "assistant", "system"):
                filtered.append(msg)

        if self.max_messages and len(filtered) > self.max_messages:
            filtered = filtered[-self.max_messages :]

        lines = []
        for msg in filtered:
            content = msg.get_content_string() if msg.content else ""
            if content:
                lines.append(f"[{msg.role.upper()}]: {content}")
        return "\n\n".join(lines)

    def _build_system_prompt(self, focus: Optional[str] = None) -> str:
        """Build the critique system prompt."""
        if self.custom_system_prompt:
            return self.custom_system_prompt

        aspects_lines = "\n".join(f"- {aspect}" for aspect in self.aspects)
        focus_line = f"\nPay special attention to: {focus}" if focus else ""

        return dedent(f"""\
            You are an expert reviewer providing constructive feedback on an AI assistant's conversation.

            Evaluate the assistant's responses on these aspects:
            {aspects_lines}
            {focus_line}
            Respond in JSON format with this exact structure:
            {{
              "overall_rating": <1-10>,
              "aspects": {{
                "<aspect_name>": {{
                  "rating": <1-10>,
                  "comment": "<brief comment>"
                }}
              }},
              "suggestions": ["<suggestion 1>", "<suggestion 2>"],
              "summary": "<1-2 sentence overall assessment>"
            }}

            Only respond with the JSON object, no other text.\
        """)

    def _invoke_model(self, model: Model, conversation: str, focus: Optional[str] = None) -> Dict[str, Any]:
        """Invoke a single model for feedback (sync)."""
        system_prompt = self._build_system_prompt(focus)
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=conversation),
        ]
        assistant_message = Message(role="assistant")

        try:
            response: ModelResponse = model.invoke(
                messages=messages,
                assistant_message=assistant_message,
            )
            content = response.content or ""
            # Try to parse as JSON for validation
            try:
                parsed = json.loads(content)
                parsed["model"] = model.id or model.name
                return parsed
            except json.JSONDecodeError:
                return {
                    "model": model.id or model.name,
                    "raw_feedback": content,
                }
        except Exception as e:
            logger.error(f"Feedback model {model.id} failed: {e}")
            return {
                "model": model.id or model.name,
                "error": str(e),
            }

    async def _ainvoke_model(self, model: Model, conversation: str, focus: Optional[str] = None) -> Dict[str, Any]:
        """Invoke a single model for feedback (async)."""
        system_prompt = self._build_system_prompt(focus)
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=conversation),
        ]
        assistant_message = Message(role="assistant")

        try:
            response: ModelResponse = await model.ainvoke(
                messages=messages,
                assistant_message=assistant_message,
            )
            content = response.content or ""
            try:
                parsed = json.loads(content)
                parsed["model"] = model.id or model.name
                return parsed
            except json.JSONDecodeError:
                return {
                    "model": model.id or model.name,
                    "raw_feedback": content,
                }
        except Exception as e:
            logger.error(f"Feedback model {model.id} failed: {e}")
            return {
                "model": model.id or model.name,
                "error": str(e),
            }

    def get_feedback(self, run_context: RunContext, focus: Optional[str] = None) -> str:
        """Get feedback on the current conversation from one or more secondary AI models.

        Args:
            run_context: Automatically injected by the framework. Contains the current conversation messages.
            focus (str, optional): A specific area to focus the feedback on (e.g. "check the code for bugs").

        Returns:
            str: JSON string with structured feedback from each model.
        """
        if not run_context.messages:
            return json.dumps({"error": "No conversation messages available for feedback."})

        conversation = self._format_conversation(run_context.messages)
        if not conversation:
            return json.dumps({"error": "No conversation content to review."})

        models = self.feedback_models

        if len(models) == 1:
            result = self._invoke_model(models[0], conversation, focus)
            return json.dumps(result, indent=2)

        # Parallel execution for multiple models
        results: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=len(models)) as executor:
            futures = {executor.submit(self._invoke_model, m, conversation, focus): m for m in models}
            for future in as_completed(futures):
                results.append(future.result())

        return json.dumps({"feedback": results}, indent=2)

    async def aget_feedback(self, run_context: RunContext, focus: Optional[str] = None) -> str:
        """Get feedback on the current conversation from one or more secondary AI models.

        Args:
            run_context: Automatically injected by the framework. Contains the current conversation messages.
            focus (str, optional): A specific area to focus the feedback on (e.g. "check the code for bugs").

        Returns:
            str: JSON string with structured feedback from each model.
        """
        if not run_context.messages:
            return json.dumps({"error": "No conversation messages available for feedback."})

        conversation = self._format_conversation(run_context.messages)
        if not conversation:
            return json.dumps({"error": "No conversation content to review."})

        models = self.feedback_models

        if len(models) == 1:
            result = await self._ainvoke_model(models[0], conversation, focus)
            return json.dumps(result, indent=2)

        # Parallel execution for multiple models using asyncio.gather
        tasks = [self._ainvoke_model(m, conversation, focus) for m in models]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        return json.dumps({"feedback": list(results)}, indent=2)
