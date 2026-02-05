from __future__ import annotations

from asyncio import CancelledError, Task, create_task
from collections import deque
from concurrent.futures import Future
from inspect import iscoroutinefunction
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Type,
    Union,
    cast,
    get_args,
)
from uuid import uuid4

from agno.agent.trait.base import AgentTraitBase

from agno.exceptions import (
    InputCheckError,
    OutputCheckError,
)
from agno.media import Audio
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.reasoning.step import ReasoningStep, ReasoningSteps

from agno.run import RunContext, RunStatus
from agno.run.agent import (
    RunEvent,
    RunInput,
    RunOutput,
    RunOutputEvent,
)
from agno.run.messages import RunMessages
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutputEvent

from agno.session import AgentSession
from agno.tools import Toolkit
from agno.tools.function import Function

from agno.utils.events import (
    create_compression_completed_event,
    create_compression_started_event,
    create_model_request_completed_event,
    create_model_request_started_event,
    create_post_hook_completed_event,
    create_post_hook_started_event,
    create_pre_hook_completed_event,
    create_pre_hook_started_event,
    create_reasoning_completed_event,
    create_reasoning_started_event,
    create_reasoning_step_event,
    create_run_output_content_event,
    create_run_paused_event,
    create_tool_call_completed_event,
    create_tool_call_error_event,
    create_tool_call_started_event,
    handle_event,
)
from agno.utils.hooks import (
    copy_args_for_background,
    filter_hook_args,
    should_run_hook_in_background,
)
from agno.utils.log import (
    log_debug,
    log_error,
    log_exception,
    log_warning,
)
from agno.utils.merge_dict import merge_dictionaries
from agno.utils.reasoning import (
    add_reasoning_metrics_to_metadata,
)
from agno.utils.response import (
    get_paused_content,
)
from agno.utils.string import parse_response_dict_str, parse_response_model_str

if TYPE_CHECKING:
    from pydantic import BaseModel


