from __future__ import annotations

from collections import deque
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Optional,
    Union,
)

from agno.agent.trait.base import AgentTraitBase
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse
from agno.reasoning.step import ReasoningStep, ReasoningSteps
from agno.run import RunContext
from agno.run.agent import (
    RunOutput,
    RunOutputEvent,
)
from agno.run.messages import RunMessages
from agno.session import AgentSession
from agno.utils.events import (
    create_parser_model_response_completed_event,
    create_parser_model_response_started_event,
    create_reasoning_completed_event,
    create_reasoning_content_delta_event,
    create_reasoning_started_event,
    create_reasoning_step_event,
    handle_event,
)
from agno.utils.log import (
    log_warning,
)
from agno.utils.reasoning import (
    update_run_output_with_reasoning,
)


class AgentResponseTrait(AgentTraitBase):
    def save_run_response_to_file(
        self,
        run_response: RunOutput,
        input: Optional[Union[str, List, Dict, Message, List[Message]]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        if self.save_response_to_file is not None and run_response is not None:
            message_str = None
            if input is not None:
                if isinstance(input, str):
                    message_str = input
                else:
                    log_warning("Did not use input in output file name: input is not a string")
            try:
                from pathlib import Path

                fn = self.save_response_to_file.format(
                    name=self.name,
                    session_id=session_id,
                    user_id=user_id,
                    message=message_str,
                    run_id=run_response.run_id,
                )
                fn_path = Path(fn)
                if not fn_path.parent.exists():
                    fn_path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(run_response.content, str):
                    fn_path.write_text(run_response.content)
                else:
                    import json

                    fn_path.write_text(json.dumps(run_response.content, indent=2))
            except Exception as e:
                log_warning(f"Failed to save output to file: {e}")

    def _calculate_run_metrics(self, messages: List[Message], current_run_metrics: Optional[Metrics] = None) -> Metrics:
        """Sum the metrics of the given messages into a Metrics object"""
        metrics = current_run_metrics or Metrics()

        assistant_message_role = self.model.assistant_message_role if self.model is not None else "assistant"
        for m in messages:
            if m.role == assistant_message_role and m.metrics is not None and m.from_history is False:
                metrics += m.metrics

        # If the run metrics were already initialized, keep the time related metrics
        if current_run_metrics is not None:
            metrics.timer = current_run_metrics.timer
            metrics.duration = current_run_metrics.duration
            metrics.time_to_first_token = current_run_metrics.time_to_first_token

        return metrics

    ###########################################################################
    # Reasoning
    ###########################################################################

    def _handle_reasoning(
        self, run_response: RunOutput, run_messages: RunMessages, run_context: Optional[RunContext] = None
    ) -> None:
        if self.reasoning or self.reasoning_model is not None:
            reasoning_generator = self._reason(
                run_response=run_response, run_messages=run_messages, run_context=run_context, stream_events=False
            )

            # Consume the generator without yielding
            deque(reasoning_generator, maxlen=0)

    def _handle_reasoning_stream(
        self,
        run_response: RunOutput,
        run_messages: RunMessages,
        run_context: Optional[RunContext] = None,
        stream_events: Optional[bool] = None,
    ) -> Iterator[RunOutputEvent]:
        if self.reasoning or self.reasoning_model is not None:
            reasoning_generator = self._reason(
                run_response=run_response,
                run_messages=run_messages,
                run_context=run_context,
                stream_events=stream_events,
            )
            yield from reasoning_generator

    async def _ahandle_reasoning(
        self, run_response: RunOutput, run_messages: RunMessages, run_context: Optional[RunContext] = None
    ) -> None:
        if self.reasoning or self.reasoning_model is not None:
            reason_generator = self._areason(
                run_response=run_response, run_messages=run_messages, run_context=run_context, stream_events=False
            )
            # Consume the generator without yielding
            async for _ in reason_generator:  # type: ignore
                pass

    async def _ahandle_reasoning_stream(
        self,
        run_response: RunOutput,
        run_messages: RunMessages,
        run_context: Optional[RunContext] = None,
        stream_events: Optional[bool] = None,
    ) -> AsyncIterator[RunOutputEvent]:
        if self.reasoning or self.reasoning_model is not None:
            reason_generator = self._areason(
                run_response=run_response,
                run_messages=run_messages,
                run_context=run_context,
                stream_events=stream_events,
            )
            async for item in reason_generator:  # type: ignore
                yield item

    def _format_reasoning_step_content(self, run_response: RunOutput, reasoning_step: ReasoningStep) -> str:
        """Format content for a reasoning step without changing any existing logic."""
        step_content = ""
        if reasoning_step.title:
            step_content += f"## {reasoning_step.title}\n"
        if reasoning_step.reasoning:
            step_content += f"{reasoning_step.reasoning}\n"
        if reasoning_step.action:
            step_content += f"Action: {reasoning_step.action}\n"
        if reasoning_step.result:
            step_content += f"Result: {reasoning_step.result}\n"
        step_content += "\n"

        # Get the current reasoning_content and append this step
        current_reasoning_content = ""
        if hasattr(run_response, "reasoning_content") and run_response.reasoning_content:  # type: ignore
            current_reasoning_content = run_response.reasoning_content  # type: ignore

        # Create updated reasoning_content
        updated_reasoning_content = current_reasoning_content + step_content

        return updated_reasoning_content

    def _handle_reasoning_event(
        self,
        event: "ReasoningEvent",  # type: ignore # noqa: F821
        run_response: RunOutput,
        stream_events: Optional[bool] = None,
    ) -> Iterator[RunOutputEvent]:
        """
        Convert a ReasoningEvent from the ReasoningManager to Agent-specific RunOutputEvents.

        This method handles the conversion of generic reasoning events to Agent events,
        keeping the Agent._reason() method clean and simple.
        """
        from agno.reasoning.manager import ReasoningEventType

        if event.event_type == ReasoningEventType.started:
            if stream_events:
                yield handle_event(  # type: ignore
                    create_reasoning_started_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=self.events_to_skip,  # type: ignore
                    store_events=self.store_events,
                )

        elif event.event_type == ReasoningEventType.content_delta:
            if stream_events and event.reasoning_content:
                yield handle_event(  # type: ignore
                    create_reasoning_content_delta_event(
                        from_run_response=run_response,
                        reasoning_content=event.reasoning_content,
                    ),
                    run_response,
                    events_to_skip=self.events_to_skip,  # type: ignore
                    store_events=self.store_events,
                )

        elif event.event_type == ReasoningEventType.step:
            if event.reasoning_step:
                # Update run_response with this step
                update_run_output_with_reasoning(
                    run_response=run_response,
                    reasoning_steps=[event.reasoning_step],
                    reasoning_agent_messages=[],
                )
                if stream_events:
                    updated_reasoning_content = self._format_reasoning_step_content(
                        run_response=run_response,
                        reasoning_step=event.reasoning_step,
                    )
                    yield handle_event(  # type: ignore
                        create_reasoning_step_event(
                            from_run_response=run_response,
                            reasoning_step=event.reasoning_step,
                            reasoning_content=updated_reasoning_content,
                        ),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

        elif event.event_type == ReasoningEventType.completed:
            if event.message and event.reasoning_steps:
                # This is from native reasoning - update with the message and steps
                update_run_output_with_reasoning(
                    run_response=run_response,
                    reasoning_steps=event.reasoning_steps,
                    reasoning_agent_messages=event.reasoning_messages,
                )
            if stream_events:
                yield handle_event(  # type: ignore
                    create_reasoning_completed_event(
                        from_run_response=run_response,
                        content=ReasoningSteps(reasoning_steps=event.reasoning_steps),
                        content_type=ReasoningSteps.__name__,
                    ),
                    run_response,
                    events_to_skip=self.events_to_skip,  # type: ignore
                    store_events=self.store_events,
                )

        elif event.event_type == ReasoningEventType.error:
            log_warning(f"Reasoning error. {event.error}, continuing regular session...")

    def _reason(
        self,
        run_response: RunOutput,
        run_messages: RunMessages,
        run_context: Optional[RunContext] = None,
        stream_events: Optional[bool] = None,
    ) -> Iterator[RunOutputEvent]:
        """
        Run reasoning using the ReasoningManager.

        Handles both native reasoning models (DeepSeek, Anthropic, etc.) and
        default Chain-of-Thought reasoning with a clean, unified interface.
        """
        from agno.reasoning.manager import ReasoningConfig, ReasoningManager

        # Get the reasoning model (use copy of main model if not provided)
        reasoning_model: Optional[Model] = self.reasoning_model
        if reasoning_model is None and self.model is not None:
            from copy import deepcopy

            reasoning_model = deepcopy(self.model)

        # Create reasoning manager with config
        runtime_tools = self._get_runtime_tools(run_context=run_context)
        manager = ReasoningManager(
            ReasoningConfig(
                reasoning_model=reasoning_model,
                reasoning_agent=self.reasoning_agent,
                min_steps=self.reasoning_min_steps,
                max_steps=self.reasoning_max_steps,
                tools=runtime_tools,
                tool_call_limit=self.tool_call_limit,
                use_json_mode=self.use_json_mode,
                telemetry=self.telemetry,
                debug_mode=self.debug_mode,
                debug_level=self.debug_level,
                run_context=run_context,
            )
        )

        # Use the unified reason() method and convert events
        for event in manager.reason(run_messages, stream=bool(stream_events)):
            yield from self._handle_reasoning_event(event, run_response, stream_events)

    async def _areason(
        self,
        run_response: RunOutput,
        run_messages: RunMessages,
        run_context: Optional[RunContext] = None,
        stream_events: Optional[bool] = None,
    ) -> Any:
        """
        Run reasoning asynchronously using the ReasoningManager.

        Handles both native reasoning models (DeepSeek, Anthropic, etc.) and
        default Chain-of-Thought reasoning with a clean, unified interface.
        """
        from agno.reasoning.manager import ReasoningConfig, ReasoningManager

        # Get the reasoning model (use copy of main model if not provided)
        reasoning_model: Optional[Model] = self.reasoning_model
        if reasoning_model is None and self.model is not None:
            from copy import deepcopy

            reasoning_model = deepcopy(self.model)

        # Create reasoning manager with config
        runtime_tools = self._get_runtime_tools(run_context=run_context)
        manager = ReasoningManager(
            ReasoningConfig(
                reasoning_model=reasoning_model,
                reasoning_agent=self.reasoning_agent,
                min_steps=self.reasoning_min_steps,
                max_steps=self.reasoning_max_steps,
                tools=runtime_tools,
                tool_call_limit=self.tool_call_limit,
                use_json_mode=self.use_json_mode,
                telemetry=self.telemetry,
                debug_mode=self.debug_mode,
                debug_level=self.debug_level,
                run_context=run_context,
            )
        )

        # Use the unified areason() method and convert events
        async for event in manager.areason(run_messages, stream=bool(stream_events)):
            for output_event in self._handle_reasoning_event(event, run_response, stream_events):
                yield output_event

    def _process_parser_response(
        self,
        model_response: ModelResponse,
        run_messages: RunMessages,
        parser_model_response: ModelResponse,
        messages_for_parser_model: list,
    ) -> None:
        """Common logic for processing parser model response."""
        parser_model_response_message: Optional[Message] = None
        for message in reversed(messages_for_parser_model):
            if message.role == "assistant":
                parser_model_response_message = message
                break

        if parser_model_response_message is not None:
            run_messages.messages.append(parser_model_response_message)
            model_response.parsed = parser_model_response.parsed
            model_response.content = parser_model_response.content
        else:
            log_warning("Unable to parse response with parser model")

    def _parse_response_with_parser_model(
        self, model_response: ModelResponse, run_messages: RunMessages, run_context: Optional[RunContext] = None
    ) -> None:
        """Parse the model response using the parser model."""
        if self.parser_model is None:
            return

        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        if output_schema is not None:
            parser_response_format = self._get_response_format(self.parser_model, run_context=run_context)
            messages_for_parser_model = self._get_messages_for_parser_model(
                model_response, parser_response_format, run_context=run_context
            )
            parser_model_response: ModelResponse = self.parser_model.response(
                messages=messages_for_parser_model,
                response_format=parser_response_format,
            )
            self._process_parser_response(
                model_response,
                run_messages,
                parser_model_response,
                messages_for_parser_model,
            )
        else:
            log_warning("A response model is required to parse the response with a parser model")

    async def _aparse_response_with_parser_model(
        self, model_response: ModelResponse, run_messages: RunMessages, run_context: Optional[RunContext] = None
    ) -> None:
        """Parse the model response using the parser model."""
        if self.parser_model is None:
            return

        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        if output_schema is not None:
            parser_response_format = self._get_response_format(self.parser_model, run_context=run_context)
            messages_for_parser_model = self._get_messages_for_parser_model(
                model_response, parser_response_format, run_context=run_context
            )
            parser_model_response: ModelResponse = await self.parser_model.aresponse(
                messages=messages_for_parser_model,
                response_format=parser_response_format,
            )
            self._process_parser_response(
                model_response,
                run_messages,
                parser_model_response,
                messages_for_parser_model,
            )
        else:
            log_warning("A response model is required to parse the response with a parser model")

    def _parse_response_with_parser_model_stream(
        self,
        session: AgentSession,
        run_response: RunOutput,
        stream_events: bool = True,
        run_context: Optional[RunContext] = None,
    ):
        """Parse the model response using the parser model"""
        if self.parser_model is not None:
            # Get output_schema from run_context
            output_schema = run_context.output_schema if run_context else None

            if output_schema is not None:
                if stream_events:
                    yield handle_event(
                        create_parser_model_response_started_event(run_response),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                parser_model_response = ModelResponse(content="")
                parser_response_format = self._get_response_format(self.parser_model, run_context=run_context)
                messages_for_parser_model = self._get_messages_for_parser_model_stream(
                    run_response, parser_response_format, run_context=run_context
                )
                for model_response_event in self.parser_model.response_stream(
                    messages=messages_for_parser_model,
                    response_format=parser_response_format,
                    stream_model_response=False,
                ):
                    yield from self._handle_model_response_chunk(
                        session=session,
                        run_response=run_response,
                        model_response=parser_model_response,
                        model_response_event=model_response_event,
                        parse_structured_output=True,
                        stream_events=stream_events,
                        run_context=run_context,
                    )

                parser_model_response_message: Optional[Message] = None
                for message in reversed(messages_for_parser_model):
                    if message.role == "assistant":
                        parser_model_response_message = message
                        break
                if parser_model_response_message is not None:
                    if run_response.messages is not None:
                        run_response.messages.append(parser_model_response_message)
                else:
                    log_warning("Unable to parse response with parser model")

                if stream_events:
                    yield handle_event(
                        create_parser_model_response_completed_event(run_response),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

            else:
                log_warning("A response model is required to parse the response with a parser model")

    async def _aparse_response_with_parser_model_stream(
        self,
        session: AgentSession,
        run_response: RunOutput,
        stream_events: bool = True,
        run_context: Optional[RunContext] = None,
    ):
        """Parse the model response using the parser model stream."""
        if self.parser_model is not None:
            # Get output_schema from run_context
            output_schema = run_context.output_schema if run_context else None

            if output_schema is not None:
                if stream_events:
                    yield handle_event(
                        create_parser_model_response_started_event(run_response),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                parser_model_response = ModelResponse(content="")
                parser_response_format = self._get_response_format(self.parser_model, run_context=run_context)
                messages_for_parser_model = self._get_messages_for_parser_model_stream(
                    run_response, parser_response_format, run_context=run_context
                )
                model_response_stream = self.parser_model.aresponse_stream(
                    messages=messages_for_parser_model,
                    response_format=parser_response_format,
                    stream_model_response=False,
                )
                async for model_response_event in model_response_stream:  # type: ignore
                    for event in self._handle_model_response_chunk(
                        session=session,
                        run_response=run_response,
                        model_response=parser_model_response,
                        model_response_event=model_response_event,
                        parse_structured_output=True,
                        stream_events=stream_events,
                        run_context=run_context,
                    ):
                        yield event

                parser_model_response_message: Optional[Message] = None
                for message in reversed(messages_for_parser_model):
                    if message.role == "assistant":
                        parser_model_response_message = message
                        break
                if parser_model_response_message is not None:
                    if run_response.messages is not None:
                        run_response.messages.append(parser_model_response_message)
                else:
                    log_warning("Unable to parse response with parser model")

                if stream_events:
                    yield handle_event(
                        create_parser_model_response_completed_event(run_response),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )
            else:
                log_warning("A response model is required to parse the response with a parser model")

    def _generate_response_with_output_model(self, model_response: ModelResponse, run_messages: RunMessages) -> None:
        """Parse the model response using the output model."""
        if self.output_model is None:
            return

        messages_for_output_model = self._get_messages_for_output_model(run_messages.messages)
        output_model_response: ModelResponse = self.output_model.response(messages=messages_for_output_model)
        model_response.content = output_model_response.content

    def _generate_response_with_output_model_stream(
        self,
        session: AgentSession,
        run_response: RunOutput,
        run_messages: RunMessages,
        stream_events: bool = False,
    ):
        """Parse the model response using the output model."""
        from agno.utils.events import (
            create_output_model_response_completed_event,
            create_output_model_response_started_event,
        )

        if self.output_model is None:
            return

        if stream_events:
            yield handle_event(
                create_output_model_response_started_event(run_response),
                run_response,
                events_to_skip=self.events_to_skip,  # type: ignore
                store_events=self.store_events,
            )

        messages_for_output_model = self._get_messages_for_output_model(run_messages.messages)

        model_response = ModelResponse(content="")

        for model_response_event in self.output_model.response_stream(messages=messages_for_output_model):
            yield from self._handle_model_response_chunk(
                session=session,
                run_response=run_response,
                model_response=model_response,
                model_response_event=model_response_event,
                stream_events=stream_events,
            )

        if stream_events:
            yield handle_event(
                create_output_model_response_completed_event(run_response),
                run_response,
                events_to_skip=self.events_to_skip,  # type: ignore
                store_events=self.store_events,
            )

        # Build a list of messages that should be added to the RunResponse
        messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
        # Update the RunResponse messages
        run_response.messages = messages_for_run_response
        # Update the RunResponse metrics
        run_response.metrics = self._calculate_run_metrics(messages_for_run_response)

    async def _agenerate_response_with_output_model(self, model_response: ModelResponse, run_messages: RunMessages):
        """Parse the model response using the output model."""
        if self.output_model is None:
            return

        messages_for_output_model = self._get_messages_for_output_model(run_messages.messages)
        output_model_response: ModelResponse = await self.output_model.aresponse(messages=messages_for_output_model)
        model_response.content = output_model_response.content

    async def _agenerate_response_with_output_model_stream(
        self,
        session: AgentSession,
        run_response: RunOutput,
        run_messages: RunMessages,
        stream_events: bool = False,
    ):
        """Parse the model response using the output model."""
        from agno.utils.events import (
            create_output_model_response_completed_event,
            create_output_model_response_started_event,
        )

        if self.output_model is None:
            return

        if stream_events:
            yield handle_event(
                create_output_model_response_started_event(run_response),
                run_response,
                events_to_skip=self.events_to_skip,  # type: ignore
                store_events=self.store_events,
            )

        messages_for_output_model = self._get_messages_for_output_model(run_messages.messages)

        model_response = ModelResponse(content="")

        model_response_stream = self.output_model.aresponse_stream(messages=messages_for_output_model)

        async for model_response_event in model_response_stream:
            for event in self._handle_model_response_chunk(
                session=session,
                run_response=run_response,
                model_response=model_response,
                model_response_event=model_response_event,
                stream_events=stream_events,
            ):
                yield event

        if stream_events:
            yield handle_event(
                create_output_model_response_completed_event(run_response),
                run_response,
                events_to_skip=self.events_to_skip,  # type: ignore
                store_events=self.store_events,
            )

        # Build a list of messages that should be added to the RunResponse
        messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
        # Update the RunResponse messages
        run_response.messages = messages_for_run_response
        # Update the RunResponse metrics
        run_response.metrics = self._calculate_run_metrics(messages_for_run_response)
