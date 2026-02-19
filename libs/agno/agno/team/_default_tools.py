"""Built-in tool factory functions for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.team import Team

import asyncio
import contextlib
import json
from copy import copy
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Optional,
    Union,
    cast,
)

from pydantic import BaseModel

from agno.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.filters import FilterExpr
from agno.knowledge.types import KnowledgeFilter
from agno.media import Audio, File, Image, Video
from agno.memory import MemoryManager
from agno.models.message import Message, MessageReferences
from agno.run import RunContext
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.team import (
    TeamRunOutput,
    TeamRunOutputEvent,
)
from agno.session import TeamSession
from agno.tools.function import Function
from agno.utils.knowledge import get_agentic_or_user_search_filters
from agno.utils.log import (
    log_debug,
    log_info,
    log_warning,
    use_agent_logger,
    use_team_logger,
)
from agno.utils.merge_dict import merge_dictionaries
from agno.utils.response import (
    check_if_run_cancelled,
)
from agno.utils.team import (
    add_interaction_to_team_run_context,
    format_member_agent_task,
)
from agno.utils.timer import Timer


def _get_update_user_memory_function(team: "Team", user_id: Optional[str] = None, async_mode: bool = False) -> Function:
    def update_user_memory(task: str) -> str:
        """
        Use this function to submit a task to modify the Agent's memory.
        Describe the task in detail and be specific.
        The task can include adding a memory, updating a memory, deleting a memory, or clearing all memories.

        Args:
            task: The task to update the memory. Be specific and describe the task in detail.

        Returns:
            str: A string indicating the status of the update.
        """
        team.memory_manager = cast(MemoryManager, team.memory_manager)
        response = team.memory_manager.update_memory_task(task=task, user_id=user_id)
        return response

    async def aupdate_user_memory(task: str) -> str:
        """
        Use this function to submit a task to modify the Agent's memory.
        Describe the task in detail and be specific.
        The task can include adding a memory, updating a memory, deleting a memory, or clearing all memories.

        Args:
            task: The task to update the memory. Be specific and describe the task in detail.

        Returns:
            str: A string indicating the status of the update.
        """
        team.memory_manager = cast(MemoryManager, team.memory_manager)
        response = await team.memory_manager.aupdate_memory_task(task=task, user_id=user_id)
        return response

    if async_mode:
        update_memory_function = aupdate_user_memory
    else:
        update_memory_function = update_user_memory  # type: ignore

    return Function.from_callable(update_memory_function, name="update_user_memory")


def _get_chat_history_function(team: "Team", session: TeamSession, async_mode: bool = False):
    def get_chat_history(num_chats: Optional[int] = None) -> str:
        """
        Use this function to get the team chat history in reverse chronological order.
        Leave the num_chats parameter blank to get the entire chat history.
        Example:
            - To get the last chat, use num_chats=1
            - To get the last 5 chats, use num_chats=5
            - To get all chats, leave num_chats blank

        Args:
            num_chats: The number of chats to return.
                Each chat contains 2 messages. One from the team and one from the user.
                Default: None

        Returns:
            str: A JSON string containing a list of dictionaries representing the team chat history.
        """
        import json

        all_chats = session.get_messages(team_id=team.id)

        if len(all_chats) == 0:
            return ""

        history: List[Dict[str, Any]] = [chat.to_dict() for chat in all_chats]  # type: ignore

        if num_chats is not None:
            history = history[-num_chats:]

        return json.dumps(history)

    async def aget_chat_history(num_chats: Optional[int] = None) -> str:
        """
        Use this function to get the team chat history in reverse chronological order.
        Leave the num_chats parameter blank to get the entire chat history.
        Example:
            - To get the last chat, use num_chats=1
            - To get the last 5 chats, use num_chats=5
            - To get all chats, leave num_chats blank

        Args:
            num_chats: The number of chats to return.
                Each chat contains 2 messages. One from the team and one from the user.
                Default: None

        Returns:
            str: A JSON string containing a list of dictionaries representing the team chat history.
        """
        import json

        all_chats = session.get_messages(team_id=team.id)

        if len(all_chats) == 0:
            return ""

        history: List[Dict[str, Any]] = [chat.to_dict() for chat in all_chats]  # type: ignore

        if num_chats is not None:
            history = history[-num_chats:]

        return json.dumps(history)

    if async_mode:
        get_chat_history_func = aget_chat_history
    else:
        get_chat_history_func = get_chat_history  # type: ignore
    return Function.from_callable(get_chat_history_func, name="get_chat_history")


def _update_session_state_tool(team: "Team", run_context: RunContext, session_state_updates: dict) -> str:
    """
    Update the shared session state.  Provide any updates as a dictionary of key-value pairs.
    Example:
        "session_state_updates": {"shopping_list": ["milk", "eggs", "bread"]}

    Args:
        session_state_updates (dict): The updates to apply to the shared session state. Should be a dictionary of key-value pairs.
    """
    if run_context.session_state is None:
        run_context.session_state = {}
    session_state = run_context.session_state
    for key, value in session_state_updates.items():
        session_state[key] = value

    return f"Updated session state: {session_state}"


def _get_previous_sessions_messages_function(
    team: "Team", num_history_sessions: Optional[int] = 2, user_id: Optional[str] = None, async_mode: bool = False
):
    """Factory function to create a get_previous_session_messages function.

    Args:
        num_history_sessions: The last n sessions to be taken from db
        user_id: The user ID to filter sessions by

    Returns:
        Callable: A function that retrieves messages from previous sessions
    """

    from agno.team._init import _has_async_db

    def get_previous_session_messages() -> str:
        """Use this function to retrieve messages from previous chat sessions.
        USE THIS TOOL ONLY WHEN THE QUESTION IS EITHER "What was my last conversation?" or "What was my last question?" and similar to it.

        Returns:
            str: JSON formatted list of message pairs from previous sessions
        """
        import json

        if team.db is None:
            return "Previous session messages not available"

        team.db = cast(BaseDb, team.db)
        selected_sessions = team.db.get_sessions(
            session_type=SessionType.TEAM,
            limit=num_history_sessions,
            user_id=user_id,
            sort_by="created_at",
            sort_order="desc",
        )

        all_messages = []
        seen_message_pairs = set()

        for session in selected_sessions:
            if isinstance(session, TeamSession) and session.runs:
                for run in session.runs:
                    messages = run.messages
                    if messages is not None:
                        for i in range(0, len(messages) - 1, 2):
                            if i + 1 < len(messages):
                                try:
                                    user_msg = messages[i]
                                    assistant_msg = messages[i + 1]
                                    user_content = user_msg.content
                                    assistant_content = assistant_msg.content
                                    if user_content is None or assistant_content is None:
                                        continue  # Skip this pair if either message has no content

                                    msg_pair_id = f"{user_content}:{assistant_content}"
                                    if msg_pair_id not in seen_message_pairs:
                                        seen_message_pairs.add(msg_pair_id)
                                        all_messages.append(Message.model_validate(user_msg))
                                        all_messages.append(Message.model_validate(assistant_msg))
                                except Exception as e:
                                    log_warning(f"Error processing message pair: {e}")
                                    continue

        return json.dumps([msg.to_dict() for msg in all_messages]) if all_messages else "No history found"

    async def aget_previous_session_messages() -> str:
        """Use this function to retrieve messages from previous chat sessions.
        USE THIS TOOL ONLY WHEN THE QUESTION IS EITHER "What was my last conversation?" or "What was my last question?" and similar to it.

        Returns:
            str: JSON formatted list of message pairs from previous sessions
        """
        import json

        from agno.team._init import _has_async_db

        if team.db is None:
            return "Previous session messages not available"

        if _has_async_db(team):
            selected_sessions = await cast(AsyncBaseDb, team.db).get_sessions(  # type: ignore
                session_type=SessionType.TEAM,
                limit=num_history_sessions,
                user_id=user_id,
                sort_by="created_at",
                sort_order="desc",
            )
        else:
            selected_sessions = team.db.get_sessions(  # type: ignore
                session_type=SessionType.TEAM,
                limit=num_history_sessions,
                user_id=user_id,
                sort_by="created_at",
                sort_order="desc",
            )

        all_messages = []
        seen_message_pairs = set()

        for session in selected_sessions:
            if isinstance(session, TeamSession) and session.runs:
                for run in session.runs:
                    messages = run.messages
                    if messages is not None:
                        for i in range(0, len(messages) - 1, 2):
                            if i + 1 < len(messages):
                                try:
                                    user_msg = messages[i]
                                    assistant_msg = messages[i + 1]
                                    user_content = user_msg.content
                                    assistant_content = assistant_msg.content
                                    if user_content is None or assistant_content is None:
                                        continue  # Skip this pair if either message has no content

                                    msg_pair_id = f"{user_content}:{assistant_content}"
                                    if msg_pair_id not in seen_message_pairs:
                                        seen_message_pairs.add(msg_pair_id)
                                        all_messages.append(Message.model_validate(user_msg))
                                        all_messages.append(Message.model_validate(assistant_msg))
                                except Exception as e:
                                    log_warning(f"Error processing message pair: {e}")
                                    continue

        return json.dumps([msg.to_dict() for msg in all_messages]) if all_messages else "No history found"

    if _has_async_db(team):
        return Function.from_callable(aget_previous_session_messages, name="get_previous_session_messages")
    else:
        return Function.from_callable(get_previous_session_messages, name="get_previous_session_messages")


def _get_delegate_task_function(
    team: "Team",
    run_response: TeamRunOutput,
    run_context: RunContext,
    session: TeamSession,
    team_run_context: Dict[str, Any],
    user_id: Optional[str] = None,
    stream: bool = False,
    stream_events: bool = False,
    async_mode: bool = False,
    input: Optional[str] = None,  # Used for determine_input_for_members=False
    images: Optional[List[Image]] = None,
    videos: Optional[List[Video]] = None,
    audio: Optional[List[Audio]] = None,
    files: Optional[List[File]] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    debug_mode: Optional[bool] = None,
) -> Function:
    from agno.team._init import _initialize_member
    from agno.team._run import _update_team_media
    from agno.team._tools import (
        _determine_team_member_interactions,
        _find_member_by_id,
        _get_history_for_member_agent,
        _propagate_member_pause,
    )

    if not images:
        images = []
    if not videos:
        videos = []
    if not audio:
        audio = []
    if not files:
        files = []

    def _setup_delegate_task_to_member(member_agent: Union[Agent, "Team"], task: str):
        # 1. Initialize the member agent

        _initialize_member(team, member_agent)

        # If team has send_media_to_model=False, ensure member agent also has it set to False
        # This allows tools to access files while preventing models from receiving them
        if not team.send_media_to_model:
            member_agent.send_media_to_model = False

        # 2. Handle respond_directly nuances
        if team.respond_directly:
            # Since we return the response directly from the member agent, we need to set the output schema from the team down.
            # Get output_schema from run_context
            team_output_schema = run_context.output_schema if run_context else None
            if not member_agent.output_schema and team_output_schema:
                member_agent.output_schema = team_output_schema

            # If the member will produce structured output, we need to parse the response
            if member_agent.output_schema is not None:
                team._member_response_model = member_agent.output_schema

        # 3. Handle enable_agentic_knowledge_filters on the member agent
        if team.enable_agentic_knowledge_filters and not member_agent.enable_agentic_knowledge_filters:
            member_agent.enable_agentic_knowledge_filters = team.enable_agentic_knowledge_filters

        # 4. Determine team context to send
        team_member_interactions_str = _determine_team_member_interactions(
            team, team_run_context, images=images, videos=videos, audio=audio, files=files
        )

        # 5. Get the team history
        team_history_str = None
        if team.add_team_history_to_members and session:
            team_history_str = session.get_team_history_context(num_runs=team.num_team_history_runs)

        # 6. Create the member agent task or use the input directly
        if team.determine_input_for_members is False:
            member_agent_task = input  # type: ignore
        else:
            member_agent_task = task

        if team_history_str or team_member_interactions_str:
            member_agent_task = format_member_agent_task(  # type: ignore
                task_description=member_agent_task or "",
                team_member_interactions_str=team_member_interactions_str,
                team_history_str=team_history_str,
            )

        # 7. Add member-level history for the member if enabled (because we won't load the session for the member, so history won't be loaded automatically)
        history = None
        if hasattr(member_agent, "add_history_to_context") and member_agent.add_history_to_context:
            history = _get_history_for_member_agent(team, session, member_agent)
            if history:
                if isinstance(member_agent_task, str):
                    history.append(Message(role="user", content=member_agent_task))

        return member_agent_task, history

    def _process_delegate_task_to_member(
        member_agent_run_response: Optional[Union[TeamRunOutput, RunOutput]],
        member_agent: Union[Agent, "Team"],
        member_agent_task: Union[str, Message],
        member_session_state_copy: Dict[str, Any],
    ):
        # Add team run id to the member run

        if member_agent_run_response is not None:
            member_agent_run_response.parent_run_id = run_response.run_id  # type: ignore

        # Update the top-level team run_response tool call to have the run_id of the member run
        if run_response.tools is not None and member_agent_run_response is not None:
            for tool in run_response.tools:
                if tool.tool_name and tool.tool_name.lower() == "delegate_task_to_member":
                    tool.child_run_id = member_agent_run_response.run_id  # type: ignore

        # Update the team run context
        member_name = member_agent.name if member_agent.name else member_agent.id if member_agent.id else "Unknown"
        if isinstance(member_agent_task, str):
            normalized_task = member_agent_task
        elif member_agent_task.content:
            normalized_task = str(member_agent_task.content)
        else:
            normalized_task = ""
        add_interaction_to_team_run_context(
            team_run_context=team_run_context,
            member_name=member_name,
            task=normalized_task,
            run_response=member_agent_run_response,  # type: ignore
        )

        # Add the member run to the team run response if enabled
        if run_response and member_agent_run_response:
            run_response.add_member_run(member_agent_run_response)

        # Scrub the member run based on that member's storage flags before storing
        if member_agent_run_response:
            if (
                not member_agent.store_media
                or not member_agent.store_tool_messages
                or not member_agent.store_history_messages
            ):
                from agno.agent._run import scrub_run_output_for_storage

                scrub_run_output_for_storage(member_agent, run_response=member_agent_run_response)  # type: ignore[arg-type]

            # Add the member run to the team session
            session.upsert_run(member_agent_run_response)

        # Update team session state
        merge_dictionaries(run_context.session_state, member_session_state_copy)  # type: ignore

        # Update the team media
        if member_agent_run_response is not None:
            _update_team_media(team, member_agent_run_response)  # type: ignore

    def delegate_task_to_member(member_id: str, task: str) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Use this function to delegate a task to the selected team member.
        You must provide a clear and concise description of the task the member should achieve AND the expected output.

        Args:
            member_id (str): The ID of the member to delegate the task to. Use only the ID of the member, not the ID of the team followed by the ID of the member.
            task (str): A clear and concise description of the task the member should achieve.
        Returns:
            str: The result of the delegated task.
        """

        # Find the member agent using the helper function
        result = _find_member_by_id(team, member_id, run_context=run_context)
        if result is None:
            yield f"Member with ID {member_id} not found in the team or any subteams. Please choose the correct member from the list of members:\n\n{team.get_members_system_message_content(indent=0, run_context=run_context)}"
            return

        _, member_agent = result
        member_agent_task, history = _setup_delegate_task_to_member(member_agent=member_agent, task=task)

        # Make sure for the member agent, we are using the agent logger
        use_agent_logger()

        member_session_state_copy = copy(run_context.session_state)

        if stream:
            member_agent_run_response_stream = member_agent.run(
                input=member_agent_task if not history else history,
                user_id=user_id,
                # All members have the same session_id
                session_id=session.session_id,
                session_state=member_session_state_copy,  # Send a copy to the agent
                images=images,
                videos=videos,
                audio=audio,
                files=files,
                stream=True,
                stream_events=stream_events or team.stream_member_events,
                debug_mode=debug_mode,
                dependencies=run_context.dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                metadata=run_context.metadata,
                add_session_state_to_context=add_session_state_to_context,
                knowledge_filters=run_context.knowledge_filters
                if not member_agent.knowledge_filters and member_agent.knowledge
                else None,
                yield_run_output=True,
            )
            member_agent_run_response = None
            for member_agent_run_output_event in member_agent_run_response_stream:
                # Do NOT break out of the loop, Iterator need to exit properly
                if isinstance(member_agent_run_output_event, (TeamRunOutput, RunOutput)):
                    member_agent_run_response = member_agent_run_output_event  # type: ignore
                    continue  # Don't yield TeamRunOutput or RunOutput, only yield events

                # Check if the run is cancelled
                check_if_run_cancelled(member_agent_run_output_event)

                # Yield the member event directly
                member_agent_run_output_event.parent_run_id = (
                    member_agent_run_output_event.parent_run_id or run_response.run_id
                )
                yield member_agent_run_output_event  # type: ignore
        else:
            member_agent_run_response = member_agent.run(  # type: ignore
                input=member_agent_task if not history else history,  # type: ignore
                user_id=user_id,
                # All members have the same session_id
                session_id=session.session_id,
                session_state=member_session_state_copy,  # Send a copy to the agent
                images=images,
                videos=videos,
                audio=audio,
                files=files,
                stream=False,
                debug_mode=debug_mode,
                dependencies=run_context.dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                metadata=run_context.metadata,
                knowledge_filters=run_context.knowledge_filters
                if not member_agent.knowledge_filters and member_agent.knowledge
                else None,
            )

            check_if_run_cancelled(member_agent_run_response)  # type: ignore

        # Check if the member run is paused (HITL)
        if member_agent_run_response is not None and member_agent_run_response.is_paused:
            _propagate_member_pause(run_response, member_agent, member_agent_run_response)
            use_team_logger()
            _process_delegate_task_to_member(
                member_agent_run_response,
                member_agent,
                member_agent_task,  # type: ignore
                member_session_state_copy,  # type: ignore
            )
            yield f"Member '{member_agent.name}' requires human input before continuing."
            return

        if not stream:
            try:
                if member_agent_run_response.content is None and (  # type: ignore
                    member_agent_run_response.tools is None or len(member_agent_run_response.tools) == 0  # type: ignore
                ):
                    yield "No response from the member agent."
                elif isinstance(member_agent_run_response.content, str):  # type: ignore
                    content = member_agent_run_response.content.strip()  # type: ignore
                    if len(content) > 0:
                        yield content

                    # If the content is empty but we have tool calls
                    elif member_agent_run_response.tools is not None and len(member_agent_run_response.tools) > 0:  # type: ignore
                        tool_str = ""
                        for tool in member_agent_run_response.tools:  # type: ignore
                            if tool.result:
                                tool_str += f"{tool.result},"
                        yield tool_str.rstrip(",")

                elif issubclass(type(member_agent_run_response.content), BaseModel):  # type: ignore
                    yield member_agent_run_response.content.model_dump_json(indent=2)  # type: ignore
                else:
                    import json

                    yield json.dumps(member_agent_run_response.content, indent=2)  # type: ignore
            except Exception as e:
                yield str(e)

        # Afterward, switch back to the team logger
        use_team_logger()

        _process_delegate_task_to_member(
            member_agent_run_response,
            member_agent,
            member_agent_task,  # type: ignore
            member_session_state_copy,  # type: ignore
        )

    async def adelegate_task_to_member(
        member_id: str, task: str
    ) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Use this function to delegate a task to the selected team member.
        You must provide a clear and concise description of the task the member should achieve AND the expected output.

        Args:
            member_id (str): The ID of the member to delegate the task to. Use only the ID of the member, not the ID of the team followed by the ID of the member.
            task (str): A clear and concise description of the task the member should achieve.
        Returns:
            str: The result of the delegated task.
        """

        # Find the member agent using the helper function
        result = _find_member_by_id(team, member_id, run_context=run_context)
        if result is None:
            yield f"Member with ID {member_id} not found in the team or any subteams. Please choose the correct member from the list of members:\n\n{team.get_members_system_message_content(indent=0, run_context=run_context)}"
            return

        _, member_agent = result
        member_agent_task, history = _setup_delegate_task_to_member(member_agent=member_agent, task=task)

        # Make sure for the member agent, we are using the agent logger
        use_agent_logger()

        member_session_state_copy = copy(run_context.session_state)

        if stream:
            member_agent_run_response_stream = member_agent.arun(  # type: ignore
                input=member_agent_task if not history else history,
                user_id=user_id,
                # All members have the same session_id
                session_id=session.session_id,
                session_state=member_session_state_copy,  # Send a copy to the agent
                images=images,
                videos=videos,
                audio=audio,
                files=files,
                stream=True,
                stream_events=stream_events or team.stream_member_events,
                debug_mode=debug_mode,
                dependencies=run_context.dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                metadata=run_context.metadata,
                knowledge_filters=run_context.knowledge_filters
                if not member_agent.knowledge_filters and member_agent.knowledge
                else None,
                yield_run_output=True,
            )
            member_agent_run_response = None
            async for member_agent_run_response_event in member_agent_run_response_stream:
                # Do NOT break out of the loop, AsyncIterator need to exit properly
                if isinstance(member_agent_run_response_event, (TeamRunOutput, RunOutput)):
                    member_agent_run_response = member_agent_run_response_event  # type: ignore
                    continue  # Don't yield TeamRunOutput or RunOutput, only yield events

                # Check if the run is cancelled
                check_if_run_cancelled(member_agent_run_response_event)

                # Yield the member event directly
                member_agent_run_response_event.parent_run_id = getattr(
                    member_agent_run_response_event, "parent_run_id", None
                ) or (run_response.run_id if run_response is not None else None)
                yield member_agent_run_response_event  # type: ignore
        else:
            member_agent_run_response = await member_agent.arun(  # type: ignore
                input=member_agent_task if not history else history,
                user_id=user_id,
                # All members have the same session_id
                session_id=session.session_id,
                session_state=member_session_state_copy,  # Send a copy to the agent
                images=images,
                videos=videos,
                audio=audio,
                files=files,
                stream=False,
                debug_mode=debug_mode,
                dependencies=run_context.dependencies,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                metadata=run_context.metadata,
                knowledge_filters=run_context.knowledge_filters
                if not member_agent.knowledge_filters and member_agent.knowledge
                else None,
            )
            check_if_run_cancelled(member_agent_run_response)  # type: ignore

        # Check if the member run is paused (HITL)
        if member_agent_run_response is not None and member_agent_run_response.is_paused:
            _propagate_member_pause(run_response, member_agent, member_agent_run_response)
            use_team_logger()
            _process_delegate_task_to_member(
                member_agent_run_response,
                member_agent,
                member_agent_task,  # type: ignore
                member_session_state_copy,  # type: ignore
            )
            yield f"Member '{member_agent.name}' requires human input before continuing."
            return

        if not stream:
            try:
                if member_agent_run_response.content is None and (  # type: ignore
                    member_agent_run_response.tools is None or len(member_agent_run_response.tools) == 0  # type: ignore
                ):
                    yield "No response from the member agent."
                elif isinstance(member_agent_run_response.content, str):  # type: ignore
                    if len(member_agent_run_response.content.strip()) > 0:  # type: ignore
                        yield member_agent_run_response.content  # type: ignore

                    # If the content is empty but we have tool calls
                    elif (
                        member_agent_run_response.tools is not None  # type: ignore
                        and len(member_agent_run_response.tools) > 0  # type: ignore
                    ):
                        yield ",".join([tool.result for tool in member_agent_run_response.tools if tool.result])  # type: ignore
                elif issubclass(type(member_agent_run_response.content), BaseModel):  # type: ignore
                    yield member_agent_run_response.content.model_dump_json(indent=2)  # type: ignore
                else:
                    import json

                    yield json.dumps(member_agent_run_response.content, indent=2)  # type: ignore
            except Exception as e:
                yield str(e)

        # Afterward, switch back to the team logger
        use_team_logger()

        _process_delegate_task_to_member(
            member_agent_run_response,
            member_agent,
            member_agent_task,  # type: ignore
            member_session_state_copy,  # type: ignore
        )

    # When the task should be delegated to all members
    def delegate_task_to_members(task: str) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """
        Use this function to delegate a task to all the member agents and return a response.
        You must provide a clear and concise description of the task the member should achieve AND the expected output.

        Args:
            task (str): A clear and concise description of the task to send to member agents.
        Returns:
            str: The result of the delegated task.
        """
        from agno.utils.callables import get_resolved_members

        resolved_members = get_resolved_members(team, run_context) or []

        # Run all the members sequentially
        for _, member_agent in enumerate(resolved_members):
            member_agent_task, history = _setup_delegate_task_to_member(member_agent=member_agent, task=task)

            member_session_state_copy = copy(run_context.session_state)
            if stream:
                member_agent_run_response_stream = member_agent.run(
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    # All members have the same session_id
                    session_id=session.session_id,
                    session_state=member_session_state_copy,  # Send a copy to the agent
                    images=images,
                    videos=videos,
                    audio=audio,
                    files=files,
                    stream=True,
                    stream_events=stream_events or team.stream_member_events,
                    knowledge_filters=run_context.knowledge_filters
                    if not member_agent.knowledge_filters and member_agent.knowledge
                    else None,
                    debug_mode=debug_mode,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    metadata=run_context.metadata,
                    yield_run_output=True,
                )
                member_agent_run_response = None
                for member_agent_run_response_chunk in member_agent_run_response_stream:
                    # Do NOT break out of the loop, Iterator need to exit properly
                    if isinstance(member_agent_run_response_chunk, (TeamRunOutput, RunOutput)):
                        member_agent_run_response = member_agent_run_response_chunk  # type: ignore
                        continue  # Don't yield TeamRunOutput or RunOutput, only yield events

                    # Check if the run is cancelled
                    check_if_run_cancelled(member_agent_run_response_chunk)

                    # Yield the member event directly
                    member_agent_run_response_chunk.parent_run_id = member_agent_run_response_chunk.parent_run_id or (
                        run_response.run_id if run_response is not None else None
                    )
                    yield member_agent_run_response_chunk  # type: ignore

            else:
                member_agent_run_response = member_agent.run(  # type: ignore
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    # All members have the same session_id
                    session_id=session.session_id,
                    session_state=member_session_state_copy,  # Send a copy to the agent
                    images=images,
                    videos=videos,
                    audio=audio,
                    files=files,
                    stream=False,
                    knowledge_filters=run_context.knowledge_filters
                    if not member_agent.knowledge_filters and member_agent.knowledge
                    else None,
                    debug_mode=debug_mode,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    metadata=run_context.metadata,
                )

                check_if_run_cancelled(member_agent_run_response)  # type: ignore

            # Check if the member run is paused (HITL)
            if member_agent_run_response is not None and member_agent_run_response.is_paused:
                _propagate_member_pause(run_response, member_agent, member_agent_run_response)
                use_team_logger()
                _process_delegate_task_to_member(
                    member_agent_run_response,
                    member_agent,
                    member_agent_task,  # type: ignore
                    member_session_state_copy,  # type: ignore
                )
                yield f"Agent {member_agent.name}: Requires human input before continuing."
                continue

            if not stream:
                try:
                    if member_agent_run_response.content is None and (  # type: ignore
                        member_agent_run_response.tools is None or len(member_agent_run_response.tools) == 0  # type: ignore
                    ):
                        yield f"Agent {member_agent.name}: No response from the member agent."
                    elif isinstance(member_agent_run_response.content, str):  # type: ignore
                        if len(member_agent_run_response.content.strip()) > 0:  # type: ignore
                            yield f"Agent {member_agent.name}: {member_agent_run_response.content}"  # type: ignore
                        elif (
                            member_agent_run_response.tools is not None and len(member_agent_run_response.tools) > 0  # type: ignore
                        ):
                            yield f"Agent {member_agent.name}: {','.join([tool.result for tool in member_agent_run_response.tools])}"  # type: ignore
                    elif issubclass(type(member_agent_run_response.content), BaseModel):  # type: ignore
                        yield f"Agent {member_agent.name}: {member_agent_run_response.content.model_dump_json(indent=2)}"  # type: ignore
                    else:
                        import json

                        yield f"Agent {member_agent.name}: {json.dumps(member_agent_run_response.content, indent=2)}"  # type: ignore
                except Exception as e:
                    yield f"Agent {member_agent.name}: Error - {str(e)}"

            _process_delegate_task_to_member(
                member_agent_run_response,
                member_agent,
                member_agent_task,  # type: ignore
                member_session_state_copy,  # type: ignore
            )

        # After all the member runs, switch back to the team logger
        use_team_logger()

    # When the task should be delegated to all members
    async def adelegate_task_to_members(task: str) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Use this function to delegate a task to all the member agents and return a response.
        You must provide a clear and concise description of the task to send to member agents.

        Args:
            task (str): A clear and concise description of the task to send to member agents.
        Returns:
            str: The result of the delegated task.
        """
        from agno.utils.callables import get_resolved_members

        resolved_members = get_resolved_members(team, run_context) or []

        if stream:
            # Concurrent streaming: launch each member as a streaming worker and merge events
            done_marker = object()
            queue: "asyncio.Queue[Union[RunOutputEvent, TeamRunOutputEvent, str, object]]" = asyncio.Queue()

            async def stream_member(agent: Union[Agent, "Team"]) -> None:
                member_agent_task, history = _setup_delegate_task_to_member(member_agent=agent, task=task)  # type: ignore
                member_session_state_copy = copy(run_context.session_state)

                member_stream = agent.arun(  # type: ignore
                    input=member_agent_task if not history else history,
                    user_id=user_id,
                    session_id=session.session_id,
                    session_state=member_session_state_copy,  # Send a copy to the agent
                    images=images,
                    videos=videos,
                    audio=audio,
                    files=files,
                    stream=True,
                    stream_events=stream_events or team.stream_member_events,
                    debug_mode=debug_mode,
                    knowledge_filters=run_context.knowledge_filters
                    if not agent.knowledge_filters and agent.knowledge
                    else None,
                    dependencies=run_context.dependencies,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    metadata=run_context.metadata,
                    yield_run_output=True,
                )
                member_agent_run_response = None
                try:
                    try:
                        async for member_agent_run_output_event in member_stream:
                            # Do NOT break out of the loop, AsyncIterator need to exit properly
                            if isinstance(member_agent_run_output_event, (TeamRunOutput, RunOutput)):
                                member_agent_run_response = member_agent_run_output_event  # type: ignore
                                continue  # Don't yield TeamRunOutput or RunOutput, only yield events

                            check_if_run_cancelled(member_agent_run_output_event)
                            member_agent_run_output_event.parent_run_id = (
                                member_agent_run_output_event.parent_run_id
                                or (run_response.run_id if run_response is not None else None)
                            )
                            await queue.put(member_agent_run_output_event)
                    finally:
                        # Check if the member run is paused (HITL)
                        if member_agent_run_response is not None and member_agent_run_response.is_paused:
                            _propagate_member_pause(run_response, agent, member_agent_run_response)
                            _process_delegate_task_to_member(
                                member_agent_run_response,
                                agent,
                                member_agent_task,  # type: ignore
                                member_session_state_copy,  # type: ignore
                            )
                            await queue.put(f"Agent {agent.name}: Requires human input before continuing.")
                        else:
                            _process_delegate_task_to_member(
                                member_agent_run_response,
                                agent,
                                member_agent_task,  # type: ignore
                                member_session_state_copy,  # type: ignore
                            )
                finally:
                    await queue.put(done_marker)

            # Initialize and launch all members
            tasks: List[asyncio.Task[None]] = []
            for member_agent in resolved_members:
                current_agent = member_agent
                _initialize_member(team, current_agent)
                tasks.append(asyncio.create_task(stream_member(current_agent)))

            # Drain queue until all members reported done
            completed = 0
            try:
                while completed < len(tasks):
                    item = await queue.get()
                    if item is done_marker:
                        completed += 1
                    else:
                        yield item  # type: ignore
            finally:
                # Ensure tasks do not leak on cancellation
                for t in tasks:
                    if not t.done():
                        t.cancel()
                # Await cancellation to suppress warnings
                for t in tasks:
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        await t
        else:
            # Non-streaming concurrent run of members; collect results when done
            tasks = []
            for member_agent_index, member_agent in enumerate(resolved_members):
                current_agent = member_agent
                member_agent_task, history = _setup_delegate_task_to_member(member_agent=current_agent, task=task)

                async def run_member_agent(
                    member_agent=current_agent,
                    member_agent_task=member_agent_task,
                    history=history,
                    member_agent_index=member_agent_index,
                ) -> tuple[str, Optional[Union[Agent, "Team"]], Optional[Union[RunOutput, TeamRunOutput]]]:
                    member_session_state_copy = copy(run_context.session_state)

                    member_agent_run_response = await member_agent.arun(
                        input=member_agent_task if not history else history,
                        user_id=user_id,
                        # All members have the same session_id
                        session_id=session.session_id,
                        session_state=member_session_state_copy,  # Send a copy to the agent
                        images=images,
                        videos=videos,
                        audio=audio,
                        files=files,
                        stream=False,
                        stream_events=stream_events,
                        debug_mode=debug_mode,
                        knowledge_filters=run_context.knowledge_filters
                        if not member_agent.knowledge_filters and member_agent.knowledge
                        else None,
                        dependencies=run_context.dependencies,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        metadata=run_context.metadata,
                    )
                    check_if_run_cancelled(member_agent_run_response)

                    member_name = member_agent.name if member_agent.name else f"agent_{member_agent_index}"

                    # Check if the member run is paused (HITL) before processing
                    if member_agent_run_response is not None and member_agent_run_response.is_paused:
                        _process_delegate_task_to_member(
                            member_agent_run_response,
                            member_agent,
                            member_agent_task,  # type: ignore
                            member_session_state_copy,  # type: ignore
                        )
                        return (
                            f"Agent {member_name}: Requires human input before continuing.",
                            member_agent,
                            member_agent_run_response,
                        )

                    _process_delegate_task_to_member(
                        member_agent_run_response,
                        member_agent,
                        member_agent_task,  # type: ignore
                        member_session_state_copy,  # type: ignore
                    )

                    try:
                        if member_agent_run_response.content is None and (
                            member_agent_run_response.tools is None or len(member_agent_run_response.tools) == 0
                        ):
                            return (f"Agent {member_name}: No response from the member agent.", None, None)
                        elif isinstance(member_agent_run_response.content, str):
                            if len(member_agent_run_response.content.strip()) > 0:
                                return (f"Agent {member_name}: {member_agent_run_response.content}", None, None)
                            elif (
                                member_agent_run_response.tools is not None and len(member_agent_run_response.tools) > 0
                            ):
                                return (
                                    f"Agent {member_name}: {','.join([tool.result for tool in member_agent_run_response.tools])}",
                                    None,
                                    None,
                                )
                        elif issubclass(type(member_agent_run_response.content), BaseModel):
                            return (
                                f"Agent {member_name}: {member_agent_run_response.content.model_dump_json(indent=2)}",  # type: ignore
                                None,
                                None,
                            )
                        else:
                            import json

                            return (
                                f"Agent {member_name}: {json.dumps(member_agent_run_response.content, indent=2)}",
                                None,
                                None,
                            )
                    except Exception as e:
                        return (f"Agent {member_name}: Error - {str(e)}", None, None)

                    return (f"Agent {member_name}: No Response", None, None)

                tasks.append(run_member_agent)  # type: ignore

            results = await asyncio.gather(*[task() for task in tasks])  # type: ignore
            # Propagate pauses sequentially after all members complete
            for result_text, paused_agent, paused_run_response in results:
                if paused_agent is not None and paused_run_response is not None:
                    _propagate_member_pause(run_response, paused_agent, paused_run_response)
                yield result_text

        # After all the member runs, switch back to the team logger
        use_team_logger()

    if team.delegate_to_all_members:
        if async_mode:
            delegate_function = adelegate_task_to_members  # type: ignore
        else:
            delegate_function = delegate_task_to_members  # type: ignore

        delegate_func = Function.from_callable(delegate_function, name="delegate_task_to_members")
    else:
        if async_mode:
            delegate_function = adelegate_task_to_member  # type: ignore
        else:
            delegate_function = delegate_task_to_member  # type: ignore

        delegate_func = Function.from_callable(delegate_function, name="delegate_task_to_member")

    if team.respond_directly:
        delegate_func.stop_after_tool_call = True
        delegate_func.show_result = True

    return delegate_func