class AgentHooksTrait(AgentTraitBase):
    def _execute_pre_hooks(
        self,
        hooks: Optional[List[Callable[..., Any]]],
        run_response: RunOutput,
        run_input: RunInput,
        session: AgentSession,
        run_context: RunContext,
        user_id: Optional[str] = None,
        debug_mode: Optional[bool] = None,
        stream_events: bool = False,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> Iterator[RunOutputEvent]:
        """Execute multiple pre-hook functions in succession."""
        if hooks is None:
            return
        # Prepare arguments for this hook
        all_args = {
            "run_input": run_input,
            "run_context": run_context,
            "agent": self,
            "session": session,
            "user_id": user_id,
            "debug_mode": debug_mode or self.debug_mode,
        }

        # Check if background_tasks is available and ALL hooks should run in background
        # Note: Pre-hooks running in background may not be able to modify run_input
        if self._run_hooks_in_background is True and background_tasks is not None:
            # Schedule ALL pre_hooks as background tasks
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            for hook in hooks:
                # Filter arguments to only include those that the hook accepts
                filtered_args = filter_hook_args(hook, bg_args)

                # Add to background tasks
                background_tasks.add_task(hook, **filtered_args)
            return

        all_args.update(kwargs)

        for i, hook in enumerate(hooks):
            # Check if this specific hook should run in background (via @hook decorator)
            if should_run_hook_in_background(hook) and background_tasks is not None:
                # Copy args to prevent race conditions
                bg_args = copy_args_for_background(all_args)
                filtered_args = filter_hook_args(hook, bg_args)
                background_tasks.add_task(hook, **filtered_args)
                continue

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_response,
                    event=create_pre_hook_started_event(
                        from_run_response=run_response,
                        run_input=run_input,
                        pre_hook_name=hook.__name__,
                    ),
                    events_to_skip=self.events_to_skip,  # type: ignore
                    store_events=self.store_events,
                )
            try:
                # Filter arguments to only include those that the hook accepts
                filtered_args = filter_hook_args(hook, all_args)

                hook(**filtered_args)

                if stream_events:
                    yield handle_event(  # type: ignore
                        run_response=run_response,
                        event=create_pre_hook_completed_event(
                            from_run_response=run_response,
                            run_input=run_input,
                            pre_hook_name=hook.__name__,
                        ),
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

            except (InputCheckError, OutputCheckError) as e:
                raise e
            except Exception as e:
                log_error(f"Pre-hook #{i + 1} execution failed: {str(e)}")
                log_exception(e)
            finally:
                # Reset global log mode incase an agent in the pre-hook changed it
                self._set_debug(debug_mode=debug_mode)

        # Update the input on the run_response
        run_response.input = run_input

    async def _aexecute_pre_hooks(
        self,
        hooks: Optional[List[Callable[..., Any]]],
        run_response: RunOutput,
        run_input: RunInput,
        run_context: RunContext,
        session: AgentSession,
        user_id: Optional[str] = None,
        debug_mode: Optional[bool] = None,
        stream_events: bool = False,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[RunOutputEvent]:
        """Execute multiple pre-hook functions in succession (async version)."""
        if hooks is None:
            return
        # Prepare arguments for this hook
        all_args = {
            "run_input": run_input,
            "agent": self,
            "session": session,
            "run_context": run_context,
            "user_id": user_id,
            "debug_mode": debug_mode or self.debug_mode,
        }

        # Check if background_tasks is available and ALL hooks should run in background
        # Note: Pre-hooks running in background may not be able to modify run_input
        if self._run_hooks_in_background is True and background_tasks is not None:
            # Schedule ALL pre_hooks as background tasks
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            for hook in hooks:
                # Filter arguments to only include those that the hook accepts
                filtered_args = filter_hook_args(hook, bg_args)

                # Add to background tasks (both sync and async hooks supported)
                background_tasks.add_task(hook, **filtered_args)
            return

        all_args.update(kwargs)

        for i, hook in enumerate(hooks):
            # Check if this specific hook should run in background (via @hook decorator)
            if should_run_hook_in_background(hook) and background_tasks is not None:
                # Copy args to prevent race conditions
                bg_args = copy_args_for_background(all_args)
                filtered_args = filter_hook_args(hook, bg_args)
                background_tasks.add_task(hook, **filtered_args)
                continue

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_response,
                    event=create_pre_hook_started_event(
                        from_run_response=run_response,
                        run_input=run_input,
                        pre_hook_name=hook.__name__,
                    ),
                    events_to_skip=self.events_to_skip,  # type: ignore
                    store_events=self.store_events,
                )
            try:
                # Filter arguments to only include those that the hook accepts
                filtered_args = filter_hook_args(hook, all_args)

                if iscoroutinefunction(hook):
                    await hook(**filtered_args)
                else:
                    # Synchronous function
                    hook(**filtered_args)

                if stream_events:
                    yield handle_event(  # type: ignore
                        run_response=run_response,
                        event=create_pre_hook_completed_event(
                            from_run_response=run_response,
                            run_input=run_input,
                            pre_hook_name=hook.__name__,
                        ),
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

            except (InputCheckError, OutputCheckError) as e:
                raise e
            except Exception as e:
                log_error(f"Pre-hook #{i + 1} execution failed: {str(e)}")
                log_exception(e)
            finally:
                # Reset global log mode incase an agent in the pre-hook changed it
                self._set_debug(debug_mode=debug_mode)

        # Update the input on the run_response
        run_response.input = run_input

    def _execute_post_hooks(
        self,
        hooks: Optional[List[Callable[..., Any]]],
        run_output: RunOutput,
        session: AgentSession,
        run_context: RunContext,
        user_id: Optional[str] = None,
        debug_mode: Optional[bool] = None,
        stream_events: bool = False,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> Iterator[RunOutputEvent]:
        """Execute multiple post-hook functions in succession."""
        if hooks is None:
            return

        # Prepare arguments for this hook
        all_args = {
            "run_output": run_output,
            "agent": self,
            "session": session,
            "user_id": user_id,
            "run_context": run_context,
            "debug_mode": debug_mode or self.debug_mode,
        }

        # Check if background_tasks is available and ALL hooks should run in background
        if self._run_hooks_in_background is True and background_tasks is not None:
            # Schedule ALL post_hooks as background tasks
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            for hook in hooks:
                # Filter arguments to only include those that the hook accepts
                filtered_args = filter_hook_args(hook, bg_args)

                # Add to background tasks
                background_tasks.add_task(hook, **filtered_args)
            return

        all_args.update(kwargs)

        for i, hook in enumerate(hooks):
            # Check if this specific hook should run in background (via @hook decorator)
            if should_run_hook_in_background(hook) and background_tasks is not None:
                # Copy args to prevent race conditions
                bg_args = copy_args_for_background(all_args)
                filtered_args = filter_hook_args(hook, bg_args)
                background_tasks.add_task(hook, **filtered_args)
                continue

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_output,
                    event=create_post_hook_started_event(
                        from_run_response=run_output,
                        post_hook_name=hook.__name__,
                    ),
                    events_to_skip=self.events_to_skip,  # type: ignore
                    store_events=self.store_events,
                )
            try:
                # Filter arguments to only include those that the hook accepts
                filtered_args = filter_hook_args(hook, all_args)

                hook(**filtered_args)

                if stream_events:
                    yield handle_event(  # type: ignore
                        run_response=run_output,
                        event=create_post_hook_completed_event(
                            from_run_response=run_output,
                            post_hook_name=hook.__name__,
                        ),
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )
            except (InputCheckError, OutputCheckError) as e:
                raise e
            except Exception as e:
                log_error(f"Post-hook #{i + 1} execution failed: {str(e)}")
                log_exception(e)
            finally:
                # Reset global log mode incase an agent in the pre-hook changed it
                self._set_debug(debug_mode=debug_mode)

    async def _aexecute_post_hooks(
        self,
        hooks: Optional[List[Callable[..., Any]]],
        run_output: RunOutput,
        run_context: RunContext,
        session: AgentSession,
        user_id: Optional[str] = None,
        debug_mode: Optional[bool] = None,
        stream_events: bool = False,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[RunOutputEvent]:
        """Execute multiple post-hook functions in succession (async version)."""
        if hooks is None:
            return

        # Prepare arguments for this hook
        all_args = {
            "run_output": run_output,
            "agent": self,
            "session": session,
            "run_context": run_context,
            "user_id": user_id,
            "debug_mode": debug_mode or self.debug_mode,
        }
        # Check if background_tasks is available and ALL hooks should run in background
        if self._run_hooks_in_background is True and background_tasks is not None:
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            for hook in hooks:
                # Filter arguments to only include those that the hook accepts
                filtered_args = filter_hook_args(hook, bg_args)

                # Add to background tasks (both sync and async hooks supported)
                background_tasks.add_task(hook, **filtered_args)
            return

        all_args.update(kwargs)

        for i, hook in enumerate(hooks):
            # Check if this specific hook should run in background (via @hook decorator)
            if should_run_hook_in_background(hook) and background_tasks is not None:
                # Copy args to prevent race conditions
                bg_args = copy_args_for_background(all_args)
                filtered_args = filter_hook_args(hook, bg_args)
                background_tasks.add_task(hook, **filtered_args)
                continue

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_output,
                    event=create_post_hook_started_event(
                        from_run_response=run_output,
                        post_hook_name=hook.__name__,
                    ),
                    events_to_skip=self.events_to_skip,  # type: ignore
                    store_events=self.store_events,
                )
            try:
                # Filter arguments to only include those that the hook accepts
                filtered_args = filter_hook_args(hook, all_args)
                from inspect import iscoroutinefunction

                if iscoroutinefunction(hook):
                    await hook(**filtered_args)
                else:
                    hook(**filtered_args)

                if stream_events:
                    yield handle_event(  # type: ignore
                        run_response=run_output,
                        event=create_post_hook_completed_event(
                            from_run_response=run_output,
                            post_hook_name=hook.__name__,
                        ),
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

            except (InputCheckError, OutputCheckError) as e:
                raise e
            except Exception as e:
                log_error(f"Post-hook #{i + 1} execution failed: {str(e)}")
                log_exception(e)
            finally:
                # Reset global log mode incase an agent in the pre-hook changed it
                self._set_debug(debug_mode=debug_mode)

    def _handle_agent_run_paused(
        self,
        run_response: RunOutput,
        session: AgentSession,
        user_id: Optional[str] = None,
    ) -> RunOutput:
        # Set the run response to paused

        run_response.status = RunStatus.paused
        if not run_response.content:
            run_response.content = get_paused_content(run_response)

        self._cleanup_and_store(run_response=run_response, session=session, user_id=user_id)

        log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")

        # We return and await confirmation/completion for the tools that require it
        return run_response

    def _handle_agent_run_paused_stream(
        self,
        run_response: RunOutput,
        session: AgentSession,
        user_id: Optional[str] = None,
    ) -> Iterator[RunOutputEvent]:
        # Set the run response to paused

        run_response.status = RunStatus.paused
        if not run_response.content:
            run_response.content = get_paused_content(run_response)

        # We return and await confirmation/completion for the tools that require it
        pause_event = handle_event(
            create_run_paused_event(
                from_run_response=run_response,
                tools=run_response.tools,
                requirements=run_response.requirements,
            ),
            run_response,
            events_to_skip=self.events_to_skip,  # type: ignore
            store_events=self.store_events,
        )

        self._cleanup_and_store(run_response=run_response, session=session, user_id=user_id)

        yield pause_event  # type: ignore

        log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")

    async def _ahandle_agent_run_paused(
        self,
        run_response: RunOutput,
        session: AgentSession,
        user_id: Optional[str] = None,
    ) -> RunOutput:
        # Set the run response to paused

        run_response.status = RunStatus.paused
        if not run_response.content:
            run_response.content = get_paused_content(run_response)

        await self._acleanup_and_store(run_response=run_response, session=session, user_id=user_id)

        log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")

        # We return and await confirmation/completion for the tools that require it
        return run_response

    async def _ahandle_agent_run_paused_stream(
        self,
        run_response: RunOutput,
        session: AgentSession,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[RunOutputEvent]:
        # Set the run response to paused

        run_response.status = RunStatus.paused
        if not run_response.content:
            run_response.content = get_paused_content(run_response)

        # We return and await confirmation/completion for the tools that require it
        pause_event = handle_event(
            create_run_paused_event(
                from_run_response=run_response,
                tools=run_response.tools,
                requirements=run_response.requirements,
            ),
            run_response,
            events_to_skip=self.events_to_skip,  # type: ignore
            store_events=self.store_events,
        )

        await self._acleanup_and_store(run_response=run_response, session=session, user_id=user_id)

        yield pause_event  # type: ignore

        log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")

    def _convert_response_to_structured_format(
        self, run_response: Union[RunOutput, ModelResponse], run_context: Optional[RunContext] = None
    ):
        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        # Convert the response to the structured format if needed
        if output_schema is not None:
            # If the output schema is a dict, do not convert it into a BaseModel
            if isinstance(output_schema, dict):
                if isinstance(run_response.content, str):
                    parsed_dict = parse_response_dict_str(run_response.content)
                    if parsed_dict is not None:
                        run_response.content = parsed_dict
                        if isinstance(run_response, RunOutput):
                            run_response.content_type = "dict"
                    else:
                        log_warning("Failed to parse JSON response against the provided output schema.")
            # If the output schema is a Pydantic model and parse_response is True, parse it into a BaseModel
            elif not isinstance(run_response.content, output_schema):
                if isinstance(run_response.content, str) and self.parse_response:
                    try:
                        structured_output = parse_response_model_str(run_response.content, output_schema)

                        # Update RunOutput
                        if structured_output is not None:
                            run_response.content = structured_output
                            if isinstance(run_response, RunOutput):
                                run_response.content_type = output_schema.__name__
                        else:
                            log_warning("Failed to convert response to output_schema")
                    except Exception as e:
                        log_warning(f"Failed to convert response to output model: {e}")
                else:
                    log_warning("Something went wrong. Run response content is not a string")

    def _handle_external_execution_update(self, run_messages: RunMessages, tool: ToolExecution):
        self.model = cast(Model, self.model)

        if tool.result is not None:
            for msg in run_messages.messages:
                # Skip if the message is already in the run_messages
                if msg.tool_call_id == tool.tool_call_id:
                    break

            run_messages.messages.append(
                Message(
                    role=self.model.tool_message_role,
                    content=tool.result,
                    tool_call_id=tool.tool_call_id,
                    tool_name=tool.tool_name,
                    tool_args=tool.tool_args,
                    tool_call_error=tool.tool_call_error,
                    stop_after_tool_call=tool.stop_after_tool_call,
                )
            )
            tool.external_execution_required = False
        else:
            raise ValueError(f"Tool {tool.tool_name} requires external execution, cannot continue run")

    def _handle_user_input_update(self, tool: ToolExecution):
        for field in tool.user_input_schema or []:
            if not tool.tool_args:
                tool.tool_args = {}
            tool.tool_args[field.name] = field.value

    def _handle_get_user_input_tool_update(self, run_messages: RunMessages, tool: ToolExecution):
        import json

        self.model = cast(Model, self.model)
        # Skipping tool without user_input_schema so that tool_call_id is not repeated
        if not hasattr(tool, "user_input_schema") or not tool.user_input_schema:
            return
        user_input_result = [
            {"name": user_input_field.name, "value": user_input_field.value}
            for user_input_field in tool.user_input_schema or []
        ]
        # Add the tool call result to the run_messages
        run_messages.messages.append(
            Message(
                role=self.model.tool_message_role,
                content=f"User inputs retrieved: {json.dumps(user_input_result)}",
                tool_call_id=tool.tool_call_id,
                tool_name=tool.tool_name,
                tool_args=tool.tool_args,
                metrics=Metrics(duration=0),
            )
        )

    def _run_tool(
        self,
        run_response: RunOutput,
        run_messages: RunMessages,
        tool: ToolExecution,
        functions: Optional[Dict[str, Function]] = None,
        stream_events: bool = False,
    ) -> Iterator[RunOutputEvent]:
        from agno.run.agent import CustomEvent

        self.model = cast(Model, self.model)
        # Execute the tool
        function_call = self.model.get_function_call_to_run_from_tool_execution(tool, functions)
        function_call_results: List[Message] = []

        for call_result in self.model.run_function_call(
            function_call=function_call,
            function_call_results=function_call_results,
        ):
            if isinstance(call_result, ModelResponse):
                if call_result.event == ModelResponseEvent.tool_call_started.value:
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_tool_call_started_event(from_run_response=run_response, tool=tool),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )

                if call_result.event == ModelResponseEvent.tool_call_completed.value and call_result.tool_executions:
                    tool_execution = call_result.tool_executions[0]
                    tool.result = tool_execution.result
                    tool.tool_call_error = tool_execution.tool_call_error
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_tool_call_completed_event(
                                from_run_response=run_response, tool=tool, content=call_result.content
                            ),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                        if tool.tool_call_error:
                            yield handle_event(  # type: ignore
                                create_tool_call_error_event(
                                    from_run_response=run_response, tool=tool, error=str(tool.result)
                                ),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )
            # Yield CustomEvent instances from sync tool generators
            elif isinstance(call_result, CustomEvent):
                if stream_events:
                    yield call_result  # type: ignore

        if len(function_call_results) > 0:
            run_messages.messages.extend(function_call_results)

    def _reject_tool_call(
        self, run_messages: RunMessages, tool: ToolExecution, functions: Optional[Dict[str, Function]] = None
    ):
        self.model = cast(Model, self.model)
        function_call = self.model.get_function_call_to_run_from_tool_execution(tool, functions)
        function_call.error = tool.confirmation_note or "Function call was rejected by the user"
        function_call_result = self.model.create_function_call_result(
            function_call=function_call,
            success=False,
        )
        run_messages.messages.append(function_call_result)

    async def _arun_tool(
        self,
        run_response: RunOutput,
        run_messages: RunMessages,
        tool: ToolExecution,
        functions: Optional[Dict[str, Function]] = None,
        stream_events: bool = False,
    ) -> AsyncIterator[RunOutputEvent]:
        from agno.run.agent import CustomEvent

        self.model = cast(Model, self.model)

        # Execute the tool
        function_call = self.model.get_function_call_to_run_from_tool_execution(tool, functions)
        function_call_results: List[Message] = []

        async for call_result in self.model.arun_function_calls(
            function_calls=[function_call],
            function_call_results=function_call_results,
            skip_pause_check=True,
        ):
            if isinstance(call_result, ModelResponse):
                if call_result.event == ModelResponseEvent.tool_call_started.value:
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_tool_call_started_event(from_run_response=run_response, tool=tool),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                if call_result.event == ModelResponseEvent.tool_call_completed.value and call_result.tool_executions:
                    tool_execution = call_result.tool_executions[0]
                    tool.result = tool_execution.result
                    tool.tool_call_error = tool_execution.tool_call_error
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_tool_call_completed_event(
                                from_run_response=run_response, tool=tool, content=call_result.content
                            ),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                        if tool.tool_call_error:
                            yield handle_event(  # type: ignore
                                create_tool_call_error_event(
                                    from_run_response=run_response, tool=tool, error=str(tool.result)
                                ),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )
            # Yield CustomEvent instances from async tool generators
            elif isinstance(call_result, CustomEvent):
                if stream_events:
                    yield call_result  # type: ignore

        if len(function_call_results) > 0:
            run_messages.messages.extend(function_call_results)

    def _handle_tool_call_updates(
        self, run_response: RunOutput, run_messages: RunMessages, tools: List[Union[Function, dict]]
    ):
        self.model = cast(Model, self.model)
        _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

        for _t in run_response.tools or []:
            # Case 1: Handle confirmed tools and execute them
            if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
                # Tool is confirmed and hasn't been run before
                if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                    # Consume the generator without yielding
                    deque(self._run_tool(run_response, run_messages, _t, functions=_functions), maxlen=0)
                else:
                    self._reject_tool_call(run_messages, _t, functions=_functions)
                    _t.confirmed = False
                    _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                    _t.tool_call_error = True
                _t.requires_confirmation = False

            # Case 2: Handle external execution required tools
            elif _t.external_execution_required is not None and _t.external_execution_required is True:
                self._handle_external_execution_update(run_messages=run_messages, tool=_t)

            # Case 3: Agentic user input required
            elif (
                _t.tool_name == "get_user_input"
                and _t.requires_user_input is not None
                and _t.requires_user_input is True
            ):
                self._handle_get_user_input_tool_update(run_messages=run_messages, tool=_t)
                _t.requires_user_input = False

            # Case 4: Handle user input required tools
            elif _t.requires_user_input is not None and _t.requires_user_input is True:
                self._handle_user_input_update(tool=_t)
                _t.requires_user_input = False
                _t.answered = True
                # Consume the generator without yielding
                deque(self._run_tool(run_response, run_messages, _t, functions=_functions), maxlen=0)

    def _handle_tool_call_updates_stream(
        self,
        run_response: RunOutput,
        run_messages: RunMessages,
        tools: List[Union[Function, dict]],
        stream_events: bool = False,
    ) -> Iterator[RunOutputEvent]:
        self.model = cast(Model, self.model)
        _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

        for _t in run_response.tools or []:
            # Case 1: Handle confirmed tools and execute them
            if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
                # Tool is confirmed and hasn't been run before
                if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                    yield from self._run_tool(
                        run_response, run_messages, _t, functions=_functions, stream_events=stream_events
                    )
                else:
                    self._reject_tool_call(run_messages, _t, functions=_functions)
                    _t.confirmed = False
                    _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                    _t.tool_call_error = True
                _t.requires_confirmation = False

            # Case 2: Handle external execution required tools
            elif _t.external_execution_required is not None and _t.external_execution_required is True:
                self._handle_external_execution_update(run_messages=run_messages, tool=_t)

            # Case 3: Agentic user input required
            elif (
                _t.tool_name == "get_user_input"
                and _t.requires_user_input is not None
                and _t.requires_user_input is True
            ):
                self._handle_get_user_input_tool_update(run_messages=run_messages, tool=_t)
                _t.requires_user_input = False
                _t.answered = True

            # Case 4: Handle user input required tools
            elif _t.requires_user_input is not None and _t.requires_user_input is True:
                self._handle_user_input_update(tool=_t)
                yield from self._run_tool(
                    run_response, run_messages, _t, functions=_functions, stream_events=stream_events
                )
                _t.requires_user_input = False
                _t.answered = True

    async def _ahandle_tool_call_updates(
        self, run_response: RunOutput, run_messages: RunMessages, tools: List[Union[Function, dict]]
    ):
        self.model = cast(Model, self.model)
        _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

        for _t in run_response.tools or []:
            # Case 1: Handle confirmed tools and execute them
            if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
                # Tool is confirmed and hasn't been run before
                if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                    async for _ in self._arun_tool(run_response, run_messages, _t, functions=_functions):
                        pass
                else:
                    self._reject_tool_call(run_messages, _t, functions=_functions)
                    _t.confirmed = False
                    _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                    _t.tool_call_error = True
                _t.requires_confirmation = False

            # Case 2: Handle external execution required tools
            elif _t.external_execution_required is not None and _t.external_execution_required is True:
                self._handle_external_execution_update(run_messages=run_messages, tool=_t)
            # Case 3: Agentic user input required
            elif (
                _t.tool_name == "get_user_input"
                and _t.requires_user_input is not None
                and _t.requires_user_input is True
            ):
                self._handle_get_user_input_tool_update(run_messages=run_messages, tool=_t)
                _t.requires_user_input = False
                _t.answered = True
            # Case 4: Handle user input required tools
            elif _t.requires_user_input is not None and _t.requires_user_input is True:
                self._handle_user_input_update(tool=_t)
                async for _ in self._arun_tool(run_response, run_messages, _t, functions=_functions):
                    pass
                _t.requires_user_input = False
                _t.answered = True

    async def _ahandle_tool_call_updates_stream(
        self,
        run_response: RunOutput,
        run_messages: RunMessages,
        tools: List[Union[Function, dict]],
        stream_events: bool = False,
    ) -> AsyncIterator[RunOutputEvent]:
        self.model = cast(Model, self.model)
        _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

        for _t in run_response.tools or []:
            # Case 1: Handle confirmed tools and execute them
            if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
                # Tool is confirmed and hasn't been run before
                if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                    async for event in self._arun_tool(
                        run_response, run_messages, _t, functions=_functions, stream_events=stream_events
                    ):
                        yield event
                else:
                    self._reject_tool_call(run_messages, _t, functions=_functions)
                    _t.confirmed = False
                    _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                    _t.tool_call_error = True
                _t.requires_confirmation = False

            # Case 2: Handle external execution required tools
            elif _t.external_execution_required is not None and _t.external_execution_required is True:
                self._handle_external_execution_update(run_messages=run_messages, tool=_t)
            # Case 3: Agentic user input required
            elif (
                _t.tool_name == "get_user_input"
                and _t.requires_user_input is not None
                and _t.requires_user_input is True
            ):
                self._handle_get_user_input_tool_update(run_messages=run_messages, tool=_t)
                _t.requires_user_input = False
                _t.answered = True
            # # Case 4: Handle user input required tools
            elif _t.requires_user_input is not None and _t.requires_user_input is True:
                self._handle_user_input_update(tool=_t)
                async for event in self._arun_tool(
                    run_response, run_messages, _t, functions=_functions, stream_events=stream_events
                ):
                    yield event
                _t.requires_user_input = False
                _t.answered = True

    def _update_run_response(
        self,
        model_response: ModelResponse,
        run_response: RunOutput,
        run_messages: RunMessages,
        run_context: Optional[RunContext] = None,
    ):
        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        # Handle structured outputs
        if output_schema is not None and model_response.parsed is not None:
            # We get native structured outputs from the model
            if self._model_should_return_structured_output(run_context=run_context):
                # Update the run_response content with the structured output
                run_response.content = model_response.parsed
                # Update the run_response content_type with the structured output class name
                run_response.content_type = "dict" if isinstance(output_schema, dict) else output_schema.__name__
        else:
            # Update the run_response content with the model response content
            run_response.content = model_response.content

        # Update the run_response reasoning content with the model response reasoning content
        if model_response.reasoning_content is not None:
            run_response.reasoning_content = model_response.reasoning_content
        if model_response.redacted_reasoning_content is not None:
            if run_response.reasoning_content is None:
                run_response.reasoning_content = model_response.redacted_reasoning_content
            else:
                run_response.reasoning_content += model_response.redacted_reasoning_content

        # Update the run_response citations with the model response citations
        if model_response.citations is not None:
            run_response.citations = model_response.citations
        if model_response.provider_data is not None:
            run_response.model_provider_data = model_response.provider_data

        # Update the run_response tools with the model response tool_executions
        if model_response.tool_executions is not None:
            if run_response.tools is None:
                run_response.tools = model_response.tool_executions
            else:
                run_response.tools.extend(model_response.tool_executions)

            # For Reasoning/Thinking/Knowledge Tools update reasoning_content in RunOutput
            for tool_call in model_response.tool_executions:
                tool_name = tool_call.tool_name or ""
                if tool_name.lower() in ["think", "analyze"]:
                    tool_args = tool_call.tool_args or {}
                    self._update_reasoning_content_from_tool_call(
                        run_response=run_response,
                        tool_name=tool_name,
                        tool_args=tool_args,
                    )

        # Update the run_response audio with the model response audio
        if model_response.audio is not None:
            run_response.response_audio = model_response.audio

        # Update the run_response created_at with the model response created_at
        run_response.created_at = model_response.created_at

        # Build a list of messages that should be added to the RunOutput
        messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
        # Update the RunOutput messages
        run_response.messages = messages_for_run_response
        # Update the RunOutput metrics
        run_response.metrics = self._calculate_run_metrics(
            messages=messages_for_run_response, current_run_metrics=run_response.metrics
        )

    def _update_session_metrics(self, session: AgentSession, run_response: RunOutput):
        """Calculate session metrics"""
        session_metrics = self._get_session_metrics(session=session)
        # Add the metrics for the current run to the session metrics
        if session_metrics is None:
            return
        if run_response.metrics is not None:
            session_metrics += run_response.metrics
        session_metrics.time_to_first_token = None
        if session.session_data is not None:
            session.session_data["session_metrics"] = session_metrics

    def _handle_model_response_stream(
        self,
        session: AgentSession,
        run_response: RunOutput,
        run_messages: RunMessages,
        tools: Optional[List[Union[Function, dict]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream_events: bool = False,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
    ) -> Iterator[RunOutputEvent]:
        self.model = cast(Model, self.model)

        reasoning_state = {
            "reasoning_started": False,
            "reasoning_time_taken": 0.0,
        }
        model_response = ModelResponse(content="")

        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None
        should_parse_structured_output = output_schema is not None and self.parse_response and self.parser_model is None

        stream_model_response = True
        if should_parse_structured_output:
            log_debug("Response model set, model response is not streamed.")
            stream_model_response = False

        for model_response_event in self.model.response_stream(
            messages=run_messages.messages,
            response_format=response_format,
            tools=tools,
            tool_choice=self.tool_choice,
            tool_call_limit=self.tool_call_limit,
            stream_model_response=stream_model_response,
            run_response=run_response,
            send_media_to_model=self.send_media_to_model,
            compression_manager=self.compression_manager if self.compress_tool_results else None,
        ):
            # Handle LLM request events and compression events from ModelResponse
            if isinstance(model_response_event, ModelResponse):
                if model_response_event.event == ModelResponseEvent.model_request_started.value:
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_model_request_started_event(
                                from_run_response=run_response,
                                model=self.model.id,
                                model_provider=self.model.provider,
                            ),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                    continue

                if model_response_event.event == ModelResponseEvent.model_request_completed.value:
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_model_request_completed_event(
                                from_run_response=run_response,
                                model=self.model.id,
                                model_provider=self.model.provider,
                                input_tokens=model_response_event.input_tokens,
                                output_tokens=model_response_event.output_tokens,
                                total_tokens=model_response_event.total_tokens,
                                time_to_first_token=model_response_event.time_to_first_token,
                                reasoning_tokens=model_response_event.reasoning_tokens,
                                cache_read_tokens=model_response_event.cache_read_tokens,
                                cache_write_tokens=model_response_event.cache_write_tokens,
                            ),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                    continue

                # Handle compression events
                if model_response_event.event == ModelResponseEvent.compression_started.value:
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_compression_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                    continue

                if model_response_event.event == ModelResponseEvent.compression_completed.value:
                    if stream_events:
                        stats = model_response_event.compression_stats or {}
                        yield handle_event(  # type: ignore
                            create_compression_completed_event(
                                from_run_response=run_response,
                                tool_results_compressed=stats.get("tool_results_compressed"),
                                original_size=stats.get("original_size"),
                                compressed_size=stats.get("compressed_size"),
                            ),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                    continue

            yield from self._handle_model_response_chunk(
                session=session,
                run_response=run_response,
                model_response=model_response,
                model_response_event=model_response_event,
                reasoning_state=reasoning_state,
                parse_structured_output=should_parse_structured_output,
                stream_events=stream_events,
                session_state=session_state,
                run_context=run_context,
            )

        # Update RunOutput
        # Build a list of messages that should be added to the RunOutput
        messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
        # Update the RunOutput messages
        run_response.messages = messages_for_run_response
        # Update the RunOutput metrics
        run_response.metrics = self._calculate_run_metrics(
            messages=messages_for_run_response, current_run_metrics=run_response.metrics
        )

        # Determine reasoning completed
        if stream_events and reasoning_state["reasoning_started"]:
            all_reasoning_steps: List[ReasoningStep] = []
            if run_response and run_response.reasoning_steps:
                all_reasoning_steps = cast(List[ReasoningStep], run_response.reasoning_steps)

            if all_reasoning_steps:
                add_reasoning_metrics_to_metadata(
                    run_response=run_response,
                    reasoning_time_taken=reasoning_state["reasoning_time_taken"],
                )
                yield handle_event(  # type: ignore
                    create_reasoning_completed_event(
                        from_run_response=run_response,
                        content=ReasoningSteps(reasoning_steps=all_reasoning_steps),
                        content_type=ReasoningSteps.__name__,
                    ),
                    run_response,
                    events_to_skip=self.events_to_skip,  # type: ignore
                    store_events=self.store_events,
                )

        # Update the run_response audio if streaming
        if model_response.audio is not None:
            run_response.response_audio = model_response.audio

    async def _ahandle_model_response_stream(
        self,
        session: AgentSession,
        run_response: RunOutput,
        run_messages: RunMessages,
        tools: Optional[List[Union[Function, dict]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream_events: bool = False,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
    ) -> AsyncIterator[RunOutputEvent]:
        self.model = cast(Model, self.model)

        reasoning_state = {
            "reasoning_started": False,
            "reasoning_time_taken": 0.0,
        }
        model_response = ModelResponse(content="")

        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None
        should_parse_structured_output = output_schema is not None and self.parse_response and self.parser_model is None

        stream_model_response = True
        if should_parse_structured_output:
            log_debug("Response model set, model response is not streamed.")
            stream_model_response = False

        model_response_stream = self.model.aresponse_stream(
            messages=run_messages.messages,
            response_format=response_format,
            tools=tools,
            tool_choice=self.tool_choice,
            tool_call_limit=self.tool_call_limit,
            stream_model_response=stream_model_response,
            run_response=run_response,
            send_media_to_model=self.send_media_to_model,
            compression_manager=self.compression_manager if self.compress_tool_results else None,
        )  # type: ignore

        async for model_response_event in model_response_stream:  # type: ignore
            # Handle LLM request events and compression events from ModelResponse
            if isinstance(model_response_event, ModelResponse):
                if model_response_event.event == ModelResponseEvent.model_request_started.value:
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_model_request_started_event(
                                from_run_response=run_response,
                                model=self.model.id,
                                model_provider=self.model.provider,
                            ),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                    continue

                if model_response_event.event == ModelResponseEvent.model_request_completed.value:
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_model_request_completed_event(
                                from_run_response=run_response,
                                model=self.model.id,
                                model_provider=self.model.provider,
                                input_tokens=model_response_event.input_tokens,
                                output_tokens=model_response_event.output_tokens,
                                total_tokens=model_response_event.total_tokens,
                                time_to_first_token=model_response_event.time_to_first_token,
                                reasoning_tokens=model_response_event.reasoning_tokens,
                                cache_read_tokens=model_response_event.cache_read_tokens,
                                cache_write_tokens=model_response_event.cache_write_tokens,
                            ),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                    continue

                # Handle compression events
                if model_response_event.event == ModelResponseEvent.compression_started.value:
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_compression_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                    continue

                if model_response_event.event == ModelResponseEvent.compression_completed.value:
                    if stream_events:
                        stats = model_response_event.compression_stats or {}
                        yield handle_event(  # type: ignore
                            create_compression_completed_event(
                                from_run_response=run_response,
                                tool_results_compressed=stats.get("tool_results_compressed"),
                                original_size=stats.get("original_size"),
                                compressed_size=stats.get("compressed_size"),
                            ),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )
                    continue

            for event in self._handle_model_response_chunk(
                session=session,
                run_response=run_response,
                model_response=model_response,
                model_response_event=model_response_event,
                reasoning_state=reasoning_state,
                parse_structured_output=should_parse_structured_output,
                stream_events=stream_events,
                session_state=session_state,
                run_context=run_context,
            ):
                yield event

        # Update RunOutput
        # Build a list of messages that should be added to the RunOutput
        messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
        # Update the RunOutput messages
        run_response.messages = messages_for_run_response
        # Update the RunOutput metrics
        run_response.metrics = self._calculate_run_metrics(
            messages=messages_for_run_response, current_run_metrics=run_response.metrics
        )

        if stream_events and reasoning_state["reasoning_started"]:
            all_reasoning_steps: List[ReasoningStep] = []
            if run_response and run_response.reasoning_steps:
                all_reasoning_steps = cast(List[ReasoningStep], run_response.reasoning_steps)

            if all_reasoning_steps:
                add_reasoning_metrics_to_metadata(
                    run_response=run_response,
                    reasoning_time_taken=reasoning_state["reasoning_time_taken"],
                )
                yield handle_event(  # type: ignore
                    create_reasoning_completed_event(
                        from_run_response=run_response,
                        content=ReasoningSteps(reasoning_steps=all_reasoning_steps),
                        content_type=ReasoningSteps.__name__,
                    ),
                    run_response,
                    events_to_skip=self.events_to_skip,  # type: ignore
                    store_events=self.store_events,
                )

        # Update the run_response audio if streaming
        if model_response.audio is not None:
            run_response.response_audio = model_response.audio

    def _handle_model_response_chunk(
        self,
        session: AgentSession,
        run_response: RunOutput,
        model_response: ModelResponse,
        model_response_event: Union[ModelResponse, RunOutputEvent, TeamRunOutputEvent],
        reasoning_state: Optional[Dict[str, Any]] = None,
        parse_structured_output: bool = False,
        stream_events: bool = False,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
    ) -> Iterator[RunOutputEvent]:
        from agno.run.workflow import WorkflowRunOutputEvent

        if (
            isinstance(model_response_event, tuple(get_args(RunOutputEvent)))
            or isinstance(model_response_event, tuple(get_args(TeamRunOutputEvent)))
            or isinstance(model_response_event, tuple(get_args(WorkflowRunOutputEvent)))
        ):
            if model_response_event.event == RunEvent.custom_event:  # type: ignore
                model_response_event.agent_id = self.id  # type: ignore
                model_response_event.agent_name = self.name  # type: ignore
                model_response_event.session_id = session.session_id  # type: ignore
                model_response_event.run_id = run_response.run_id  # type: ignore

            # We just bubble the event up
            yield handle_event(  # type: ignore
                model_response_event,  # type: ignore
                run_response,
                events_to_skip=self.events_to_skip,  # type: ignore
                store_events=self.store_events,
            )
        else:
            model_response_event = cast(ModelResponse, model_response_event)
            # If the model response is an assistant_response, yield a RunOutput
            if model_response_event.event == ModelResponseEvent.assistant_response.value:
                content_type = "str"

                # Process content and thinking
                if model_response_event.content is not None:
                    if parse_structured_output:
                        model_response.content = model_response_event.content
                        self._convert_response_to_structured_format(model_response, run_context=run_context)

                        # Get output_schema from run_context
                        output_schema = run_context.output_schema if run_context else None
                        content_type = "dict" if isinstance(output_schema, dict) else output_schema.__name__  # type: ignore
                        run_response.content = model_response.content
                        run_response.content_type = content_type
                    else:
                        model_response.content = (model_response.content or "") + model_response_event.content
                        run_response.content = model_response.content
                        run_response.content_type = "str"

                # Process reasoning content
                if model_response_event.reasoning_content is not None:
                    model_response.reasoning_content = (
                        model_response.reasoning_content or ""
                    ) + model_response_event.reasoning_content
                    run_response.reasoning_content = model_response.reasoning_content

                if model_response_event.redacted_reasoning_content is not None:
                    if not model_response.reasoning_content:
                        model_response.reasoning_content = model_response_event.redacted_reasoning_content
                    else:
                        model_response.reasoning_content += model_response_event.redacted_reasoning_content
                    run_response.reasoning_content = model_response.reasoning_content

                # Handle provider data (one chunk)
                if model_response_event.provider_data is not None:
                    run_response.model_provider_data = model_response_event.provider_data

                # Handle citations (one chunk)
                if model_response_event.citations is not None:
                    run_response.citations = model_response_event.citations

                # Only yield if we have content to show
                if content_type != "str":
                    yield handle_event(  # type: ignore
                        create_run_output_content_event(
                            from_run_response=run_response,
                            content=model_response.content,
                            content_type=content_type,
                        ),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )
                elif (
                    model_response_event.content is not None
                    or model_response_event.reasoning_content is not None
                    or model_response_event.redacted_reasoning_content is not None
                    or model_response_event.citations is not None
                    or model_response_event.provider_data is not None
                ):
                    yield handle_event(  # type: ignore
                        create_run_output_content_event(
                            from_run_response=run_response,
                            content=model_response_event.content,
                            reasoning_content=model_response_event.reasoning_content,
                            redacted_reasoning_content=model_response_event.redacted_reasoning_content,
                            citations=model_response_event.citations,
                            model_provider_data=model_response_event.provider_data,
                        ),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                # Process audio
                if model_response_event.audio is not None:
                    if model_response.audio is None:
                        model_response.audio = Audio(id=str(uuid4()), content=b"", transcript="")

                    if model_response_event.audio.id is not None:
                        model_response.audio.id = model_response_event.audio.id  # type: ignore

                    if model_response_event.audio.content is not None:
                        # Handle both base64 string and bytes content
                        if isinstance(model_response_event.audio.content, str):
                            # Decode base64 string to bytes
                            try:
                                import base64

                                decoded_content = base64.b64decode(model_response_event.audio.content)
                                if model_response.audio.content is None:
                                    model_response.audio.content = b""
                                model_response.audio.content += decoded_content
                            except Exception:
                                # If decode fails, encode string as bytes
                                if model_response.audio.content is None:
                                    model_response.audio.content = b""
                                model_response.audio.content += model_response_event.audio.content.encode("utf-8")
                        elif isinstance(model_response_event.audio.content, bytes):
                            # Content is already bytes
                            if model_response.audio.content is None:
                                model_response.audio.content = b""
                            model_response.audio.content += model_response_event.audio.content

                    if model_response_event.audio.transcript is not None:
                        model_response.audio.transcript += model_response_event.audio.transcript  # type: ignore

                    if model_response_event.audio.expires_at is not None:
                        model_response.audio.expires_at = model_response_event.audio.expires_at  # type: ignore
                    if model_response_event.audio.mime_type is not None:
                        model_response.audio.mime_type = model_response_event.audio.mime_type  # type: ignore
                    if model_response_event.audio.sample_rate is not None:
                        model_response.audio.sample_rate = model_response_event.audio.sample_rate
                    if model_response_event.audio.channels is not None:
                        model_response.audio.channels = model_response_event.audio.channels

                    # Yield the audio and transcript bit by bit
                    run_response.response_audio = Audio(
                        id=model_response_event.audio.id,
                        content=model_response_event.audio.content,
                        transcript=model_response_event.audio.transcript,
                        sample_rate=model_response_event.audio.sample_rate,
                        channels=model_response_event.audio.channels,
                    )
                    run_response.created_at = model_response_event.created_at

                    yield handle_event(  # type: ignore
                        create_run_output_content_event(
                            from_run_response=run_response,
                            response_audio=run_response.response_audio,
                        ),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                if model_response_event.images is not None:
                    yield handle_event(  # type: ignore
                        create_run_output_content_event(
                            from_run_response=run_response,
                            image=model_response_event.images[-1],
                        ),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                    if model_response.images is None:
                        model_response.images = []
                    model_response.images.extend(model_response_event.images)
                    # Store media in run_response if store_media is enabled
                    if self.store_media:
                        for image in model_response_event.images:
                            if run_response.images is None:
                                run_response.images = []
                            run_response.images.append(image)

            # Handle tool interruption events (HITL flow)
            elif model_response_event.event == ModelResponseEvent.tool_call_paused.value:
                # Add tool calls to the run_response
                tool_executions_list = model_response_event.tool_executions
                if tool_executions_list is not None:
                    # Add tool calls to the agent.run_response
                    if run_response.tools is None:
                        run_response.tools = tool_executions_list
                    else:
                        run_response.tools.extend(tool_executions_list)
                    # Add requirement to the run_response
                    if run_response.requirements is None:
                        run_response.requirements = []
                    run_response.requirements.append(RunRequirement(tool_execution=tool_executions_list[-1]))

            # If the model response is a tool_call_started, add the tool call to the run_response
            elif (
                model_response_event.event == ModelResponseEvent.tool_call_started.value
            ):  # Add tool calls to the run_response
                tool_executions_list = model_response_event.tool_executions
                if tool_executions_list is not None:
                    # Add tool calls to the agent.run_response
                    if run_response.tools is None:
                        run_response.tools = tool_executions_list
                    else:
                        run_response.tools.extend(tool_executions_list)

                    # Yield each tool call started event
                    if stream_events:
                        for tool in tool_executions_list:
                            yield handle_event(  # type: ignore
                                create_tool_call_started_event(from_run_response=run_response, tool=tool),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )

            # If the model response is a tool_call_completed, update the existing tool call in the run_response
            elif model_response_event.event == ModelResponseEvent.tool_call_completed.value:
                if model_response_event.updated_session_state is not None:
                    # update the session_state for RunOutput
                    if session_state is not None:
                        merge_dictionaries(session_state, model_response_event.updated_session_state)
                    # update the DB session
                    if session.session_data is not None and session.session_data.get("session_state") is not None:
                        merge_dictionaries(
                            session.session_data["session_state"], model_response_event.updated_session_state
                        )

                if model_response_event.images is not None:
                    for image in model_response_event.images:
                        if run_response.images is None:
                            run_response.images = []
                        run_response.images.append(image)

                if model_response_event.videos is not None:
                    for video in model_response_event.videos:
                        if run_response.videos is None:
                            run_response.videos = []
                        run_response.videos.append(video)

                if model_response_event.audios is not None:
                    for audio in model_response_event.audios:
                        if run_response.audio is None:
                            run_response.audio = []
                        run_response.audio.append(audio)

                if model_response_event.files is not None:
                    for file_obj in model_response_event.files:
                        if run_response.files is None:
                            run_response.files = []
                        run_response.files.append(file_obj)

                reasoning_step: Optional[ReasoningStep] = None

                tool_executions_list = model_response_event.tool_executions
                if tool_executions_list is not None:
                    # Update the existing tool call in the run_response
                    if run_response.tools:
                        # Create a mapping of tool_call_id to index
                        tool_call_index_map = {
                            tc.tool_call_id: i for i, tc in enumerate(run_response.tools) if tc.tool_call_id is not None
                        }
                        # Process tool calls
                        for tool_call_dict in tool_executions_list:
                            tool_call_id = tool_call_dict.tool_call_id or ""
                            index = tool_call_index_map.get(tool_call_id)
                            if index is not None:
                                run_response.tools[index] = tool_call_dict
                    else:
                        run_response.tools = tool_executions_list

                    # Only iterate through new tool calls
                    for tool_call in tool_executions_list:
                        tool_name = tool_call.tool_name or ""
                        if tool_name.lower() in ["think", "analyze"]:
                            tool_args = tool_call.tool_args or {}

                            reasoning_step = self._update_reasoning_content_from_tool_call(
                                run_response=run_response,
                                tool_name=tool_name,
                                tool_args=tool_args,
                            )

                            tool_call_metrics = tool_call.metrics

                            if (
                                tool_call_metrics is not None
                                and tool_call_metrics.duration is not None
                                and reasoning_state is not None
                            ):
                                reasoning_state["reasoning_time_taken"] = reasoning_state[
                                    "reasoning_time_taken"
                                ] + float(tool_call_metrics.duration)

                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_tool_call_completed_event(
                                    from_run_response=run_response, tool=tool_call, content=model_response_event.content
                                ),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )
                            if tool_call.tool_call_error:
                                yield handle_event(  # type: ignore
                                    create_tool_call_error_event(
                                        from_run_response=run_response, tool=tool_call, error=str(tool_call.result)
                                    ),
                                    run_response,
                                    events_to_skip=self.events_to_skip,  # type: ignore
                                    store_events=self.store_events,
                                )

                if stream_events:
                    if reasoning_step is not None:
                        if reasoning_state and not reasoning_state["reasoning_started"]:
                            yield handle_event(  # type: ignore
                                create_reasoning_started_event(from_run_response=run_response),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )
                            reasoning_state["reasoning_started"] = True

                        yield handle_event(  # type: ignore
                            create_reasoning_step_event(
                                from_run_response=run_response,
                                reasoning_step=reasoning_step,
                                reasoning_content=run_response.reasoning_content or "",
                            ),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )

    def _make_cultural_knowledge(
        self,
        run_messages: RunMessages,
    ):
        if (
            run_messages.user_message is not None
            and self.culture_manager is not None
            and self.update_cultural_knowledge
        ):
            log_debug("Creating cultural knowledge.")
            self.culture_manager.create_cultural_knowledge(message=run_messages.user_message.get_content_string())

    async def _acreate_cultural_knowledge(
        self,
        run_messages: RunMessages,
    ):
        if (
            run_messages.user_message is not None
            and self.culture_manager is not None
            and self.update_cultural_knowledge
        ):
            log_debug("Creating cultural knowledge.")
            await self.culture_manager.acreate_cultural_knowledge(
                message=run_messages.user_message.get_content_string()
            )

    def _make_memories(
        self,
        run_messages: RunMessages,
        user_id: Optional[str] = None,
    ):
        user_message_str = (
            run_messages.user_message.get_content_string() if run_messages.user_message is not None else None
        )
        if (
            user_message_str is not None
            and user_message_str.strip() != ""
            and self.memory_manager is not None
            and self.update_memory_on_run
        ):
            log_debug("Managing user memories")
            self.memory_manager.create_user_memories(  # type: ignore
                message=user_message_str,
                user_id=user_id,
                agent_id=self.id,
            )

        if run_messages.extra_messages is not None and len(run_messages.extra_messages) > 0:
            parsed_messages = []
            for _im in run_messages.extra_messages:
                if isinstance(_im, Message):
                    parsed_messages.append(_im)
                elif isinstance(_im, dict):
                    try:
                        parsed_messages.append(Message(**_im))
                    except Exception as e:
                        log_warning(f"Failed to validate message during memory update: {e}")
                else:
                    log_warning(f"Unsupported message type: {type(_im)}")
                    continue

            # Filter out messages with empty content before passing to memory manager
            non_empty_messages = [
                msg
                for msg in parsed_messages
                if msg.content and (not isinstance(msg.content, str) or msg.content.strip() != "")
            ]
            if len(non_empty_messages) > 0 and self.memory_manager is not None and self.update_memory_on_run:
                self.memory_manager.create_user_memories(messages=non_empty_messages, user_id=user_id, agent_id=self.id)  # type: ignore
            else:
                log_warning("Unable to add messages to memory")

    async def _amake_memories(
        self,
        run_messages: RunMessages,
        user_id: Optional[str] = None,
    ):
        user_message_str = (
            run_messages.user_message.get_content_string() if run_messages.user_message is not None else None
        )
        if (
            user_message_str is not None
            and user_message_str.strip() != ""
            and self.memory_manager is not None
            and self.update_memory_on_run
        ):
            log_debug("Managing user memories")
            await self.memory_manager.acreate_user_memories(  # type: ignore
                message=user_message_str,
                user_id=user_id,
                agent_id=self.id,
            )

        if run_messages.extra_messages is not None and len(run_messages.extra_messages) > 0:
            parsed_messages = []
            for _im in run_messages.extra_messages:
                if isinstance(_im, Message):
                    parsed_messages.append(_im)
                elif isinstance(_im, dict):
                    try:
                        parsed_messages.append(Message(**_im))
                    except Exception as e:
                        log_warning(f"Failed to validate message during memory update: {e}")
                else:
                    log_warning(f"Unsupported message type: {type(_im)}")
                    continue

            # Filter out messages with empty content before passing to memory manager
            non_empty_messages = [
                msg
                for msg in parsed_messages
                if msg.content and (not isinstance(msg.content, str) or msg.content.strip() != "")
            ]
            if len(non_empty_messages) > 0 and self.memory_manager is not None and self.update_memory_on_run:
                await self.memory_manager.acreate_user_memories(  # type: ignore
                    messages=non_empty_messages, user_id=user_id, agent_id=self.id
                )
            else:
                log_warning("Unable to add messages to memory")

    async def _astart_memory_task(
        self,
        run_messages: RunMessages,
        user_id: Optional[str],
        existing_task: Optional[Task[None]],
    ) -> Optional[Task[None]]:
        """Cancel any existing memory task and start a new one if conditions are met.

        Args:
            run_messages: The run messages containing the user message.
            user_id: The user ID for memory creation.
            existing_task: An existing memory task to cancel before starting a new one.

        Returns:
            A new memory task if conditions are met, None otherwise.
        """
        # Cancel any existing task from a previous retry attempt
        if existing_task is not None and not existing_task.done():
            existing_task.cancel()
            try:
                await existing_task
            except CancelledError:
                pass

        # Create new task if conditions are met
        if (
            run_messages.user_message is not None
            and self.memory_manager is not None
            and self.update_memory_on_run
            and not self.enable_agentic_memory
        ):
            log_debug("Starting memory creation in background task.")
            return create_task(self._amake_memories(run_messages=run_messages, user_id=user_id))

        return None

    async def _astart_cultural_knowledge_task(
        self,
        run_messages: RunMessages,
        existing_task: Optional[Task[None]],
    ) -> Optional[Task[None]]:
        """Cancel any existing cultural knowledge task and start a new one if conditions are met.

        Args:
            run_messages: The run messages containing the user message.
            existing_task: An existing cultural knowledge task to cancel before starting a new one.

        Returns:
            A new cultural knowledge task if conditions are met, None otherwise.
        """
        # Cancel any existing task from a previous retry attempt
        if existing_task is not None and not existing_task.done():
            existing_task.cancel()
            try:
                await existing_task
            except CancelledError:
                pass

        # Create new task if conditions are met
        if (
            run_messages.user_message is not None
            and self.culture_manager is not None
            and self.update_cultural_knowledge
        ):
            log_debug("Starting cultural knowledge creation in background task.")
            return create_task(self._acreate_cultural_knowledge(run_messages=run_messages))

        return None

    def _process_learnings(
        self,
        run_messages: RunMessages,
        session: AgentSession,
        user_id: Optional[str],
    ) -> None:
        """Process learnings from conversation (runs in background thread)."""
        if self._learning is None:
            return

        try:
            # Convert run messages to list format expected by LearningMachine
            messages = run_messages.messages if run_messages else []

            self._learning.process(
                messages=messages,
                user_id=user_id,
                session_id=session.session_id if session else None,
                agent_id=self.id,
                team_id=self.team_id,
            )
            log_debug("Learning extraction completed.")
        except Exception as e:
            log_warning(f"Error processing learnings: {e}")

    async def _astart_learning_task(
        self,
        run_messages: RunMessages,
        session: AgentSession,
        user_id: Optional[str],
        existing_task: Optional[Task] = None,
    ) -> Optional[Task]:
        """Start learning extraction as async task.

        Args:
            run_messages: The run messages containing conversation.
            session: The agent session.
            user_id: The user ID for learning extraction.
            existing_task: An existing task to cancel before starting a new one.

        Returns:
            A new learning task if conditions are met, None otherwise.
        """
        # Cancel any existing task from a previous retry attempt
        if existing_task is not None and not existing_task.done():
            existing_task.cancel()
            try:
                await existing_task
            except CancelledError:
                pass

        # Create new task if learning is enabled
        if self._learning is not None:
            log_debug("Starting learning extraction as async task.")
            return create_task(
                self._aprocess_learnings(
                    run_messages=run_messages,
                    session=session,
                    user_id=user_id,
                )
            )

        return None

    async def _aprocess_learnings(
        self,
        run_messages: RunMessages,
        session: AgentSession,
        user_id: Optional[str],
    ) -> None:
        """Async process learnings from conversation."""
        if self._learning is None:
            return

        try:
            messages = run_messages.messages if run_messages else []
            await self._learning.aprocess(
                messages=messages,
                user_id=user_id,
                session_id=session.session_id if session else None,
                agent_id=self.id,
                team_id=self.team_id,
            )
            log_debug("Learning extraction completed.")
        except Exception as e:
            log_warning(f"Error processing learnings: {e}")

    def _start_memory_future(
        self,
        run_messages: RunMessages,
        user_id: Optional[str],
        existing_future: Optional[Future] = None,
    ) -> Optional[Future]:
        """Cancel any existing memory future and start a new one if conditions are met.

        Args:
            run_messages: The run messages containing the user message.
            user_id: The user ID for memory creation.
            existing_future: An existing memory future to cancel before starting a new one.

        Returns:
            A new memory future if conditions are met, None otherwise.
        """
        # Cancel any existing future from a previous retry attempt
        # Note: cancel() only works if the future hasn't started yet
        if existing_future is not None and not existing_future.done():
            existing_future.cancel()

        # Create new future if conditions are met
        if (
            run_messages.user_message is not None
            and self.memory_manager is not None
            and self.update_memory_on_run
            and not self.enable_agentic_memory
        ):
            log_debug("Starting memory creation in background thread.")
            return self.background_executor.submit(self._make_memories, run_messages=run_messages, user_id=user_id)

        return None

    def _start_learning_future(
        self,
        run_messages: RunMessages,
        session: AgentSession,
        user_id: Optional[str],
        existing_future: Optional[Future] = None,
    ) -> Optional[Future]:
        """Start learning extraction in background thread.

        Args:
            run_messages: The run messages containing conversation.
            session: The agent session.
            user_id: The user ID for learning extraction.
            existing_future: An existing future to cancel before starting a new one.

        Returns:
            A new learning future if conditions are met, None otherwise.
        """
        # Cancel any existing future from a previous retry attempt
        if existing_future is not None and not existing_future.done():
            existing_future.cancel()

        # Create new future if learning is enabled
        if self._learning is not None:
            log_debug("Starting learning extraction in background thread.")
            return self.background_executor.submit(
                self._process_learnings,
                run_messages=run_messages,
                session=session,
                user_id=user_id,
            )

        return None

    def _start_cultural_knowledge_future(
        self,
        run_messages: RunMessages,
        existing_future: Optional[Future] = None,
    ) -> Optional[Future]:
        """Cancel any existing cultural knowledge future and start a new one if conditions are met.

        Args:
            run_messages: The run messages containing the user message.
            existing_future: An existing cultural knowledge future to cancel before starting a new one.

        Returns:
            A new cultural knowledge future if conditions are met, None otherwise.
        """
        # Cancel any existing future from a previous retry attempt
        # Note: cancel() only works if the future hasn't started yet
        if existing_future is not None and not existing_future.done():
            existing_future.cancel()

        # Create new future if conditions are met
        if (
            run_messages.user_message is not None
            and self.culture_manager is not None
            and self.update_cultural_knowledge
        ):
            log_debug("Starting cultural knowledge creation in background thread.")
            return self.background_executor.submit(self._make_cultural_knowledge, run_messages=run_messages)

        return None

    def _raise_if_async_tools(self) -> None:
        """Raise an exception if any tools contain async functions"""
        if self.tools is None:
            return

        from inspect import iscoroutinefunction

        for tool in self.tools:
            if isinstance(tool, Toolkit):
                for func in tool.functions:
                    if iscoroutinefunction(tool.functions[func].entrypoint):
                        raise Exception(
                            f"Async tool {tool.name} can't be used with synchronous agent.run() or agent.print_response(). "
                            "Use agent.arun() or agent.aprint_response() instead to use this tool."
                        )
            elif isinstance(tool, Function):
                if iscoroutinefunction(tool.entrypoint):
                    raise Exception(
                        f"Async function {tool.name} can't be used with synchronous agent.run() or agent.print_response(). "
                        "Use agent.arun() or agent.aprint_response() instead to use this tool."
                    )
            elif callable(tool):
                if iscoroutinefunction(tool):
                    raise Exception(
                        f"Async function {tool.__name__} can't be used with synchronous agent.run() or agent.print_response(). "
                        "Use agent.arun() or agent.aprint_response() instead to use this tool."
                    )
