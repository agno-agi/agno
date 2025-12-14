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
from typing import (
    TYPE_CHECKING,
    Any,
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
from agno.run.messages import RunMessages
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_debug, log_error, log_warning

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.run.agent import RunOutput


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
    session_state: Optional[Dict[str, Any]] = None
    dependencies: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


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
            session_state=self.config.session_state,
            dependencies=self.config.dependencies,
            metadata=self.config.metadata,
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
            session_state=self.config.session_state,
            dependencies=self.config.dependencies,
            metadata=self.config.metadata,
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

        try:
            if model_type == "deepseek":
                from agno.reasoning.deepseek import get_deepseek_reasoning

                log_debug("Starting DeepSeek Reasoning", center=True, symbol="=")
                reasoning_message = get_deepseek_reasoning(reasoning_agent, messages)

            elif model_type == "anthropic":
                from agno.reasoning.anthropic import get_anthropic_reasoning

                log_debug("Starting Anthropic Claude Reasoning", center=True, symbol="=")
                reasoning_message = get_anthropic_reasoning(reasoning_agent, messages)

            elif model_type == "openai":
                from agno.reasoning.openai import get_openai_reasoning

                log_debug("Starting OpenAI Reasoning", center=True, symbol="=")
                reasoning_message = get_openai_reasoning(reasoning_agent, messages)

            elif model_type == "groq":
                from agno.reasoning.groq import get_groq_reasoning

                log_debug("Starting Groq Reasoning", center=True, symbol="=")
                reasoning_message = get_groq_reasoning(reasoning_agent, messages)

            elif model_type == "ollama":
                from agno.reasoning.ollama import get_ollama_reasoning

                log_debug("Starting Ollama Reasoning", center=True, symbol="=")
                reasoning_message = get_ollama_reasoning(reasoning_agent, messages)

            elif model_type == "ai_foundry":
                from agno.reasoning.azure_ai_foundry import get_ai_foundry_reasoning

                log_debug("Starting Azure AI Foundry Reasoning", center=True, symbol="=")
                reasoning_message = get_ai_foundry_reasoning(reasoning_agent, messages)

            elif model_type == "gemini":
                from agno.reasoning.gemini import get_gemini_reasoning

                log_debug("Starting Gemini Reasoning", center=True, symbol="=")
                reasoning_message = get_gemini_reasoning(reasoning_agent, messages)

            elif model_type == "vertexai":
                from agno.reasoning.vertexai import get_vertexai_reasoning

                log_debug("Starting VertexAI Reasoning", center=True, symbol="=")
                reasoning_message = get_vertexai_reasoning(reasoning_agent, messages)

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

        try:
            if model_type == "deepseek":
                from agno.reasoning.deepseek import aget_deepseek_reasoning

                log_debug("Starting DeepSeek Reasoning", center=True, symbol="=")
                reasoning_message = await aget_deepseek_reasoning(reasoning_agent, messages)

            elif model_type == "anthropic":
                from agno.reasoning.anthropic import aget_anthropic_reasoning

                log_debug("Starting Anthropic Claude Reasoning", center=True, symbol="=")
                reasoning_message = await aget_anthropic_reasoning(reasoning_agent, messages)

            elif model_type == "openai":
                from agno.reasoning.openai import aget_openai_reasoning

                log_debug("Starting OpenAI Reasoning", center=True, symbol="=")
                reasoning_message = await aget_openai_reasoning(reasoning_agent, messages)

            elif model_type == "groq":
                from agno.reasoning.groq import aget_groq_reasoning

                log_debug("Starting Groq Reasoning", center=True, symbol="=")
                reasoning_message = await aget_groq_reasoning(reasoning_agent, messages)

            elif model_type == "ollama":
                from agno.reasoning.ollama import get_ollama_reasoning

                log_debug("Starting Ollama Reasoning", center=True, symbol="=")
                reasoning_message = get_ollama_reasoning(reasoning_agent, messages)

            elif model_type == "ai_foundry":
                from agno.reasoning.azure_ai_foundry import get_ai_foundry_reasoning

                log_debug("Starting Azure AI Foundry Reasoning", center=True, symbol="=")
                reasoning_message = get_ai_foundry_reasoning(reasoning_agent, messages)

            elif model_type == "gemini":
                from agno.reasoning.gemini import aget_gemini_reasoning

                log_debug("Starting Gemini Reasoning", center=True, symbol="=")
                reasoning_message = await aget_gemini_reasoning(reasoning_agent, messages)

            elif model_type == "vertexai":
                from agno.reasoning.vertexai import aget_vertexai_reasoning

                log_debug("Starting VertexAI Reasoning", center=True, symbol="=")
                reasoning_message = await aget_vertexai_reasoning(reasoning_agent, messages)

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
            and not isinstance(reasoning_agent.output_schema, type)
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
            and not isinstance(reasoning_agent.output_schema, type)
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
                reasoning_agent_response: RunOutput = await reasoning_agent.arun(
                    input=run_messages.get_input_messages()
                )

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
