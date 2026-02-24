"""
ReasoningManager - Centralized manager for all reasoning operations.

This module consolidates reasoning logic from the Agent class into a single,
maintainable manager that handles:
- Native reasoning models (DeepSeek, Anthropic, OpenAI, Gemini, etc.)
- Default Chain-of-Thought reasoning
- Both streaming and non-streaming modes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import (
    TYPE_CHECKING,
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
)

from agno.models.base import Model
from agno.models.message import Message
from agno.reasoning.step import NextAction, ReasoningStep, ReasoningSteps
from agno.run.base import RunContext
from agno.run.messages import RunMessages
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_debug, log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput


class ReasoningEventType(str, Enum):
    """Types of reasoning events that can be emitted."""

    started = "reasoning_started"
    content_delta = "reasoning_content_delta"
    step = "reasoning_step"
    completed = "reasoning_completed"
    error = "reasoning_error"


@dataclass
class ReasoningEvent:
    """
    A unified reasoning event that can be converted to Agent or Team specific events.

    This allows the ReasoningManager to emit events without knowing about the
    specific event types used by Agent or Team.
    """

    event_type: ReasoningEventType
    # For content_delta events
    reasoning_content: Optional[str] = None
    # For step events
    reasoning_step: Optional[ReasoningStep] = None
    # For completed events
    reasoning_steps: List[ReasoningStep] = field(default_factory=list)
    # For error events
    error: Optional[str] = None
    # The message to append to run_messages (for native reasoning)
    message: Optional[Message] = None
    # All reasoning messages (for updating run_output)
    reasoning_messages: List[Message] = field(default_factory=list)


@dataclass
class ReasoningConfig:
    """Configuration for reasoning operations."""

    reasoning_model: Optional[Model] = None
    reasoning_agent: Optional["Agent"] = None
    min_steps: int = 1
    max_steps: int = 10
    tools: Optional[List[Union[Toolkit, Callable, Function, Dict]]] = None
    tool_call_limit: Optional[int] = None
    use_json_mode: bool = False
    telemetry: bool = True
    debug_mode: bool = False
    debug_level: Literal[1, 2] = 1
    run_context: Optional[RunContext] = None
    run_response: Optional[Union["RunOutput", "TeamRunOutput"]] = None


@dataclass
class ReasoningResult:
    """Result from a reasoning operation."""

    message: Optional[Message] = None
    steps: List[ReasoningStep] = field(default_factory=list)
    reasoning_messages: List[Message] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None


class ReasoningManager:
    """
    Centralized manager for all reasoning operations.

    Handles both native reasoning models (DeepSeek, Anthropic, OpenAI, etc.)
    and default Chain-of-Thought reasoning with a clean, unified interface.
    """

    def __init__(self, config: ReasoningConfig):
        self.config = config
        self._reasoning_agent: Optional["Agent"] = None
        self._model_type: Optional[str] = None

    @property
    def reasoning_model(self) -> Optional[Model]:
        return self.config.reasoning_model

    def _detect_model_type(self, model: Model) -> Optional[str]:
        """Detect the type of reasoning model."""
        from agno.reasoning.anthropic import is_anthropic_reasoning_model
        from agno.reasoning.azure_ai_foundry import is_ai_foundry_reasoning_model
        from agno.reasoning.deepseek import is_deepseek_reasoning_model
        from agno.reasoning.gemini import is_gemini_reasoning_model
        from agno.reasoning.groq import is_groq_reasoning_model
        from agno.reasoning.ollama import is_ollama_reasoning_model
        from agno.reasoning.openai import is_openai_reasoning_model
        from agno.reasoning.vertexai import is_vertexai_reasoning_model

        if is_deepseek_reasoning_model(model):
            return "deepseek"
        if is_anthropic_reasoning_model(model):
            return "anthropic"
        if is_openai_reasoning_model(model):
            return "openai"
        if is_groq_reasoning_model(model):
            return "groq"
        if is_ollama_reasoning_model(model):
            return "ollama"
        if is_ai_foundry_reasoning_model(model):
            return "ai_foundry"
        if is_gemini_reasoning_model(model):
            return "gemini"
        if is_vertexai_reasoning_model(model):
            return "vertexai"
        return None

    def _get_reasoning_agent(self, model: Model) -> "Agent":
        """Get or create a reasoning agent for the given model."""
        if self.config.reasoning_agent is not None:
            return self.config.reasoning_agent

        from agno.reasoning.helpers import get_reasoning_agent

        return get_reasoning_agent(
            reasoning_model=model,
            telemetry=self.config.telemetry,
            debug_mode=self.config.debug_mode,
            debug_level=self.config.debug_level,
            run_context=self.config.run_context,
        )

    def _get_default_reasoning_agent(self, model: Model) -> Optional["Agent"]:
        """Get or create a default CoT reasoning agent."""
        if self.config.reasoning_agent is not None:
            return self.config.reasoning_agent

        from agno.reasoning.default import get_default_reasoning_agent

        return get_default_reasoning_agent(
            reasoning_model=model,
            min_steps=self.config.min_steps,
            max_steps=self.config.max_steps,
            tools=self.config.tools,
            tool_call_limit=self.config.tool_call_limit,
            use_json_mode=self.config.use_json_mode,
            telemetry=self.config.telemetry,
            debug_mode=self.config.debug_mode,
            debug_level=self.config.debug_level,
            run_context=self.config.run_context,
        )

    def is_native_reasoning_model(self, model: Optional[Model] = None) -> bool:
        """Check if the model is a native reasoning model."""
        model = model or self.config.reasoning_model
        if model is None:
            return False
        return self._detect_model_type(model) is not None

    # =========================================================================
    # Native Model Reasoning (Non-Streaming)
    # =========================================================================

    def get_native_reasoning(self, model: Model, messages: List[Message]) -> ReasoningResult:
        """Get reasoning from a native reasoning model (non-streaming)."""
        model_type = self._detect_model_type(model)
        if model_type is None:
            return ReasoningResult(success=False, error="Not a native reasoning model")

        reasoning_agent = self._get_reasoning_agent(model)
        reasoning_message: Optional[Message] = None
        run_response = self.config.run_response

        try:
            if model_type == "deepseek":
                from agno.reasoning.deepseek import get_deepseek_reasoning

                log_debug("Starting DeepSeek Reasoning", center=True, symbol="=")
                reasoning_message = get_deepseek_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "anthropic":
                from agno.reasoning.anthropic import get_anthropic_reasoning

                log_debug("Starting Anthropic Claude Reasoning", center=True, symbol="=")
                reasoning_message = get_anthropic_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "openai":
                from agno.reasoning.openai import get_openai_reasoning

                log_debug("Starting OpenAI Reasoning", center=True, symbol="=")
                reasoning_message = get_openai_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "groq":
                from agno.reasoning.groq import get_groq_reasoning

                log_debug("Starting Groq Reasoning", center=True, symbol="=")
                reasoning_message = get_groq_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "ollama":
                from agno.reasoning.ollama import get_ollama_reasoning

                log_debug("Starting Ollama Reasoning", center=True, symbol="=")
                reasoning_message = get_ollama_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "ai_foundry":
                from agno.reasoning.azure_ai_foundry import get_ai_foundry_reasoning

                log_debug("Starting Azure AI Foundry Reasoning", center=True, symbol="=")
                reasoning_message = get_ai_foundry_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "gemini":
                from agno.reasoning.gemini import get_gemini_reasoning

                log_debug("Starting Gemini Reasoning", center=True, symbol="=")
                reasoning_message = get_gemini_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "vertexai":
                from agno.reasoning.vertexai import get_vertexai_reasoning

                log_debug("Starting VertexAI Reasoning", center=True, symbol="=")
                reasoning_message = get_vertexai_reasoning(reasoning_agent, messages, run_response=run_response)

        except Exception as e:
            log_error(f"Reasoning error: {e}")
            return ReasoningResult(success=False, error=str(e))

        if reasoning_message is None:
            return ReasoningResult(
                success=False,
                error="Reasoning response is None",
            )

        return ReasoningResult(
            message=reasoning_message,
            steps=[ReasoningStep(result=reasoning_message.content)],
            reasoning_messages=[reasoning_message],
            success=True,
        )

    async def aget_native_reasoning(self, model: Model, messages: List[Message]) -> ReasoningResult:
        """Get reasoning from a native reasoning model asynchronously (non-streaming)."""
        model_type = self._detect_model_type(model)
        if model_type is None:
            return ReasoningResult(success=False, error="Not a native reasoning model")

        reasoning_agent = self._get_reasoning_agent(model)
        reasoning_message: Optional[Message] = None
        run_response = self.config.run_response

        try:
            if model_type == "deepseek":
                from agno.reasoning.deepseek import aget_deepseek_reasoning

                log_debug("Starting DeepSeek Reasoning", center=True, symbol="=")
                reasoning_message = await aget_deepseek_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "anthropic":
                from agno.reasoning.anthropic import aget_anthropic_reasoning

                log_debug("Starting Anthropic Claude Reasoning", center=True, symbol="=")
                reasoning_message = await aget_anthropic_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "openai":
                from agno.reasoning.openai import aget_openai_reasoning

                log_debug("Starting OpenAI Reasoning", center=True, symbol="=")
                reasoning_message = await aget_openai_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "groq":
                from agno.reasoning.groq import aget_groq_reasoning

                log_debug("Starting Groq Reasoning", center=True, symbol="=")
                reasoning_message = await aget_groq_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "ollama":
                from agno.reasoning.ollama import aget_ollama_reasoning

                log_debug("Starting Ollama Reasoning", center=True, symbol="=")
                reasoning_message = await aget_ollama_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "ai_foundry":
                from agno.reasoning.azure_ai_foundry import aget_ai_foundry_reasoning

                log_debug("Starting Azure AI Foundry Reasoning", center=True, symbol="=")
                reasoning_message = await aget_ai_foundry_reasoning(
                    reasoning_agent, messages, run_response=run_response
                )

            elif model_type == "gemini":
                from agno.reasoning.gemini import aget_gemini_reasoning

                log_debug("Starting Gemini Reasoning", center=True, symbol="=")
                reasoning_message = await aget_gemini_reasoning(reasoning_agent, messages, run_response=run_response)

            elif model_type == "vertexai":
                from agno.reasoning.vertexai import aget_vertexai_reasoning

                log_debug("Starting VertexAI Reasoning", center=True, symbol="=")
                reasoning_message = await aget_vertexai_reasoning(reasoning_agent, messages, run_response=run_response)

        except Exception as e:
            log_error(f"Reasoning error: {e}")
            return ReasoningResult(success=False, error=str(e))

        if reasoning_message is None:
            return ReasoningResult(
                success=False,
                error="Reasoning response is None",
            )

        return ReasoningResult(
            message=reasoning_message,
            steps=[ReasoningStep(result=reasoning_message.content)],
            reasoning_messages=[reasoning_message],
            success=True,
        )

    # =========================================================================
    # Native Model Reasoning (Streaming)
    # =========================================================================

    def stream_native_reasoning(
        self, model: Model, messages: List[Message]
    ) -> Iterator[Tuple[Optional[str], Optional[ReasoningResult]]]:
        """
        Stream reasoning from a native reasoning model.

        Yields:
            Tuple of (reasoning_content_delta, final_result)
            - During streaming: (reasoning_content_delta, None)
            - At the end: (None, ReasoningResult)
        """
        model_type = self._detect_model_type(model)
        if model_type is None:
            yield (None, ReasoningResult(success=False, error="Not a native reasoning model"))
            return

        reasoning_agent = self._get_reasoning_agent(model)

        # Currently only DeepSeek and Anthropic support streaming
        if model_type == "deepseek":
            from agno.reasoning.deepseek import get_deepseek_reasoning_stream

            log_debug("Starting DeepSeek Reasoning (streaming)", center=True, symbol="=")
            final_message: Optional[Message] = None
            for reasoning_delta, message in get_deepseek_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "anthropic":
            from agno.reasoning.anthropic import get_anthropic_reasoning_stream

            log_debug("Starting Anthropic Claude Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            for reasoning_delta, message in get_anthropic_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "gemini":
            from agno.reasoning.gemini import get_gemini_reasoning_stream

            log_debug("Starting Gemini Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            for reasoning_delta, message in get_gemini_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "openai":
            from agno.reasoning.openai import get_openai_reasoning_stream

            log_debug("Starting OpenAI Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            for reasoning_delta, message in get_openai_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "vertexai":
            from agno.reasoning.vertexai import get_vertexai_reasoning_stream

            log_debug("Starting VertexAI Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            for reasoning_delta, message in get_vertexai_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "ai_foundry":
            from agno.reasoning.azure_ai_foundry import get_ai_foundry_reasoning_stream

            log_debug("Starting Azure AI Foundry Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            for reasoning_delta, message in get_ai_foundry_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "groq":
            from agno.reasoning.groq import get_groq_reasoning_stream

            log_debug("Starting Groq Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            for reasoning_delta, message in get_groq_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "ollama":
            from agno.reasoning.ollama import get_ollama_reasoning_stream

            log_debug("Starting Ollama Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            for reasoning_delta, message in get_ollama_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        else:
            # Fall back to non-streaming for other models
            result = self.get_native_reasoning(model, messages)
            yield (None, result)

    async def astream_native_reasoning(
        self, model: Model, messages: List[Message]
    ) -> AsyncIterator[Tuple[Optional[str], Optional[ReasoningResult]]]:
        """
        Stream reasoning from a native reasoning model asynchronously.

        Yields:
            Tuple of (reasoning_content_delta, final_result)
            - During streaming: (reasoning_content_delta, None)
            - At the end: (None, ReasoningResult)
        """
        model_type = self._detect_model_type(model)
        if model_type is None:
            yield (None, ReasoningResult(success=False, error="Not a native reasoning model"))
            return

        reasoning_agent = self._get_reasoning_agent(model)

        # Currently only DeepSeek and Anthropic support streaming
        if model_type == "deepseek":
            from agno.reasoning.deepseek import aget_deepseek_reasoning_stream

            log_debug("Starting DeepSeek Reasoning (streaming)", center=True, symbol="=")
            final_message: Optional[Message] = None
            async for reasoning_delta, message in aget_deepseek_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "anthropic":
            from agno.reasoning.anthropic import aget_anthropic_reasoning_stream

            log_debug("Starting Anthropic Claude Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            async for reasoning_delta, message in aget_anthropic_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "gemini":
            from agno.reasoning.gemini import aget_gemini_reasoning_stream

            log_debug("Starting Gemini Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            async for reasoning_delta, message in aget_gemini_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "openai":
            from agno.reasoning.openai import aget_openai_reasoning_stream

            log_debug("Starting OpenAI Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            async for reasoning_delta, message in aget_openai_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "vertexai":
            from agno.reasoning.vertexai import aget_vertexai_reasoning_stream

            log_debug("Starting VertexAI Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            async for reasoning_delta, message in aget_vertexai_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "ai_foundry":
            from agno.reasoning.azure_ai_foundry import aget_ai_foundry_reasoning_stream

            log_debug("Starting Azure AI Foundry Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            async for reasoning_delta, message in aget_ai_foundry_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "groq":
            from agno.reasoning.groq import aget_groq_reasoning_stream

            log_debug("Starting Groq Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            async for reasoning_delta, message in aget_groq_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        elif model_type == "ollama":
            from agno.reasoning.ollama import aget_ollama_reasoning_stream

            log_debug("Starting Ollama Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            async for reasoning_delta, message in aget_ollama_reasoning_stream(reasoning_agent, messages):
                if reasoning_delta is not None:
                    yield (reasoning_delta, None)
                if message is not None:
                    final_message = message

            if final_message:
                yield (
                    None,
                    ReasoningResult(
                        message=final_message,
                        steps=[ReasoningStep(result=final_message.content)],
                        reasoning_messages=[final_message],
                        success=True,
                    ),
                )
            else:
                yield (None, ReasoningResult(success=False, error="No reasoning content"))

        else:
            # Fall back to non-streaming for other models
            result = await self.aget_native_reasoning(model, messages)
            yield (None, result)

    # =========================================================================
    # Default Chain-of-Thought Reasoning
    # =========================================================================

    def run_default_reasoning(
        self, model: Model, run_messages: RunMessages
    ) -> Iterator[Tuple[Optional[ReasoningStep], Optional[ReasoningResult]]]:
        """
        Run default Chain-of-Thought reasoning.

        Yields:
            Tuple of (reasoning_step, final_result)
            - During reasoning: (ReasoningStep, None)
            - At the end: (None, ReasoningResult)
        """
        from agno.reasoning.helpers import get_next_action, update_messages_with_reasoning

        reasoning_agent = self._get_default_reasoning_agent(model)
        if reasoning_agent is None:
            yield (None, ReasoningResult(success=False, error="Reasoning agent is None"))
            return

        # Validate reasoning agent output schema
        if (
            reasoning_agent.output_schema is not None
            and isinstance(reasoning_agent.output_schema, type)
            and not issubclass(reasoning_agent.output_schema, ReasoningSteps)
        ):
            yield (
                None,
                ReasoningResult(
                    success=False,
                    error="Reasoning agent response model should be ReasoningSteps",
                ),
            )
            return

        step_count = 1
        next_action = NextAction.CONTINUE
        reasoning_messages: List[Message] = []
        all_reasoning_steps: List[ReasoningStep] = []

        log_debug("Starting Reasoning", center=True, symbol="=")

        while next_action == NextAction.CONTINUE and step_count < self.config.max_steps:
            log_debug(f"Step {step_count}", center=True, symbol="=")
            try:
                reasoning_agent_response: RunOutput = reasoning_agent.run(input=run_messages.get_input_messages())

                # Accumulate reasoning model metrics
                if self.config.run_response is not None:
                    from agno.metrics import accumulate_eval_metrics

                    accumulate_eval_metrics(reasoning_agent_response, self.config.run_response, prefix="reasoning")

                if reasoning_agent_response.content is None or reasoning_agent_response.messages is None:
                    log_warning("Reasoning error. Reasoning response is empty")
                    break

                if isinstance(reasoning_agent_response.content, str):
                    log_warning("Reasoning error. Content is a string, not structured output")
                    break

                if (
                    reasoning_agent_response.content.reasoning_steps is None
                    or len(reasoning_agent_response.content.reasoning_steps) == 0
                ):
                    log_warning("Reasoning error. Reasoning steps are empty")
                    break

                reasoning_steps: List[ReasoningStep] = reasoning_agent_response.content.reasoning_steps
                all_reasoning_steps.extend(reasoning_steps)

                # Yield each reasoning step
                for step in reasoning_steps:
                    yield (step, None)

                # Extract reasoning messages
                first_assistant_index = next(
                    (i for i, m in enumerate(reasoning_agent_response.messages) if m.role == "assistant"),
                    len(reasoning_agent_response.messages),
                )
                reasoning_messages = reasoning_agent_response.messages[first_assistant_index:]

                # Get the next action
                next_action = get_next_action(reasoning_steps[-1])
                if next_action == NextAction.FINAL_ANSWER:
                    break

            except Exception as e:
                log_error(f"Reasoning error: {e}")
                break

            step_count += 1

        log_debug(f"Total Reasoning steps: {len(all_reasoning_steps)}")
        log_debug("Reasoning finished", center=True, symbol="=")

        # Update messages with reasoning
        update_messages_with_reasoning(
            run_messages=run_messages,
            reasoning_messages=reasoning_messages,
        )

        # Yield final result
        yield (
            None,
            ReasoningResult(
                steps=all_reasoning_steps,
                reasoning_messages=reasoning_messages,
                success=True,
            ),
        )

    async def arun_default_reasoning(
        self, model: Model, run_messages: RunMessages
    ) -> AsyncIterator[Tuple[Optional[ReasoningStep], Optional[ReasoningResult]]]:
        """
        Run default Chain-of-Thought reasoning asynchronously.

        Yields:
            Tuple of (reasoning_step, final_result)
            - During reasoning: (ReasoningStep, None)
            - At the end: (None, ReasoningResult)
        """
        from agno.reasoning.helpers import get_next_action, update_messages_with_reasoning

        reasoning_agent = self._get_default_reasoning_agent(model)
        if reasoning_agent is None:
            yield (None, ReasoningResult(success=False, error="Reasoning agent is None"))
            return

        # Validate reasoning agent output schema
        if (
            reasoning_agent.output_schema is not None
            and isinstance(reasoning_agent.output_schema, type)
            and not issubclass(reasoning_agent.output_schema, ReasoningSteps)
        ):
            yield (
                None,
                ReasoningResult(
                    success=False,
                    error="Reasoning agent response model should be ReasoningSteps",
                ),
            )
            return

        step_count = 1
        next_action = NextAction.CONTINUE
        reasoning_messages: List[Message] = []
        all_reasoning_steps: List[ReasoningStep] = []

        log_debug("Starting Reasoning", center=True, symbol="=")

        while next_action == NextAction.CONTINUE and step_count < self.config.max_steps:
            log_debug(f"Step {step_count}", center=True, symbol="=")
            step_count += 1
            try:
                reasoning_agent_response: RunOutput = await reasoning_agent.arun(  # type: ignore[misc]
                    input=run_messages.get_input_messages()
                )

                # Accumulate reasoning model metrics
                if self.config.run_response is not None:
                    from agno.metrics import accumulate_eval_metrics

                    accumulate_eval_metrics(reasoning_agent_response, self.config.run_response, prefix="reasoning")

                if reasoning_agent_response.content is None or reasoning_agent_response.messages is None:
                    log_warning("Reasoning error. Reasoning response is empty")
                    break

                if isinstance(reasoning_agent_response.content, str):
                    log_warning("Reasoning error. Content is a string, not structured output")
                    break

                if reasoning_agent_response.content.reasoning_steps is None:
                    log_warning("Reasoning error. Reasoning steps are empty")
                    break

                reasoning_steps: List[ReasoningStep] = reasoning_agent_response.content.reasoning_steps
                all_reasoning_steps.extend(reasoning_steps)

                # Yield each reasoning step
                for step in reasoning_steps:
                    yield (step, None)

                # Extract reasoning messages
                first_assistant_index = next(
                    (i for i, m in enumerate(reasoning_agent_response.messages) if m.role == "assistant"),
                    len(reasoning_agent_response.messages),
                )
                reasoning_messages = reasoning_agent_response.messages[first_assistant_index:]

                # Get the next action
                next_action = get_next_action(reasoning_steps[-1])
                if next_action == NextAction.FINAL_ANSWER:
                    break

            except Exception as e:
                log_error(f"Reasoning error: {e}")
                break

        log_debug(f"Total Reasoning steps: {len(all_reasoning_steps)}")
        log_debug("Reasoning finished", center=True, symbol="=")

        # Update messages with reasoning
        update_messages_with_reasoning(
            run_messages=run_messages,
            reasoning_messages=reasoning_messages,
        )

        # Yield final result
        yield (
            None,
            ReasoningResult(
                steps=all_reasoning_steps,
                reasoning_messages=reasoning_messages,
                success=True,
            ),
        )

    def reason(
        self,
        run_messages: RunMessages,
        stream: bool = False,
    ) -> Iterator[ReasoningEvent]:
        """
        Run reasoning and yield ReasoningEvent objects.

        Args:
            run_messages: The messages to reason about
            stream: Whether to stream reasoning content

        Yields:
            ReasoningEvent objects for each stage of reasoning
        """
        # Get the reasoning model
        reasoning_model: Optional[Model] = self.config.reasoning_model
        reasoning_model_provided = reasoning_model is not None

        if reasoning_model is None:
            yield ReasoningEvent(
                event_type=ReasoningEventType.error,
                error="Reasoning model is None",
            )
            return

        # Yield started event
        yield ReasoningEvent(event_type=ReasoningEventType.started)

        # Check if this is a native reasoning model
        if reasoning_model_provided and self.is_native_reasoning_model(reasoning_model):
            # Use streaming for native models when stream is enabled
            if stream:
                yield from self._stream_native_reasoning_events(reasoning_model, run_messages)
            else:
                yield from self._get_native_reasoning_events(reasoning_model, run_messages)
        else:
            # Use default Chain-of-Thought reasoning
            if reasoning_model_provided:
                log_info(
                    f"Reasoning model: {reasoning_model.__class__.__name__} is not a native reasoning model, "
                    "defaulting to manual Chain-of-Thought reasoning"
                )
            yield from self._run_default_reasoning_events(reasoning_model, run_messages)

    async def areason(
        self,
        run_messages: RunMessages,
        stream: bool = False,
    ) -> AsyncIterator[ReasoningEvent]:
        """
        Unified async reasoning interface that yields ReasoningEvent objects.

        This method handles all reasoning logic and yields events that can be
        converted to Agent or Team specific events by the caller.

        Args:
            run_messages: The messages to reason about
            stream: Whether to stream reasoning content deltas

        Yields:
            ReasoningEvent objects for each stage of reasoning
        """
        # Get the reasoning model
        reasoning_model: Optional[Model] = self.config.reasoning_model
        reasoning_model_provided = reasoning_model is not None

        if reasoning_model is None:
            yield ReasoningEvent(
                event_type=ReasoningEventType.error,
                error="Reasoning model is None",
            )
            return

        # Yield started event
        yield ReasoningEvent(event_type=ReasoningEventType.started)

        # Check if this is a native reasoning model
        if reasoning_model_provided and self.is_native_reasoning_model(reasoning_model):
            # Use streaming for native models when stream is enabled
            if stream:
                async for event in self._astream_native_reasoning_events(reasoning_model, run_messages):
                    yield event
            else:
                async for event in self._aget_native_reasoning_events(reasoning_model, run_messages):
                    yield event
        else:
            # Use default Chain-of-Thought reasoning
            if reasoning_model_provided:
                log_info(
                    f"Reasoning model: {reasoning_model.__class__.__name__} is not a native reasoning model, "
                    "defaulting to manual Chain-of-Thought reasoning"
                )
            async for event in self._arun_default_reasoning_events(reasoning_model, run_messages):
                yield event

    def _stream_native_reasoning_events(self, model: Model, run_messages: RunMessages) -> Iterator[ReasoningEvent]:
        """Stream native reasoning and yield ReasoningEvent objects."""
        messages = run_messages.get_input_messages()

        for reasoning_delta, result in self.stream_native_reasoning(model, messages):
            if reasoning_delta is not None:
                yield ReasoningEvent(
                    event_type=ReasoningEventType.content_delta,
                    reasoning_content=reasoning_delta,
                )
            if result is not None:
                if not result.success:
                    yield ReasoningEvent(
                        event_type=ReasoningEventType.error,
                        error=result.error,
                    )
                    return
                if result.message:
                    run_messages.messages.append(result.message)
                    yield ReasoningEvent(
                        event_type=ReasoningEventType.completed,
                        reasoning_steps=result.steps,
                        message=result.message,
                        reasoning_messages=result.reasoning_messages,
                    )

    def _get_native_reasoning_events(self, model: Model, run_messages: RunMessages) -> Iterator[ReasoningEvent]:
        """Get native reasoning (non-streaming) and yield ReasoningEvent objects."""
        messages = run_messages.get_input_messages()
        result = self.get_native_reasoning(model, messages)

        if not result.success:
            yield ReasoningEvent(
                event_type=ReasoningEventType.error,
                error=result.error,
            )
            return

        if result.message:
            run_messages.messages.append(result.message)
            yield ReasoningEvent(
                event_type=ReasoningEventType.completed,
                reasoning_steps=result.steps,
                message=result.message,
                reasoning_messages=result.reasoning_messages,
            )

    def _run_default_reasoning_events(self, model: Model, run_messages: RunMessages) -> Iterator[ReasoningEvent]:
        """Run default CoT reasoning and yield ReasoningEvent objects."""
        all_reasoning_steps: List[ReasoningStep] = []

        for reasoning_step, result in self.run_default_reasoning(model, run_messages):
            if reasoning_step is not None:
                all_reasoning_steps.append(reasoning_step)
                yield ReasoningEvent(
                    event_type=ReasoningEventType.step,
                    reasoning_step=reasoning_step,
                )
            if result is not None:
                if not result.success:
                    yield ReasoningEvent(
                        event_type=ReasoningEventType.error,
                        error=result.error,
                    )
                    return

        # Yield completed event with all steps
        if all_reasoning_steps:
            yield ReasoningEvent(
                event_type=ReasoningEventType.completed,
                reasoning_steps=all_reasoning_steps,
            )

    async def _astream_native_reasoning_events(
        self, model: Model, run_messages: RunMessages
    ) -> AsyncIterator[ReasoningEvent]:
        """Stream native reasoning asynchronously and yield ReasoningEvent objects."""
        messages = run_messages.get_input_messages()

        async for reasoning_delta, result in self.astream_native_reasoning(model, messages):
            if reasoning_delta is not None:
                yield ReasoningEvent(
                    event_type=ReasoningEventType.content_delta,
                    reasoning_content=reasoning_delta,
                )
            if result is not None:
                if not result.success:
                    yield ReasoningEvent(
                        event_type=ReasoningEventType.error,
                        error=result.error,
                    )
                    return
                if result.message:
                    run_messages.messages.append(result.message)
                    yield ReasoningEvent(
                        event_type=ReasoningEventType.completed,
                        reasoning_steps=result.steps,
                        message=result.message,
                        reasoning_messages=result.reasoning_messages,
                    )

    async def _aget_native_reasoning_events(
        self, model: Model, run_messages: RunMessages
    ) -> AsyncIterator[ReasoningEvent]:
        """Get native reasoning asynchronously (non-streaming) and yield ReasoningEvent objects."""
        messages = run_messages.get_input_messages()
        result = await self.aget_native_reasoning(model, messages)

        if not result.success:
            yield ReasoningEvent(
                event_type=ReasoningEventType.error,
                error=result.error,
            )
            return

        if result.message:
            run_messages.messages.append(result.message)
            yield ReasoningEvent(
                event_type=ReasoningEventType.completed,
                reasoning_steps=result.steps,
                message=result.message,
                reasoning_messages=result.reasoning_messages,
            )

    async def _arun_default_reasoning_events(
        self, model: Model, run_messages: RunMessages
    ) -> AsyncIterator[ReasoningEvent]:
        """Run default CoT reasoning asynchronously and yield ReasoningEvent objects."""
        all_reasoning_steps: List[ReasoningStep] = []

        async for reasoning_step, result in self.arun_default_reasoning(model, run_messages):
            if reasoning_step is not None:
                all_reasoning_steps.append(reasoning_step)
                yield ReasoningEvent(
                    event_type=ReasoningEventType.step,
                    reasoning_step=reasoning_step,
                )
            if result is not None:
                if not result.success:
                    yield ReasoningEvent(
                        event_type=ReasoningEventType.error,
                        error=result.error,
                    )
                    return

        # Yield completed event with all steps
        if all_reasoning_steps:
            yield ReasoningEvent(
                event_type=ReasoningEventType.completed,
                reasoning_steps=all_reasoning_steps,
            )