def add_to_knowledge(team: "Team", query: str, result: str) -> str:
    """Use this function to add information to the knowledge base for future use.

    Args:
        query (str): The query or topic to add.
        result (str): The actual content or information to store.

    Returns:
        str: A string indicating the status of the addition.
    """
    from agno.utils.callables import get_resolved_knowledge

    knowledge = get_resolved_knowledge(team, None)
    if knowledge is None:
        log_warning("Knowledge is not set, cannot add to knowledge")
        return "Knowledge is not set, cannot add to knowledge"

    insert_method = getattr(knowledge, "insert", None)
    if not callable(insert_method):
        log_warning("Knowledge base does not support adding content")
        return "Knowledge base does not support adding content"

    document_name = query.replace(" ", "_").replace("?", "").replace("!", "").replace(".", "")
    document_content = json.dumps({"query": query, "result": result})
    log_info(f"Adding document to Knowledge: {document_name}: {document_content}")
    from agno.knowledge.reader.text_reader import TextReader

    insert_method(name=document_name, text_content=document_content, reader=TextReader())
    return "Successfully added to knowledge base"


def create_knowledge_search_tool(
    team: "Team",
    run_response: Optional[TeamRunOutput] = None,
    run_context: Optional[RunContext] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    enable_agentic_filters: Optional[bool] = False,
    async_mode: bool = False,
) -> Function:
    """Create a unified search_knowledge_base tool for Team.

    Routes all knowledge searches through get_relevant_docs_from_knowledge(),
    which checks knowledge_retriever first and falls back to knowledge.search().
    """

    def _format_results(docs: Optional[List[Union[Dict[str, Any], str]]]) -> str:
        if not docs:
            return "No documents found"
        if team.references_format == "json":
            return json.dumps(docs, indent=2, default=str)
        else:
            import yaml

            return yaml.dump(docs, default_flow_style=False)

    def _track_references(docs: Optional[List[Union[Dict[str, Any], str]]], query: str, elapsed: float) -> None:
        if run_response is not None and docs:
            references = MessageReferences(
                query=query,
                references=docs,
                time=round(elapsed, 4),
            )
            if run_response.references is None:
                run_response.references = []
            run_response.references.append(references)

    def _resolve_filters(
        agentic_filters: Optional[List[Any]] = None,
    ) -> Optional[Union[Dict[str, Any], List[FilterExpr]]]:
        if agentic_filters:
            filters_dict: Dict[str, Any] = {}
            for filt in agentic_filters:
                if isinstance(filt, dict):
                    filters_dict.update(filt)
                elif hasattr(filt, "key") and hasattr(filt, "value"):
                    filters_dict[filt.key] = filt.value
            return get_agentic_or_user_search_filters(filters_dict, knowledge_filters)
        return knowledge_filters

    if enable_agentic_filters:

        def search_knowledge_base_with_filters(query: str, filters: Optional[List[KnowledgeFilter]] = None) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.
                filters (optional): The filters to apply to the search. This is a list of KnowledgeFilter objects.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            retrieval_timer = Timer()
            retrieval_timer.start()
            try:
                docs = get_relevant_docs_from_knowledge(
                    team,
                    query=query,
                    filters=_resolve_filters(filters),
                    validate_filters=True,
                    run_context=run_context,
                )
            except Exception as e:
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"
            _track_references(docs, query, retrieval_timer.elapsed)
            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")
            return _format_results(docs)

        async def asearch_knowledge_base_with_filters(
            query: str, filters: Optional[List[KnowledgeFilter]] = None
        ) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.
                filters (optional): The filters to apply to the search. This is a list of KnowledgeFilter objects.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            retrieval_timer = Timer()
            retrieval_timer.start()
            try:
                docs = await aget_relevant_docs_from_knowledge(
                    team,
                    query=query,
                    filters=_resolve_filters(filters),
                    validate_filters=True,
                    run_context=run_context,
                )
            except Exception as e:
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"
            _track_references(docs, query, retrieval_timer.elapsed)
            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")
            return _format_results(docs)

        if async_mode:
            return Function.from_callable(asearch_knowledge_base_with_filters, name="search_knowledge_base")
        return Function.from_callable(search_knowledge_base_with_filters, name="search_knowledge_base")

    else:

        def search_knowledge_base(query: str) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            retrieval_timer = Timer()
            retrieval_timer.start()
            try:
                docs = get_relevant_docs_from_knowledge(
                    team,
                    query=query,
                    filters=knowledge_filters,
                    run_context=run_context,
                )
            except Exception as e:
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"
            _track_references(docs, query, retrieval_timer.elapsed)
            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")
            return _format_results(docs)

        async def asearch_knowledge_base(query: str) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            retrieval_timer = Timer()
            retrieval_timer.start()
            try:
                docs = await aget_relevant_docs_from_knowledge(
                    team,
                    query=query,
                    filters=knowledge_filters,
                    run_context=run_context,
                )
            except Exception as e:
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"
            _track_references(docs, query, retrieval_timer.elapsed)
            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")
            return _format_results(docs)

        if async_mode:
            return Function.from_callable(asearch_knowledge_base, name="search_knowledge_base")
        return Function.from_callable(search_knowledge_base, name="search_knowledge_base")



