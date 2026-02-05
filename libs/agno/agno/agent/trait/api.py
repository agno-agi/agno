from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Union,
    cast,
)

from pydantic import BaseModel

from agno.agent.trait.base import AgentTraitBase
from agno.filters import FilterExpr
from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.reasoning.step import NextAction, ReasoningStep
from agno.run import RunContext
from agno.run.agent import (
    RunOutput,
)
from agno.session import AgentSession
from agno.utils.agent import (
    scrub_history_messages_from_run_output,
    scrub_media_from_run_output,
    scrub_tool_results_from_run_output,
)
from agno.utils.log import (
    log_debug,
)
from agno.utils.print_response.agent import (
    aprint_response,
    aprint_response_stream,
    print_response,
    print_response_stream,
)
from agno.utils.reasoning import (
    add_reasoning_step_to_metadata,
    append_to_reasoning_content,
)


class AgentApiTrait(AgentTraitBase):
    ###########################################################################
    # Print Response
    ###########################################################################

    def print_response(
        self,
        input: Union[List, Dict, str, Message, BaseModel, List[Message]],
        *,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        run_id: Optional[str] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream: Optional[bool] = None,
        markdown: Optional[bool] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        add_session_state_to_context: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        debug_mode: Optional[bool] = None,
        show_message: bool = True,
        show_reasoning: bool = True,
        show_full_reasoning: bool = False,
        console: Optional[Any] = None,
        # Add tags to include in markdown content
        tags_to_include_in_markdown: Optional[Set[str]] = None,
        **kwargs: Any,
    ) -> None:
        if self._has_async_db():
            raise Exception(
                "This method is not supported with an async DB. Please use the async version of this method."
            )

        if not tags_to_include_in_markdown:
            tags_to_include_in_markdown = {"think", "thinking"}

        if markdown is None:
            markdown = self.markdown

        if self.output_schema is not None:
            markdown = False

        # Use stream override value when necessary
        if stream is None:
            stream = False if self.stream is None else self.stream

        if "stream_events" in kwargs:
            kwargs.pop("stream_events")

        if stream:
            print_response_stream(
                agent=cast(Any, self),
                input=input,
                session_id=session_id,
                session_state=session_state,
                user_id=user_id,
                run_id=run_id,
                audio=audio,
                images=images,
                videos=videos,
                files=files,
                stream_events=True,
                knowledge_filters=knowledge_filters,
                debug_mode=debug_mode,
                markdown=markdown,
                show_message=show_message,
                show_reasoning=show_reasoning,
                show_full_reasoning=show_full_reasoning,
                tags_to_include_in_markdown=tags_to_include_in_markdown,
                console=console,
                add_history_to_context=add_history_to_context,
                dependencies=dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                metadata=metadata,
                **kwargs,
            )

        else:
            print_response(
                agent=cast(Any, self),
                input=input,
                session_id=session_id,
                session_state=session_state,
                user_id=user_id,
                run_id=run_id,
                audio=audio,
                images=images,
                videos=videos,
                files=files,
                knowledge_filters=knowledge_filters,
                debug_mode=debug_mode,
                markdown=markdown,
                show_message=show_message,
                show_reasoning=show_reasoning,
                show_full_reasoning=show_full_reasoning,
                tags_to_include_in_markdown=tags_to_include_in_markdown,
                console=console,
                add_history_to_context=add_history_to_context,
                dependencies=dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                metadata=metadata,
                **kwargs,
            )

    async def aprint_response(
        self,
        input: Union[List, Dict, str, Message, BaseModel, List[Message]],
        *,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        run_id: Optional[str] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream: Optional[bool] = None,
        markdown: Optional[bool] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        add_history_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        debug_mode: Optional[bool] = None,
        show_message: bool = True,
        show_reasoning: bool = True,
        show_full_reasoning: bool = False,
        console: Optional[Any] = None,
        # Add tags to include in markdown content
        tags_to_include_in_markdown: Optional[Set[str]] = None,
        **kwargs: Any,
    ) -> None:
        if not tags_to_include_in_markdown:
            tags_to_include_in_markdown = {"think", "thinking"}

        if markdown is None:
            markdown = self.markdown

        if self.output_schema is not None:
            markdown = False

        if stream is None:
            stream = self.stream or False

        if "stream_events" in kwargs:
            kwargs.pop("stream_events")

        if stream:
            await aprint_response_stream(
                agent=cast(Any, self),
                input=input,
                session_id=session_id,
                session_state=session_state,
                user_id=user_id,
                run_id=run_id,
                audio=audio,
                images=images,
                videos=videos,
                files=files,
                stream_events=True,
                knowledge_filters=knowledge_filters,
                debug_mode=debug_mode,
                markdown=markdown,
                show_message=show_message,
                show_reasoning=show_reasoning,
                show_full_reasoning=show_full_reasoning,
                tags_to_include_in_markdown=tags_to_include_in_markdown,
                console=console,
                add_history_to_context=add_history_to_context,
                dependencies=dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                metadata=metadata,
                **kwargs,
            )
        else:
            await aprint_response(
                agent=cast(Any, self),
                input=input,
                session_id=session_id,
                session_state=session_state,
                user_id=user_id,
                run_id=run_id,
                audio=audio,
                images=images,
                videos=videos,
                files=files,
                knowledge_filters=knowledge_filters,
                debug_mode=debug_mode,
                markdown=markdown,
                show_message=show_message,
                show_reasoning=show_reasoning,
                show_full_reasoning=show_full_reasoning,
                tags_to_include_in_markdown=tags_to_include_in_markdown,
                console=console,
                add_history_to_context=add_history_to_context,
                dependencies=dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                metadata=metadata,
                **kwargs,
            )

    def _update_reasoning_content_from_tool_call(
        self, run_response: RunOutput, tool_name: str, tool_args: Dict[str, Any]
    ) -> Optional[ReasoningStep]:
        """Update reasoning_content based on tool calls that look like thinking or reasoning tools."""

        # Case 1: ReasoningTools.think (has title, thought, optional action and confidence)
        if tool_name.lower() == "think" and "title" in tool_args and "thought" in tool_args:
            title = tool_args["title"]
            thought = tool_args["thought"]
            action = tool_args.get("action", "")
            confidence = tool_args.get("confidence", None)

            # Create a reasoning step
            reasoning_step = ReasoningStep(
                title=title,
                reasoning=thought,
                action=action,
                next_action=NextAction.CONTINUE,
                confidence=confidence,
                result=None,
            )

            # Add the step to the run response
            add_reasoning_step_to_metadata(run_response=run_response, reasoning_step=reasoning_step)

            formatted_content = f"## {title}\n{thought}\n"
            if action:
                formatted_content += f"Action: {action}\n"
            if confidence is not None:
                formatted_content += f"Confidence: {confidence}\n"
            formatted_content += "\n"

            append_to_reasoning_content(run_response=run_response, content=formatted_content)
            return reasoning_step

        # Case 2: ReasoningTools.analyze (has title, result, analysis, optional next_action and confidence)
        elif tool_name.lower() == "analyze" and "title" in tool_args:
            title = tool_args["title"]
            result = tool_args.get("result", "")
            analysis = tool_args.get("analysis", "")
            next_action = tool_args.get("next_action", "")
            confidence = tool_args.get("confidence", None)

            # Map string next_action to enum
            next_action_enum = NextAction.CONTINUE
            if next_action.lower() == "validate":
                next_action_enum = NextAction.VALIDATE
            elif next_action.lower() in ["final", "final_answer", "finalize"]:
                next_action_enum = NextAction.FINAL_ANSWER

            # Create a reasoning step
            reasoning_step = ReasoningStep(
                title=title,
                result=result,
                reasoning=analysis,
                next_action=next_action_enum,
                confidence=confidence,
                action=None,
            )

            # Add the step to the run response
            add_reasoning_step_to_metadata(run_response=run_response, reasoning_step=reasoning_step)

            formatted_content = f"## {title}\n"
            if result:
                formatted_content += f"Result: {result}\n"
            if analysis:
                formatted_content += f"{analysis}\n"
            if next_action and next_action.lower() != "continue":
                formatted_content += f"Next Action: {next_action}\n"
            if confidence is not None:
                formatted_content += f"Confidence: {confidence}\n"
            formatted_content += "\n"

            append_to_reasoning_content(run_response=run_response, content=formatted_content)
            return reasoning_step

        # Case 3: ReasoningTool.think (simple format, just has 'thought')
        elif tool_name.lower() == "think" and "thought" in tool_args:
            thought = tool_args["thought"]
            reasoning_step = ReasoningStep(  # type: ignore
                title="Thinking",
                reasoning=thought,
                confidence=None,
            )
            formatted_content = f"## Thinking\n{thought}\n\n"
            add_reasoning_step_to_metadata(run_response=run_response, reasoning_step=reasoning_step)
            append_to_reasoning_content(run_response=run_response, content=formatted_content)
            return reasoning_step

        return None

    def _get_effective_filters(
        self, knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    ) -> Optional[Any]:
        """
        Determine which knowledge filters to use, with priority to run-level filters.

        Args:
            knowledge_filters: Filters passed at run time

        Returns:
            The effective filters to use, with run-level filters taking priority
        """
        effective_filters = None

        # If agent has filters, use those as a base
        if self.knowledge_filters:
            effective_filters = self.knowledge_filters.copy()

        # If run has filters, they override agent filters
        if knowledge_filters:
            if effective_filters:
                if isinstance(knowledge_filters, dict):
                    if isinstance(effective_filters, dict):
                        effective_filters.update(knowledge_filters)
                    else:
                        effective_filters = knowledge_filters
                elif isinstance(knowledge_filters, list):
                    effective_filters = [*effective_filters, *knowledge_filters]
            else:
                effective_filters = knowledge_filters

        if effective_filters:
            log_debug(f"Using knowledge filters: {effective_filters}")

        return effective_filters

    def _cleanup_and_store(
        self,
        run_response: RunOutput,
        session: AgentSession,
        run_context: Optional[RunContext] = None,
        user_id: Optional[str] = None,
    ) -> None:  #  Scrub the stored run based on storage flags
        self._scrub_run_output_for_storage(run_response)

        # Stop the timer for the Run duration
        if run_response.metrics:
            run_response.metrics.stop_timer()

        # Update run_response.session_state before saving
        # This ensures RunOutput reflects all tool modifications
        if session.session_data is not None and run_context is not None and run_context.session_state is not None:
            run_response.session_state = run_context.session_state

        # Optional: Save output to file if save_response_to_file is set
        self.save_run_response_to_file(
            run_response=run_response,
            input=run_response.input.input_content_string() if run_response.input else "",
            session_id=session.session_id,
            user_id=user_id,
        )

        # Add RunOutput to Agent Session
        session.upsert_run(run=run_response)

        # Calculate session metrics
        self._update_session_metrics(session=session, run_response=run_response)

        # Save session to memory
        self.save_session(session=session)

    async def _acleanup_and_store(
        self,
        run_response: RunOutput,
        session: AgentSession,
        run_context: Optional[RunContext] = None,
        user_id: Optional[str] = None,
    ) -> None:
        #  Scrub the stored run based on storage flags
        self._scrub_run_output_for_storage(run_response)

        # Stop the timer for the Run duration
        if run_response.metrics:
            run_response.metrics.stop_timer()

        # Update run_response.session_state from session before saving
        # This ensures RunOutput reflects all tool modifications
        if session.session_data is not None and run_context is not None and run_context.session_state is not None:
            run_response.session_state = run_context.session_state

        # Optional: Save output to file if save_response_to_file is set
        self.save_run_response_to_file(
            run_response=run_response,
            input=run_response.input.input_content_string() if run_response.input else "",
            session_id=session.session_id,
            user_id=user_id,
        )

        # Add RunOutput to Agent Session
        session.upsert_run(run=run_response)

        # Calculate session metrics
        self._update_session_metrics(session=session, run_response=run_response)

        # Update session state before saving the session
        if run_context is not None and run_context.session_state is not None:
            if session.session_data is not None:
                session.session_data["session_state"] = run_context.session_state
            else:
                session.session_data = {"session_state": run_context.session_state}

        # Save session to memory
        await self.asave_session(session=session)

    def _scrub_run_output_for_storage(self, run_response: RunOutput) -> None:
        """
        Scrub run output based on storage flags before persisting to database.
        """
        if not self.store_media:
            scrub_media_from_run_output(run_response)

        if not self.store_tool_messages:
            scrub_tool_results_from_run_output(run_response)

        if not self.store_history_messages:
            scrub_history_messages_from_run_output(run_response)

    def cli_app(
        self,
        input: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user: str = "User",
        emoji: str = ":sunglasses:",
        stream: bool = False,
        markdown: bool = False,
        exit_on: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        """Run an interactive command-line interface to interact with the agent."""

        from inspect import isawaitable

        from rich.prompt import Prompt

        # Ensuring the agent is not using our async MCP tools
        tools = self._get_tools()
        if tools is not None:
            for tool in tools:
                if isawaitable(tool):
                    raise NotImplementedError("Use `acli_app` to use async tools.")
                # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
                if hasattr(type(tool), "__mro__") and any(
                    c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
                ):
                    raise NotImplementedError("Use `acli_app` to use MCP tools.")

        if input:
            self.print_response(
                input=input,
                stream=stream,
                markdown=markdown,
                user_id=user_id,
                session_id=session_id,
                **kwargs,
            )

        _exit_on = exit_on or ["exit", "quit", "bye"]
        while True:
            message = Prompt.ask(f"[bold] {emoji} {user} [/bold]")
            if message in _exit_on:
                break

            self.print_response(
                input=message,
                stream=stream,
                markdown=markdown,
                user_id=user_id,
                session_id=session_id,
                **kwargs,
            )

    async def acli_app(
        self,
        input: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user: str = "User",
        emoji: str = ":sunglasses:",
        stream: bool = False,
        markdown: bool = False,
        exit_on: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Run an interactive command-line interface to interact with the agent.
        Works with agent dependencies requiring async logic.
        """
        from rich.prompt import Prompt

        if input:
            await self.aprint_response(
                input=input,
                stream=stream,
                markdown=markdown,
                user_id=user_id,
                session_id=session_id,
                **kwargs,
            )

        _exit_on = exit_on or ["exit", "quit", "bye"]
        while True:
            message = Prompt.ask(f"[bold] {emoji} {user} [/bold]")
            if message in _exit_on:
                break

            await self.aprint_response(
                input=message,
                stream=stream,
                markdown=markdown,
                user_id=user_id,
                session_id=session_id,
                **kwargs,
            )
