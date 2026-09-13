"""
ReasoningManager - Centralized manager for native reasoning model operations.

This module consolidates reasoning logic from the Agent class into a single,
maintainable manager that handles native reasoning models (DeepSeek-R1, OpenAI o1/o3,
Anthropic Claude with thinking, Gemini Flash Thinking, etc.) in both streaming
and non-streaming modes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    TYPE_CHECKING,
    AsyncIterator,
    Iterator,
    List,
    Literal,
    Optional,
    Tuple,
)

from agno.models.base import Model
from agno.models.message import Message
from agno.reasoning.step import ReasoningStep
from agno.run.base import RunContext
from agno.run.messages import RunMessages
from agno.utils.log import log_debug, log_error, log_warning

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.metrics import RunMetrics


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
    telemetry: bool = True
    debug_mode: bool = False
    debug_level: Literal[1, 2] = 1
    run_context: Optional[RunContext] = None
    run_metrics: Optional["RunMetrics"] = None


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
    Centralized manager for reasoning operations with native reasoning models.

    Supports native reasoning models: DeepSeek-R1, OpenAI o1/o3, Anthropic Claude
    with thinking, Gemini Flash Thinking, Groq, Ollama, VertexAI, Azure AI Foundry.
    """

    def __init__(self, config: ReasoningConfig):
        self.config = config
        self._reasoning_agent: Optional["Agent"] = None
        self._model_type: Optional[str] = None
        self._model_type_key: Optional[Tuple[str, str]] = None

    @property
    def reasoning_model(self) -> Optional[Model]:
        return self.config.reasoning_model

    def _detect_model_type(self, model: Model) -> Optional[str]:
        """Detect the type of reasoning model.

        Detection can hit the provider API, and it runs on every reasoning entry point, so the
        result is memoized per model for the life of this manager.
        """
        cache_key = (model.__class__.__name__, model.id)
        if self._model_type_key == cache_key:
            return self._model_type

        model_type = self._detect_model_type_uncached(model)
        self._model_type_key = cache_key
        self._model_type = model_type
        return model_type

    async def _adetect_model_type(self, model: Model) -> Optional[str]:
        """Async variant of _detect_model_type.

        Some detectors call the provider API synchronously, which would block the event loop for
        the length of the request, so the uncached detection runs in a worker thread.
        """
        cache_key = (model.__class__.__name__, model.id)
        if self._model_type_key == cache_key:
            return self._model_type

        model_type = await asyncio.to_thread(self._detect_model_type_uncached, model)
        self._model_type_key = cache_key
        self._model_type = model_type
        return model_type

    def _detect_model_type_uncached(self, model: Model) -> Optional[str]:
        from agno.reasoning.anthropic import is_anthropic_reasoning_model
        from agno.reasoning.azure_ai_foundry import is_ai_foundry_reasoning_model
        from agno.reasoning.deepseek import is_deepseek_reasoning_model
        from agno.reasoning.gemini import is_gemini_reasoning_model
        from agno.reasoning.groq import is_groq_reasoning_model
        from agno.reasoning.moonshot import is_moonshot_reasoning_model
        from agno.reasoning.ollama import is_ollama_reasoning_model
        from agno.reasoning.openai import is_openai_reasoning_model
        from agno.reasoning.openrouter import is_openrouter_reasoning_model
        from agno.reasoning.vertexai import is_vertexai_reasoning_model

        if is_deepseek_reasoning_model(model):
            return "deepseek"
        if is_anthropic_reasoning_model(model):
            return "anthropic"
        # OpenRouter and Moonshot are OpenAILike subclasses, so they must be checked before the OpenAI detector.
        if is_openrouter_reasoning_model(model):
            return "openrouter"
        if is_moonshot_reasoning_model(model):
            return "moonshot"
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

    def is_native_reasoning_model(self, model: Optional[Model] = None) -> bool:
        """Check if the model is a native reasoning model."""
        model = model or self.config.reasoning_model
        if model is None:
            return False
        return self._detect_model_type(model) is not None

    async def ais_native_reasoning_model(self, model: Optional[Model] = None) -> bool:
        """Check if the model is a native reasoning model, without blocking the event loop."""
        model = model or self.config.reasoning_model
        if model is None:
            return False
        return await self._adetect_model_type(model) is not None

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
        run_metrics = self.config.run_metrics

        try:
            if model_type == "deepseek":
                from agno.reasoning.deepseek import get_deepseek_reasoning

                log_debug("Starting DeepSeek Reasoning", center=True, symbol="=")
                reasoning_message = get_deepseek_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "moonshot":
                from agno.reasoning.moonshot import get_moonshot_reasoning

                log_debug("Starting Kimi Reasoning", center=True, symbol="=")
                reasoning_message = get_moonshot_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "anthropic":
                from agno.reasoning.anthropic import get_anthropic_reasoning

                log_debug("Starting Anthropic Claude Reasoning", center=True, symbol="=")
                reasoning_message = get_anthropic_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type in ("openai", "openrouter"):
                from agno.reasoning.openai import get_openai_reasoning

                log_debug("Starting OpenAI Reasoning", center=True, symbol="=")
                reasoning_message = get_openai_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "groq":
                from agno.reasoning.groq import get_groq_reasoning

                log_debug("Starting Groq Reasoning", center=True, symbol="=")
                reasoning_message = get_groq_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "ollama":
                from agno.reasoning.ollama import get_ollama_reasoning

                log_debug("Starting Ollama Reasoning", center=True, symbol="=")
                reasoning_message = get_ollama_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "ai_foundry":
                from agno.reasoning.azure_ai_foundry import get_ai_foundry_reasoning

                log_debug("Starting Azure AI Foundry Reasoning", center=True, symbol="=")
                reasoning_message = get_ai_foundry_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "gemini":
                from agno.reasoning.gemini import get_gemini_reasoning

                log_debug("Starting Gemini Reasoning", center=True, symbol="=")
                reasoning_message = get_gemini_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "vertexai":
                from agno.reasoning.vertexai import get_vertexai_reasoning

                log_debug("Starting VertexAI Reasoning", center=True, symbol="=")
                reasoning_message = get_vertexai_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

        except Exception as e:
            log_error(f"Reasoning error: {str(e)}")
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
        model_type = await self._adetect_model_type(model)
        if model_type is None:
            return ReasoningResult(success=False, error="Not a native reasoning model")

        reasoning_agent = self._get_reasoning_agent(model)
        reasoning_message: Optional[Message] = None
        run_metrics = self.config.run_metrics

        try:
            if model_type == "deepseek":
                from agno.reasoning.deepseek import aget_deepseek_reasoning

                log_debug("Starting DeepSeek Reasoning", center=True, symbol="=")
                reasoning_message = await aget_deepseek_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "moonshot":
                from agno.reasoning.moonshot import aget_moonshot_reasoning

                log_debug("Starting Kimi Reasoning", center=True, symbol="=")
                reasoning_message = await aget_moonshot_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "anthropic":
                from agno.reasoning.anthropic import aget_anthropic_reasoning

                log_debug("Starting Anthropic Claude Reasoning", center=True, symbol="=")
                reasoning_message = await aget_anthropic_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type in ("openai", "openrouter"):
                from agno.reasoning.openai import aget_openai_reasoning

                log_debug("Starting OpenAI Reasoning", center=True, symbol="=")
                reasoning_message = await aget_openai_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "groq":
                from agno.reasoning.groq import aget_groq_reasoning

                log_debug("Starting Groq Reasoning", center=True, symbol="=")
                reasoning_message = await aget_groq_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "ollama":
                from agno.reasoning.ollama import aget_ollama_reasoning

                log_debug("Starting Ollama Reasoning", center=True, symbol="=")
                reasoning_message = await aget_ollama_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "ai_foundry":
                from agno.reasoning.azure_ai_foundry import aget_ai_foundry_reasoning

                log_debug("Starting Azure AI Foundry Reasoning", center=True, symbol="=")
                reasoning_message = await aget_ai_foundry_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "gemini":
                from agno.reasoning.gemini import aget_gemini_reasoning

                log_debug("Starting Gemini Reasoning", center=True, symbol="=")
                reasoning_message = await aget_gemini_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

            elif model_type == "vertexai":
                from agno.reasoning.vertexai import aget_vertexai_reasoning

                log_debug("Starting VertexAI Reasoning", center=True, symbol="=")
                reasoning_message = await aget_vertexai_reasoning(reasoning_agent, messages, run_metrics=run_metrics)

        except Exception as e:
            log_error(f"Reasoning error: {str(e)}")
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

        elif model_type == "moonshot":
            from agno.reasoning.moonshot import get_moonshot_reasoning_stream

            log_debug("Starting Kimi Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            for reasoning_delta, message in get_moonshot_reasoning_stream(reasoning_agent, messages):
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

        elif model_type in ("openai", "openrouter"):
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
        model_type = await self._adetect_model_type(model)
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

        elif model_type == "moonshot":
            from agno.reasoning.moonshot import aget_moonshot_reasoning_stream

            log_debug("Starting Kimi Reasoning (streaming)", center=True, symbol="=")
            final_message = None
            async for reasoning_delta, message in aget_moonshot_reasoning_stream(reasoning_agent, messages):
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

        elif model_type in ("openai", "openrouter"):
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

        # Use streaming for native models when stream is enabled
        if reasoning_model_provided and self.is_native_reasoning_model(reasoning_model):
            if stream:
                yield from self._stream_native_reasoning_events(reasoning_model, run_messages)
            else:
                yield from self._get_native_reasoning_events(reasoning_model, run_messages)
        else:
            # Non-native reasoning models are not supported
            log_warning(
                f"Reasoning model {reasoning_model.__class__.__name__} is not a native reasoning model. "
                "Reasoning requires a native model (DeepSeek-R1, OpenAI o1/o3, Claude with thinking, etc.) "
                "or use ReasoningTools for manual chain-of-thought."
            )
            yield ReasoningEvent(
                event_type=ReasoningEventType.error,
                error=f"Model {reasoning_model.__class__.__name__} is not a native reasoning model",
            )

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

        # Use streaming for native models when stream is enabled
        if reasoning_model_provided and await self.ais_native_reasoning_model(reasoning_model):
            if stream:
                async for event in self._astream_native_reasoning_events(reasoning_model, run_messages):
                    yield event
            else:
                async for event in self._aget_native_reasoning_events(reasoning_model, run_messages):
                    yield event
        else:
            # Non-native reasoning models are not supported
            log_warning(
                f"Reasoning model {reasoning_model.__class__.__name__} is not a native reasoning model. "
                "Reasoning requires a native model (DeepSeek-R1, OpenAI o1/o3, Claude with thinking, etc.) "
                "or use ReasoningTools for manual chain-of-thought."
            )
            yield ReasoningEvent(
                event_type=ReasoningEventType.error,
                error=f"Model {reasoning_model.__class__.__name__} is not a native reasoning model",
            )

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