def get_relevant_docs_from_knowledge(
    team: "Team",
    query: str,
    num_documents: Optional[int] = None,
    filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    validate_filters: bool = False,
    run_context: Optional[RunContext] = None,
    **kwargs,
) -> Optional[List[Union[Dict[str, Any], str]]]:
    """Return a list of references from the knowledge base"""
    from agno.knowledge.document import Document
    from agno.utils.callables import get_resolved_knowledge

    knowledge = get_resolved_knowledge(team, run_context)

    # Extract dependencies from run_context if available
    dependencies = run_context.dependencies if run_context else None

    if num_documents is None and knowledge is not None:
        num_documents = getattr(knowledge, "max_results", None)

    # Validate the filters against known valid filter keys
    if knowledge is not None and filters is not None and validate_filters:
        validate_filters_method = getattr(knowledge, "validate_filters", None)
        if callable(validate_filters_method):
            valid_filters, invalid_keys = validate_filters_method(filters)

            # Warn about invalid filter keys
            if invalid_keys:
                log_warning(f"Invalid filter keys provided: {invalid_keys}. These filters will be ignored.")

                # Only use valid filters
                filters = valid_filters
                if not filters:
                    log_warning("No valid filters remain after validation. Search will proceed without filters.")

            if invalid_keys == [] and valid_filters == {}:
                log_debug("No valid filters provided. Search will proceed without filters.")
                filters = None

    if team.knowledge_retriever is not None and callable(team.knowledge_retriever):
        from inspect import signature

        try:
            sig = signature(team.knowledge_retriever)
            knowledge_retriever_kwargs: Dict[str, Any] = {}
            if "team" in sig.parameters:
                knowledge_retriever_kwargs = {"team": team}
            if "filters" in sig.parameters:
                knowledge_retriever_kwargs["filters"] = filters
            if "run_context" in sig.parameters:
                knowledge_retriever_kwargs["run_context"] = run_context
            elif "dependencies" in sig.parameters:
                # Backward compatibility: support dependencies parameter
                knowledge_retriever_kwargs["dependencies"] = dependencies
            knowledge_retriever_kwargs.update({"query": query, "num_documents": num_documents, **kwargs})
            return team.knowledge_retriever(**knowledge_retriever_kwargs)
        except Exception as e:
            log_warning(f"Knowledge retriever failed: {e}")
            raise e
    # Use knowledge protocol's retrieve method
    try:
        if knowledge is None:
            return None

        # Use protocol retrieve() method if available
        retrieve_fn = getattr(knowledge, "retrieve", None)
        if not callable(retrieve_fn):
            log_debug("Knowledge does not implement retrieve()")
            return None

        if num_documents is None:
            num_documents = getattr(knowledge, "max_results", 10)

        log_debug(f"Retrieving from knowledge base with filters: {filters}")
        relevant_docs: List[Document] = retrieve_fn(query=query, max_results=num_documents, filters=filters)

        if not relevant_docs or len(relevant_docs) == 0:
            log_debug("No relevant documents found for query")
            return None

        return [doc.to_dict() for doc in relevant_docs]
    except Exception as e:
        log_warning(f"Error retrieving from knowledge base: {e}")
        raise e


async def aget_relevant_docs_from_knowledge(
    team: "Team",
    query: str,
    num_documents: Optional[int] = None,
    filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    validate_filters: bool = False,
    run_context: Optional[RunContext] = None,
    **kwargs,
) -> Optional[List[Union[Dict[str, Any], str]]]:
    """Get relevant documents from knowledge base asynchronously."""
    from agno.knowledge.document import Document
    from agno.utils.callables import get_resolved_knowledge

    knowledge = get_resolved_knowledge(team, run_context)

    # Extract dependencies from run_context if available
    dependencies = run_context.dependencies if run_context else None

    if num_documents is None and knowledge is not None:
        num_documents = getattr(knowledge, "max_results", None)

    # Validate the filters against known valid filter keys
    if knowledge is not None and filters is not None and validate_filters:
        avalidate_filters_method = getattr(knowledge, "avalidate_filters", None)
        if callable(avalidate_filters_method):
            valid_filters, invalid_keys = await avalidate_filters_method(filters)

            # Warn about invalid filter keys
            if invalid_keys:
                log_warning(f"Invalid filter keys provided: {invalid_keys}. These filters will be ignored.")

                # Only use valid filters
                filters = valid_filters
                if not filters:
                    log_warning("No valid filters remain after validation. Search will proceed without filters.")

            if invalid_keys == [] and valid_filters == {}:
                log_debug("No valid filters provided. Search will proceed without filters.")
                filters = None

    if team.knowledge_retriever is not None and callable(team.knowledge_retriever):
        from inspect import isawaitable, signature

        try:
            sig = signature(team.knowledge_retriever)
            knowledge_retriever_kwargs: Dict[str, Any] = {}
            if "team" in sig.parameters:
                knowledge_retriever_kwargs = {"team": team}
            if "filters" in sig.parameters:
                knowledge_retriever_kwargs["filters"] = filters
            if "run_context" in sig.parameters:
                knowledge_retriever_kwargs["run_context"] = run_context
            elif "dependencies" in sig.parameters:
                # Backward compatibility: support dependencies parameter
                knowledge_retriever_kwargs["dependencies"] = dependencies
            knowledge_retriever_kwargs.update({"query": query, "num_documents": num_documents, **kwargs})

            result = team.knowledge_retriever(**knowledge_retriever_kwargs)

            if isawaitable(result):
                result = await result

            return result
        except Exception as e:
            log_warning(f"Knowledge retriever failed: {e}")
            raise e

    # Use knowledge protocol's retrieve method
    try:
        if knowledge is None:
            return None

        # Use protocol aretrieve() or retrieve() method if available
        aretrieve_fn = getattr(knowledge, "aretrieve", None)
        retrieve_fn = getattr(knowledge, "retrieve", None)

        if not callable(aretrieve_fn) and not callable(retrieve_fn):
            log_debug("Knowledge does not implement retrieve()")
            return None

        if num_documents is None:
            num_documents = getattr(knowledge, "max_results", 10)

        log_debug(f"Retrieving from knowledge base with filters: {filters}")

        if callable(aretrieve_fn):
            relevant_docs: List[Document] = await aretrieve_fn(query=query, max_results=num_documents, filters=filters)
        elif callable(retrieve_fn):
            relevant_docs = retrieve_fn(query=query, max_results=num_documents, filters=filters)
        else:
            return None

        if not relevant_docs or len(relevant_docs) == 0:
            log_debug("No relevant documents found for query")
            return None

        return [doc.to_dict() for doc in relevant_docs]
    except Exception as e:
        log_warning(f"Error retrieving from knowledge base: {e}")
        raise e
