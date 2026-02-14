"""Prompt/message building and deep-copy helpers for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.team import Team

import json
from collections import ChainMap
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Type,
    Union,
    cast,
)

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message, MessageReferences
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.messages import RunMessages
from agno.run.team import (
    TeamRunOutput,
)
from agno.session import TeamSession
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.agent import (
    aexecute_instructions,
    aexecute_system_message,
    execute_instructions,
    execute_system_message,
)
from agno.utils.common import is_typed_dict
from agno.utils.log import (
    log_debug,
    log_warning,
)
from agno.utils.message import filter_tool_calls, get_text_from_message
from agno.utils.team import (
    get_member_id,
)
from agno.utils.timer import Timer


def _get_tool_names(member: Any) -> List[str]:
    """Extract tool names from a member's tools list."""
    tool_names: List[str] = []
    if member.tools is None or not isinstance(member.tools, list):
        return tool_names
    for _tool in member.tools:
        if isinstance(_tool, Toolkit):
            for _func in _tool.functions.values():
                if _func.entrypoint:
                    tool_names.append(_func.name)
        elif isinstance(_tool, Function) and _tool.entrypoint:
            tool_names.append(_tool.name)
        elif callable(_tool):
            tool_names.append(_tool.__name__)
        elif isinstance(_tool, dict) and "name" in _tool and _tool.get("name") is not None:
            tool_names.append(_tool["name"])
        else:
            tool_names.append(str(_tool))
    return tool_names


def get_members_system_message_content(
    team: "Team", indent: int = 0, run_context: Optional["RunContext"] = None
) -> str:
    from agno.team.team import Team
    from agno.utils.callables import get_resolved_members

    pad = " " * indent
    content = ""
    resolved_members = get_resolved_members(team, run_context)
    if resolved_members is None or len(resolved_members) == 0:
        return content
    for member in resolved_members:
        member_id = get_member_id(member)

        if isinstance(member, Team):
            content += f'{pad}<member id="{member_id}" name="{member.name}" type="team">\n'
            if member.description is not None:
                content += f"{pad}  Description: {member.description}\n"
            if member.members is not None:
                content += member.get_members_system_message_content(indent=indent + 2, run_context=run_context)
            content += f"{pad}</member>\n"
        else:
            content += f'{pad}<member id="{member_id}" name="{member.name}">\n'
            if member.role is not None:
                content += f"{pad}  Role: {member.role}\n"
            if member.description is not None:
                content += f"{pad}  Description: {member.description}\n"
            if team.add_member_tools_to_context:
                tool_names = _get_tool_names(member)
                if tool_names:
                    content += f"{pad}  Tools: {', '.join(tool_names)}\n"
            content += f"{pad}</member>\n"

    return content


def _get_opening_prompt() -> str:
    """Opening identity statement for the team leader."""
    return (
        "You coordinate a team of specialized AI agents to fulfill the user's request. "
        "Delegate to members when their expertise or tools are needed. "
        "For straightforward requests you can handle directly — including using your own tools — respond without delegating.\n"
    )


def _get_mode_instructions(team: "Team") -> str:
    """Return the mode-specific <how_to_respond> block."""
    from agno.team.mode import TeamMode

    content = "\n<how_to_respond>\n"

    if team.mode == TeamMode.tasks:
        content += (
            "You operate in autonomous task mode. Decompose the user's goal into discrete tasks, "
            "execute them by delegating to team members, and deliver the final result.\n\n"
            "Planning:\n"
            "- Break the goal into tasks with clear, actionable titles and self-contained descriptions. "
            "Each task should be a single unit of work for one member.\n"
            "- Assign each task to the member whose role and tools are best suited.\n"
            "- Set `depends_on` when a task requires another task's output. "
            "Leave tasks independent when they can run in any order.\n\n"
            "Execution:\n"
            "- Use `execute_task` for sequential or dependent tasks.\n"
            "- Use `execute_tasks_parallel` for groups of independent tasks to maximize throughput.\n"
            "- Review each result before proceeding. If a task fails, decide whether to retry with the same member, "
            "reassign to a different member, or adjust the plan.\n\n"
            "Completion:\n"
            "- When all tasks are done and results are satisfactory, call `mark_all_complete` with a summary of the outcome.\n"
            "- Use `list_tasks` to check progress at any point, and `add_task_note` to record observations.\n\n"
            "Write task descriptions that give the member everything they need: "
            "the objective, relevant context from the conversation or prior task results, and what a good result looks like.\n"
        )
    elif team.mode == TeamMode.route:
        content += (
            "You operate in route mode. For requests that need member expertise, "
            "identify the single best member and delegate to them — their response is returned directly to the user. "
            "For requests you can handle directly — simple questions, using your own tools, or general conversation — "
            "respond without delegating.\n\n"
            "When routing to a member:\n"
            "- Analyze the request to determine which member's role and tools are the best match.\n"
            "- Delegate to exactly one member. Use only the member's ID — do not prefix it with the team ID.\n"
            "- Write the task to faithfully represent the user's full intent. Do not reinterpret or narrow the request.\n"
            "- If no member is a clear fit, choose the closest match and include any additional context the member might need.\n"
        )
    elif team.mode == TeamMode.broadcast:
        content += (
            "You operate in broadcast mode. For requests that benefit from multiple perspectives, "
            "send the request to all members simultaneously and synthesize their collective responses. "
            "For requests you can handle directly — simple questions, using your own tools, or general conversation — "
            "respond without delegating.\n\n"
            "When broadcasting:\n"
            "- Call `delegate_task_to_members` exactly once with a clear task description. "
            "This sends the task to every member in parallel.\n"
            "- Write the task so each member can respond independently from their own perspective.\n\n"
            "After receiving member responses:\n"
            "- Compare perspectives: note agreements, highlight complementary insights, and reconcile any contradictions.\n"
            "- Synthesize into a unified answer that integrates the strongest contributions thematically — "
            "do not list each member's response sequentially.\n"
        )
    else:
        # coordinate mode (default)
        content += (
            "You operate in coordinate mode. For requests that need member expertise, "
            "select the best member(s), delegate with clear task descriptions, and synthesize their outputs "
            "into a unified response. For requests you can handle directly — simple questions, "
            "using your own tools, or general conversation — respond without delegating.\n\n"
            "Delegation:\n"
            "- Match each sub-task to the member whose role and tools are the best fit. "
            "Delegate to multiple members when the request spans different areas of expertise.\n"
            "- Write task descriptions that are self-contained: state the goal, provide relevant context "
            "from the conversation, and describe what a good result looks like.\n"
            "- Use only the member's ID when delegating — do not prefix it with the team ID.\n\n"
            "After receiving member responses:\n"
            "- If a response is incomplete or off-target, re-delegate with clearer instructions or try a different member.\n"
            "- Synthesize all results into a single coherent response. Resolve contradictions, fill gaps with your own "
            "reasoning, and add structure — do not simply concatenate member outputs.\n"
        )

    content += "</how_to_respond>\n\n"
    return content


def _build_team_context(
    team: "Team",
    run_context: Optional["RunContext"] = None,
) -> str:
    """Build the opening + team_members + how_to_respond blocks.

    Shared between sync and async system-message builders.
    """
    from agno.utils.callables import get_resolved_members

    content = ""
    resolved_members = get_resolved_members(team, run_context)
    if resolved_members is not None and len(resolved_members) > 0:
        content += _get_opening_prompt()
        content += "\n<team_members>\n"
        content += team.get_members_system_message_content(run_context=run_context)
        if team.get_member_information_tool:
            content += "If you need to get information about your team members, you can use the `get_member_information` tool at any time.\n"
        content += "</team_members>\n"
        content += _get_mode_instructions(team)
    return content


def _build_identity_sections(
    team: "Team",
    instructions: List[str],
) -> str:
    """Build description, role, and instructions sections.

    Shared between sync and async system-message builders.
    """
    content = ""
    if team.description is not None:
        content += f"<description>\n{team.description}\n</description>\n\n"

    if team.role is not None:
        content += f"<your_role>\n{team.role}\n</your_role>\n\n"

    if len(instructions) > 0:
        if team.use_instruction_tags:
            content += "<instructions>"
            if len(instructions) > 1:
                for _upi in instructions:
                    content += f"\n- {_upi}"
            else:
                content += "\n" + instructions[0]
            content += "\n</instructions>\n\n"
        else:
            if len(instructions) > 1:
                for _upi in instructions:
                    content += f"- {_upi}\n"
            else:
                content += instructions[0] + "\n\n"
    return content


def _build_trailing_sections(
    team: "Team",
    *,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    additional_information: List[str],
    tools: Optional[List[Union[Function, dict]]] = None,
    output_schema: Optional[Any] = None,
    run_context: Optional[RunContext] = None,
    session_state: Optional[Dict[str, Any]] = None,
    add_session_state_to_context: Optional[bool] = None,
) -> str:
    """Build media, additional info, tool instructions, and other trailing sections.

    Shared between sync and async system-message builders.
    """
    content = ""

    # Attached media
    if audio is not None or images is not None or videos is not None or files is not None:
        content += "<attached_media>\n"
        content += "You have the following media attached to your message:\n"
        if audio is not None and len(audio) > 0:
            content += " - Audio\n"
        if images is not None and len(images) > 0:
            content += " - Images\n"
        if videos is not None and len(videos) > 0:
            content += " - Videos\n"
        if files is not None and len(files) > 0:
            content += " - Files\n"
        content += "</attached_media>\n\n"

    # Additional information
    if len(additional_information) > 0:
        content += "<additional_information>"
        for _ai in additional_information:
            content += f"\n- {_ai}"
        content += "\n</additional_information>\n\n"

    # Tool instructions
    if team._tool_instructions is not None:
        for _ti in team._tool_instructions:
            content += f"{_ti}\n"

    system_message_from_model = team.model.get_system_message_for_model(tools)  # type: ignore[union-attr]
    if system_message_from_model is not None:
        content += system_message_from_model

    if team.expected_output is not None:
        content += f"<expected_output>\n{team.expected_output.strip()}\n</expected_output>\n\n"

    if team.additional_context is not None:
        content += f"<additional_context>\n{team.additional_context.strip()}\n</additional_context>\n\n"

    if add_session_state_to_context and session_state is not None:
        content += _get_formatted_session_state_for_system_message(team, session_state)

    # JSON output prompt
    if (
        output_schema is not None
        and team.parser_model is None
        and team.model
        and not (
            (team.model.supports_native_structured_outputs or team.model.supports_json_schema_outputs)
            and not team.use_json_mode
        )
    ):
        content += f"{_get_json_output_prompt(team, output_schema)}"

    return content


def get_system_message(
    team: "Team",
    session: TeamSession,
    run_context: Optional[RunContext] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    tools: Optional[List[Union[Function, dict]]] = None,
    add_session_state_to_context: Optional[bool] = None,
) -> Optional[Message]:
    """Get the system message for the team.

    1. If the system_message is provided, use that.
    2. If build_context is False, return None.
    3. Build and return the default system message for the Team.
    """

    # Extract values from run_context
    from agno.team._init import _has_async_db, _set_memory_manager

    session_state = run_context.session_state if run_context else None
    user_id = run_context.user_id if run_context else None

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    # 1. If the system_message is provided, use that.
    if team.system_message is not None:
        if isinstance(team.system_message, Message):
            return team.system_message

        sys_message_content: str = ""
        if isinstance(team.system_message, str):
            sys_message_content = team.system_message
        elif callable(team.system_message):
            sys_message_content = execute_system_message(
                system_message=team.system_message,
                agent=cast(Any, team),
                team=cast(Any, team),
                session_state=session_state,
                run_context=run_context,
            )
            if not isinstance(sys_message_content, str):
                raise Exception("system_message must return a string")

        # Format the system message with the session state variables
        if team.resolve_in_context:
            sys_message_content = _format_message_with_state_variables(
                team,
                sys_message_content,
                run_context=run_context,
            )

        # type: ignore
        return Message(role=team.system_message_role, content=sys_message_content)

    # 1. Build and return the default system message for the Team.
    # 1.1 Build the list of instructions for the system message
    team.model = cast(Model, team.model)
    instructions: List[str] = []
    if team.instructions is not None:
        _instructions = team.instructions
        if callable(team.instructions):
            _instructions = execute_instructions(
                instructions=team.instructions,
                agent=cast(Any, team),
                team=cast(Any, team),
                session_state=session_state,
                run_context=run_context,
            )

        if isinstance(_instructions, str):
            instructions.append(_instructions)
        elif isinstance(_instructions, list):
            instructions.extend(_instructions)

    # 1.2 Add instructions from the Model
    _model_instructions = team.model.get_instructions_for_model(tools)
    if _model_instructions is not None:
        instructions.extend(_model_instructions)

    # 1.3 Build a list of additional information for the system message
    additional_information: List[str] = []
    # 1.3.1 Add instructions for using markdown
    if team.markdown and output_schema is None:
        additional_information.append("Use markdown to format your answers.")
    # 1.3.2 Add the current datetime
    if team.add_datetime_to_context:
        from datetime import datetime

        tz = None

        if team.timezone_identifier:
            try:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(team.timezone_identifier)
            except Exception:
                log_warning("Invalid timezone identifier")

        time = datetime.now(tz) if tz else datetime.now()

        additional_information.append(f"The current time is {time}.")

    # 1.3.3 Add the current location
    if team.add_location_to_context:
        from agno.utils.location import get_location

        location = get_location()
        if location:
            location_str = ", ".join(
                filter(None, [location.get("city"), location.get("region"), location.get("country")])
            )
            if location_str:
                additional_information.append(f"Your approximate location is: {location_str}.")

    # 1.3.4 Add team name if provided
    if team.name is not None and team.add_name_to_context:
        additional_information.append(f"Your name is: {team.name}.")

    # 2 Build the default system message for the Team.
    system_message_content: str = ""

    # 2.1 Opening + team members + mode instructions
    system_message_content += _build_team_context(team, run_context=run_context)

    # 2.2 Identity sections: description, role, instructions
    system_message_content += _build_identity_sections(team, instructions)

    # 2.3 Knowledge base instructions
    if team.knowledge is not None and team.search_knowledge and team.add_search_knowledge_instructions:
        build_context_fn = getattr(team.knowledge, "build_context", None)
        if callable(build_context_fn):
            knowledge_context = build_context_fn(
                enable_agentic_filters=team.enable_agentic_knowledge_filters,
            )
            if knowledge_context:
                system_message_content += knowledge_context + "\n"

    # 2.4 Memories
    if team.add_memories_to_context:
        _memory_manager_not_set = False
        if not user_id:
            user_id = "default"
        if team.memory_manager is None:
            _set_memory_manager(team)
            _memory_manager_not_set = True
        if _has_async_db(team):
            raise ValueError(
                "Sync get_system_message cannot retrieve user memories with an async database. "
                "Use aget_system_message instead."
            )
        user_memories = team.memory_manager.get_user_memories(user_id=user_id)  # type: ignore
        if user_memories and len(user_memories) > 0:
            system_message_content += "You have access to user info and preferences from previous interactions that you can use to personalize your response:\n\n"
            system_message_content += "<memories_from_previous_interactions>"
            for _memory in user_memories:  # type: ignore
                system_message_content += f"\n- {_memory.memory}"
            system_message_content += "\n</memories_from_previous_interactions>\n\n"
            system_message_content += (
                "Note: this information is from previous interactions and may be updated in this conversation. "
                "You should always prefer information from this conversation over the past memories.\n"
            )
        else:
            system_message_content += (
                "You have the capability to retain memories from previous interactions with the user, "
                "but have not had any interactions with the user yet.\n"
            )
        if _memory_manager_not_set:
            team.memory_manager = None

        if team.enable_agentic_memory:
            system_message_content += (
                "\n<updating_user_memories>\n"
                "- You have access to the `update_user_memory` tool that you can use to add new memories, update existing memories, delete memories, or clear all memories.\n"
                "- If the user's message includes information that should be captured as a memory, use the `update_user_memory` tool to update your memory database.\n"
                "- Memories should include details that could personalize ongoing interactions with the user.\n"
                "- Use this tool to add new memories or update existing memories that you identify in the conversation.\n"
                "- Use this tool if the user asks to update their memory, delete a memory, or clear all memories.\n"
                "- If you use the `update_user_memory` tool, remember to pass on the response to the user.\n"
                "</updating_user_memories>\n\n"
            )

    # 2.5 Session summary
    if team.add_session_summary_to_context and session.summary is not None:
        system_message_content += "Here is a brief summary of your previous interactions:\n\n"
        system_message_content += "<summary_of_previous_interactions>\n"
        system_message_content += session.summary.summary
        system_message_content += "\n</summary_of_previous_interactions>\n\n"
        system_message_content += (
            "Note: this information is from previous interactions and may be outdated. "
            "You should ALWAYS prefer information from this conversation over the past summary.\n\n"
        )

    # 2.6 Trailing sections: media, additional info, tools, expected output, etc.
    system_message_content += _build_trailing_sections(
        team,
        audio=audio,
        images=images,
        videos=videos,
        files=files,
        additional_information=additional_information,
        tools=tools,
        output_schema=output_schema,
        run_context=run_context,
        session_state=session_state,
        add_session_state_to_context=add_session_state_to_context,
    )

    # Format the full system message with dependencies and session state variables
    if team.resolve_in_context:
        system_message_content = _format_message_with_state_variables(
            team,
            system_message_content,
            run_context=run_context,
        )

    return Message(role=team.system_message_role, content=system_message_content.strip())


async def aget_system_message(
    team: "Team",
    session: TeamSession,
    run_context: Optional[RunContext] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    tools: Optional[List[Union[Function, dict]]] = None,
    add_session_state_to_context: Optional[bool] = None,
) -> Optional[Message]:
    """Get the system message for the team."""

    # Extract values from run_context
    from agno.team._init import _has_async_db, _set_memory_manager

    session_state = run_context.session_state if run_context else None
    user_id = run_context.user_id if run_context else None

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    # 1. If the system_message is provided, use that.
    if team.system_message is not None:
        if isinstance(team.system_message, Message):
            return team.system_message

        sys_message_content: str = ""
        if isinstance(team.system_message, str):
            sys_message_content = team.system_message
        elif callable(team.system_message):
            sys_message_content = await aexecute_system_message(
                system_message=team.system_message,
                agent=cast(Any, team),
                team=cast(Any, team),
                session_state=session_state,
                run_context=run_context,
            )
            if not isinstance(sys_message_content, str):
                raise Exception("system_message must return a string")

        # Format the system message with the session state variables
        if team.resolve_in_context:
            sys_message_content = _format_message_with_state_variables(
                team,
                sys_message_content,
                run_context=run_context,
            )

        # type: ignore
        return Message(role=team.system_message_role, content=sys_message_content)

    # 1. Build and return the default system message for the Team.
    # 1.1 Build the list of instructions for the system message
    team.model = cast(Model, team.model)
    instructions: List[str] = []
    if team.instructions is not None:
        _instructions = team.instructions
        if callable(team.instructions):
            _instructions = await aexecute_instructions(
                instructions=team.instructions,
                agent=cast(Any, team),
                team=cast(Any, team),
                session_state=session_state,
                run_context=run_context,
            )

        if isinstance(_instructions, str):
            instructions.append(_instructions)
        elif isinstance(_instructions, list):
            instructions.extend(_instructions)

    # 1.2 Add instructions from the Model
    _model_instructions = team.model.get_instructions_for_model(tools)
    if _model_instructions is not None:
        instructions.extend(_model_instructions)

    # 1.3 Build a list of additional information for the system message
    additional_information: List[str] = []
    # 1.3.1 Add instructions for using markdown
    if team.markdown and output_schema is None:
        additional_information.append("Use markdown to format your answers.")
    # 1.3.2 Add the current datetime
    if team.add_datetime_to_context:
        from datetime import datetime

        tz = None

        if team.timezone_identifier:
            try:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(team.timezone_identifier)
            except Exception:
                log_warning("Invalid timezone identifier")

        time = datetime.now(tz) if tz else datetime.now()

        additional_information.append(f"The current time is {time}.")

    # 1.3.3 Add the current location
    if team.add_location_to_context:
        from agno.utils.location import get_location

        location = get_location()
        if location:
            location_str = ", ".join(
                filter(None, [location.get("city"), location.get("region"), location.get("country")])
            )
            if location_str:
                additional_information.append(f"Your approximate location is: {location_str}.")

    # 1.3.4 Add team name if provided
    if team.name is not None and team.add_name_to_context:
        additional_information.append(f"Your name is: {team.name}.")

    # 2 Build the default system message for the Team.
    system_message_content: str = ""

    # 2.1 Opening + team members + mode instructions
    system_message_content += _build_team_context(team, run_context=run_context)

    # 2.2 Identity sections: description, role, instructions
    system_message_content += _build_identity_sections(team, instructions)

    # 2.3 Knowledge base instructions
    if team.knowledge is not None and team.search_knowledge and team.add_search_knowledge_instructions:
        build_context_fn = getattr(team.knowledge, "build_context", None)
        if callable(build_context_fn):
            knowledge_context = build_context_fn(
                enable_agentic_filters=team.enable_agentic_knowledge_filters,
            )
            if knowledge_context:
                system_message_content += knowledge_context + "\n"

    # 2.4 Memories
    if team.add_memories_to_context:
        _memory_manager_not_set = False
        if not user_id:
            user_id = "default"
        if team.memory_manager is None:
            _set_memory_manager(team)
            _memory_manager_not_set = True

        if _has_async_db(team):
            user_memories = await team.memory_manager.aget_user_memories(user_id=user_id)  # type: ignore
        else:
            user_memories = team.memory_manager.get_user_memories(user_id=user_id)  # type: ignore

        if user_memories and len(user_memories) > 0:
            system_message_content += "You have access to user info and preferences from previous interactions that you can use to personalize your response:\n\n"
            system_message_content += "<memories_from_previous_interactions>"
            for _memory in user_memories:  # type: ignore
                system_message_content += f"\n- {_memory.memory}"
            system_message_content += "\n</memories_from_previous_interactions>\n\n"
            system_message_content += (
                "Note: this information is from previous interactions and may be updated in this conversation. "
                "You should always prefer information from this conversation over the past memories.\n"
            )
        else:
            system_message_content += (
                "You have the capability to retain memories from previous interactions with the user, "
                "but have not had any interactions with the user yet.\n"
            )
        if _memory_manager_not_set:
            team.memory_manager = None

        if team.enable_agentic_memory:
            system_message_content += (
                "\n<updating_user_memories>\n"
                "- You have access to the `update_user_memory` tool that you can use to add new memories, update existing memories, delete memories, or clear all memories.\n"
                "- If the user's message includes information that should be captured as a memory, use the `update_user_memory` tool to update your memory database.\n"
                "- Memories should include details that could personalize ongoing interactions with the user.\n"
                "- Use this tool to add new memories or update existing memories that you identify in the conversation.\n"
                "- Use this tool if the user asks to update their memory, delete a memory, or clear all memories.\n"
                "- If you use the `update_user_memory` tool, remember to pass on the response to the user.\n"
                "</updating_user_memories>\n\n"
            )

    # 2.5 Session summary
    if team.add_session_summary_to_context and session.summary is not None:
        system_message_content += "Here is a brief summary of your previous interactions:\n\n"
        system_message_content += "<summary_of_previous_interactions>\n"
        system_message_content += session.summary.summary
        system_message_content += "\n</summary_of_previous_interactions>\n\n"
        system_message_content += (
            "Note: this information is from previous interactions and may be outdated. "
            "You should ALWAYS prefer information from this conversation over the past summary.\n\n"
        )

    # 2.6 Trailing sections: media, additional info, tools, expected output, etc.
    system_message_content += _build_trailing_sections(
        team,
        audio=audio,
        images=images,
        videos=videos,
        files=files,
        additional_information=additional_information,
        tools=tools,
        output_schema=output_schema,
        run_context=run_context,
        session_state=session_state,
        add_session_state_to_context=add_session_state_to_context,
    )

    # Format the full system message with dependencies and session state variables
    if team.resolve_in_context:
        system_message_content = _format_message_with_state_variables(
            team,
            system_message_content,
            run_context=run_context,
        )

    return Message(role=team.system_message_role, content=system_message_content.strip())


def _get_formatted_session_state_for_system_message(team: "Team", session_state: Dict[str, Any]) -> str:
    return f"\n<session_state>\n{session_state}\n</session_state>\n\n"


def _get_run_messages(
    team: "Team",
    *,
    run_response: TeamRunOutput,
    run_context: RunContext,
    session: TeamSession,
    user_id: Optional[str] = None,
    input_message: Optional[Union[str, List, Dict, Message, BaseModel, List[Message]]] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    tools: Optional[List[Union[Function, dict]]] = None,
    **kwargs: Any,
) -> RunMessages:
    """This function returns a RunMessages object with the following attributes:
        - system_message: The system message for this run
        - user_message: The user message for this run
        - messages: List of messages to send to the model

    To build the RunMessages object:
    1. Add system message to run_messages
    2. Add extra messages to run_messages
    3. Add history to run_messages
    4. Add messages to run_messages if provided (messages parameter first)
    5. Add user message to run_messages (message parameter second)

    """
    # Initialize the RunMessages object
    run_messages = RunMessages()

    # 1. Add system message to run_messages
    system_message = team.get_system_message(
        session=session,
        run_context=run_context,
        images=images,
        audio=audio,
        videos=videos,
        files=files,
        add_session_state_to_context=add_session_state_to_context,
        tools=tools,
    )
    if system_message is not None:
        run_messages.system_message = system_message
        run_messages.messages.append(system_message)

    # 2. Add extra messages to run_messages if provided
    if team.additional_input is not None:
        messages_to_add_to_run_response: List[Message] = []
        if run_messages.extra_messages is None:
            run_messages.extra_messages = []

        for _m in team.additional_input:
            if isinstance(_m, Message):
                messages_to_add_to_run_response.append(_m)
                run_messages.messages.append(_m)
                run_messages.extra_messages.append(_m)
            elif isinstance(_m, dict):
                try:
                    _m_parsed = Message.model_validate(_m)
                    messages_to_add_to_run_response.append(_m_parsed)
                    run_messages.messages.append(_m_parsed)
                    run_messages.extra_messages.append(_m_parsed)
                except Exception as e:
                    log_warning(f"Failed to validate message: {e}")
        # Add the extra messages to the run_response
        if len(messages_to_add_to_run_response) > 0:
            log_debug(f"Adding {len(messages_to_add_to_run_response)} extra messages")
            if run_response.additional_input is None:
                run_response.additional_input = messages_to_add_to_run_response
            else:
                run_response.additional_input.extend(messages_to_add_to_run_response)

    # 3. Add history to run_messages
    if add_history_to_context:
        from copy import deepcopy

        # Only skip messages from history when system_message_role is NOT a standard conversation role.
        # Standard conversation roles ("user", "assistant", "tool") should never be filtered
        # to preserve conversation continuity.
        skip_role = team.system_message_role if team.system_message_role not in ["user", "assistant", "tool"] else None

        history = session.get_messages(
            last_n_runs=team.num_history_runs,
            limit=team.num_history_messages,
            skip_roles=[skip_role] if skip_role else None,
            team_id=team.id if team.parent_team_id is not None else None,
        )

        if len(history) > 0:
            # Create a deep copy of the history messages to avoid modifying the original messages
            history_copy = [deepcopy(msg) for msg in history]

            # Tag each message as coming from history
            for _msg in history_copy:
                _msg.from_history = True

            # Filter tool calls from history messages
            if team.max_tool_calls_from_history is not None:
                filter_tool_calls(history_copy, team.max_tool_calls_from_history)

            log_debug(f"Adding {len(history_copy)} messages from history")

            # Extend the messages with the history
            run_messages.messages += history_copy

    # 5. Add user message to run_messages (message second as per Dirk's requirement)
    # 5.1 Build user message if message is None, str or list
    user_message = _get_user_message(
        team,
        run_response=run_response,
        run_context=run_context,
        input_message=input_message,
        user_id=user_id,
        audio=audio,
        images=images,
        videos=videos,
        files=files,
        add_dependencies_to_context=add_dependencies_to_context,
        **kwargs,
    )
    # Add user message to run_messages
    if user_message is not None:
        run_messages.user_message = user_message
        run_messages.messages.append(user_message)

    return run_messages


async def _aget_run_messages(
    team: "Team",
    *,
    run_response: TeamRunOutput,
    run_context: RunContext,
    session: TeamSession,
    user_id: Optional[str] = None,
    input_message: Optional[Union[str, List, Dict, Message, BaseModel, List[Message]]] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    tools: Optional[List[Union[Function, dict]]] = None,
    **kwargs: Any,
) -> RunMessages:
    """This function returns a RunMessages object with the following attributes:
        - system_message: The system message for this run
        - user_message: The user message for this run
        - messages: List of messages to send to the model

    To build the RunMessages object:
    1. Add system message to run_messages
    2. Add extra messages to run_messages
    3. Add history to run_messages
    4. Add messages to run_messages if provided (messages parameter first)
    5. Add user message to run_messages (message parameter second)

    """
    # Initialize the RunMessages object
    run_messages = RunMessages()

    # 1. Add system message to run_messages
    system_message = await team.aget_system_message(
        session=session,
        run_context=run_context,
        images=images,
        audio=audio,
        videos=videos,
        files=files,
        add_session_state_to_context=add_session_state_to_context,
        tools=tools,
    )
    if system_message is not None:
        run_messages.system_message = system_message
        run_messages.messages.append(system_message)

    # 2. Add extra messages to run_messages if provided
    if team.additional_input is not None:
        messages_to_add_to_run_response: List[Message] = []
        if run_messages.extra_messages is None:
            run_messages.extra_messages = []

        for _m in team.additional_input:
            if isinstance(_m, Message):
                messages_to_add_to_run_response.append(_m)
                run_messages.messages.append(_m)
                run_messages.extra_messages.append(_m)
            elif isinstance(_m, dict):
                try:
                    _m_parsed = Message.model_validate(_m)
                    messages_to_add_to_run_response.append(_m_parsed)
                    run_messages.messages.append(_m_parsed)
                    run_messages.extra_messages.append(_m_parsed)
                except Exception as e:
                    log_warning(f"Failed to validate message: {e}")
        # Add the extra messages to the run_response
        if len(messages_to_add_to_run_response) > 0:
            log_debug(f"Adding {len(messages_to_add_to_run_response)} extra messages")
            if run_response.additional_input is None:
                run_response.additional_input = messages_to_add_to_run_response
            else:
                run_response.additional_input.extend(messages_to_add_to_run_response)

    # 3. Add history to run_messages
    if add_history_to_context:
        from copy import deepcopy

        # Only skip messages from history when system_message_role is NOT a standard conversation role.
        # Standard conversation roles ("user", "assistant", "tool") should never be filtered
        # to preserve conversation continuity.
        skip_role = team.system_message_role if team.system_message_role not in ["user", "assistant", "tool"] else None
        history = session.get_messages(
            last_n_runs=team.num_history_runs,
            limit=team.num_history_messages,
            skip_roles=[skip_role] if skip_role else None,
            team_id=team.id if team.parent_team_id is not None else None,
        )

        if len(history) > 0:
            # Create a deep copy of the history messages to avoid modifying the original messages
            history_copy = [deepcopy(msg) for msg in history]

            # Tag each message as coming from history
            for _msg in history_copy:
                _msg.from_history = True

            # Filter tool calls from history messages
            if team.max_tool_calls_from_history is not None:
                filter_tool_calls(history_copy, team.max_tool_calls_from_history)

            log_debug(f"Adding {len(history_copy)} messages from history")

            # Extend the messages with the history
            run_messages.messages += history_copy

    # 5. Add user message to run_messages (message second as per Dirk's requirement)
    # 5.1 Build user message if message is None, str or list
    user_message = await _aget_user_message(
        team,
        run_response=run_response,
        run_context=run_context,
        input_message=input_message,
        user_id=user_id,
        audio=audio,
        images=images,
        videos=videos,
        files=files,
        add_dependencies_to_context=add_dependencies_to_context,
        **kwargs,
    )
    # Add user message to run_messages
    if user_message is not None:
        run_messages.user_message = user_message
        run_messages.messages.append(user_message)

    return run_messages


def _get_user_message(
    team: "Team",
    *,
    run_response: TeamRunOutput,
    run_context: RunContext,
    input_message: Optional[Union[str, List, Dict, Message, BaseModel, List[Message]]] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    **kwargs,
):
    # Get references from the knowledge base to use in the user message
    from agno.team._utils import _convert_dependencies_to_string, _convert_documents_to_string

    references = None

    if input_message is None:
        # If we have any media, return a message with empty content
        if images is not None or audio is not None or videos is not None or files is not None:
            return Message(
                role="user",
                content="",
                images=None if not team.send_media_to_model else images,
                audio=None if not team.send_media_to_model else audio,
                videos=None if not team.send_media_to_model else videos,
                files=None if not team.send_media_to_model else files,
                **kwargs,
            )
        else:
            # If the input is None, return None
            return None

    else:
        if isinstance(input_message, list):
            input_content: Union[str, List[Any], List[Message]]
            if len(input_message) > 0 and isinstance(input_message[0], dict) and "type" in input_message[0]:
                # This is multimodal content (text + images/audio/video), preserve the structure
                input_content = input_message
            elif len(input_message) > 0 and isinstance(input_message[0], Message):
                # This is a list of Message objects, extract text content from them
                input_content = get_text_from_message(input_message)
            elif all(isinstance(item, str) for item in input_message):
                input_content = "\n".join([str(item) for item in input_message])
            else:
                input_content = str(input_message)

            return Message(
                role="user",
                content=input_content,
                images=None if not team.send_media_to_model else images,
                audio=None if not team.send_media_to_model else audio,
                videos=None if not team.send_media_to_model else videos,
                files=None if not team.send_media_to_model else files,
                **kwargs,
            )

        # If message is provided as a Message, use it directly
        elif isinstance(input_message, Message):
            return input_message
        # If message is provided as a dict, try to validate it as a Message
        elif isinstance(input_message, dict):
            try:
                if team.input_schema and is_typed_dict(team.input_schema):
                    import json

                    content = json.dumps(input_message, indent=2, ensure_ascii=False)
                    return Message(role="user", content=content)
                else:
                    return Message.model_validate(input_message)
            except Exception as e:
                log_warning(f"Failed to validate input: {e}")

        # If message is provided as a BaseModel, convert it to a Message
        elif isinstance(input_message, BaseModel):
            try:
                # Create a user message with the BaseModel content
                content = input_message.model_dump_json(indent=2, exclude_none=True)
                return Message(role="user", content=content)
            except Exception as e:
                log_warning(f"Failed to convert BaseModel to message: {e}")
        else:
            user_msg_content = input_message
            if team.add_knowledge_to_context:
                if isinstance(input_message, str):
                    user_msg_content = input_message
                elif callable(input_message):
                    user_msg_content = input_message(agent=team)
                else:
                    raise Exception("input must be a string or a callable when add_references is True")

                try:
                    retrieval_timer = Timer()
                    retrieval_timer.start()
                    docs_from_knowledge = team.get_relevant_docs_from_knowledge(
                        query=user_msg_content,
                        filters=run_context.knowledge_filters,
                        run_context=run_context,
                        **kwargs,
                    )
                    if docs_from_knowledge is not None:
                        references = MessageReferences(
                            query=user_msg_content,
                            references=docs_from_knowledge,
                            time=round(retrieval_timer.elapsed, 4),
                        )
                        # Add the references to the run_response
                        if run_response.references is None:
                            run_response.references = []
                        run_response.references.append(references)
                    retrieval_timer.stop()
                    log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")
                except Exception as e:
                    log_warning(f"Failed to get references: {e}")

            if team.resolve_in_context:
                user_msg_content = _format_message_with_state_variables(
                    team,
                    user_msg_content,
                    run_context=run_context,
                )

            # Convert to string for concatenation operations
            user_msg_content_str = get_text_from_message(user_msg_content) if user_msg_content is not None else ""

            # 4.1 Add knowledge references to user message
            if (
                team.add_knowledge_to_context
                and references is not None
                and references.references is not None
                and len(references.references) > 0
            ):
                user_msg_content_str += "\n\nUse the following references from the knowledge base if it helps:\n"
                user_msg_content_str += "<references>\n"
                user_msg_content_str += _convert_documents_to_string(team, references.references) + "\n"
                user_msg_content_str += "</references>"
            # 4.2 Add context to user message
            if add_dependencies_to_context and run_context.dependencies is not None:
                user_msg_content_str += "\n\n<additional context>\n"
                user_msg_content_str += _convert_dependencies_to_string(team, run_context.dependencies) + "\n"
                user_msg_content_str += "</additional context>"

            # Use the string version for the final content
            user_msg_content = user_msg_content_str

            # Return the user message
            return Message(
                role="user",
                content=user_msg_content,
                images=None if not team.send_media_to_model else images,
                audio=None if not team.send_media_to_model else audio,
                videos=None if not team.send_media_to_model else videos,
                files=None if not team.send_media_to_model else files,
                **kwargs,
            )


async def _aget_user_message(
    team: "Team",
    *,
    run_response: TeamRunOutput,
    run_context: RunContext,
    input_message: Optional[Union[str, List, Dict, Message, BaseModel, List[Message]]] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    **kwargs,
):
    # Get references from the knowledge base to use in the user message
    from agno.team._utils import _convert_dependencies_to_string, _convert_documents_to_string

    references = None

    if input_message is None:
        # If we have any media, return a message with empty content
        if images is not None or audio is not None or videos is not None or files is not None:
            return Message(
                role="user",
                content="",
                images=None if not team.send_media_to_model else images,
                audio=None if not team.send_media_to_model else audio,
                videos=None if not team.send_media_to_model else videos,
                files=None if not team.send_media_to_model else files,
                **kwargs,
            )
        else:
            # If the input is None, return None
            return None

    else:
        if isinstance(input_message, list):
            input_content: Union[str, List[Any], List[Message]]
            if len(input_message) > 0 and isinstance(input_message[0], dict) and "type" in input_message[0]:
                # This is multimodal content (text + images/audio/video), preserve the structure
                input_content = input_message
            elif len(input_message) > 0 and isinstance(input_message[0], Message):
                # This is a list of Message objects, extract text content from them
                input_content = get_text_from_message(input_message)
            elif all(isinstance(item, str) for item in input_message):
                input_content = "\n".join([str(item) for item in input_message])
            else:
                input_content = str(input_message)

            return Message(
                role="user",
                content=input_content,
                images=None if not team.send_media_to_model else images,
                audio=None if not team.send_media_to_model else audio,
                videos=None if not team.send_media_to_model else videos,
                files=None if not team.send_media_to_model else files,
                **kwargs,
            )

        # If message is provided as a Message, use it directly
        elif isinstance(input_message, Message):
            return input_message
        # If message is provided as a dict, try to validate it as a Message
        elif isinstance(input_message, dict):
            try:
                if team.input_schema and is_typed_dict(team.input_schema):
                    import json

                    content = json.dumps(input_message, indent=2, ensure_ascii=False)
                    return Message(role="user", content=content)
                else:
                    return Message.model_validate(input_message)
            except Exception as e:
                log_warning(f"Failed to validate input: {e}")

        # If message is provided as a BaseModel, convert it to a Message
        elif isinstance(input_message, BaseModel):
            try:
                # Create a user message with the BaseModel content
                content = input_message.model_dump_json(indent=2, exclude_none=True)
                return Message(role="user", content=content)
            except Exception as e:
                log_warning(f"Failed to convert BaseModel to message: {e}")
        else:
            user_msg_content = input_message
            if team.add_knowledge_to_context:
                if isinstance(input_message, str):
                    user_msg_content = input_message
                elif callable(input_message):
                    user_msg_content = input_message(agent=team)
                else:
                    raise Exception("input must be a string or a callable when add_references is True")

                try:
                    retrieval_timer = Timer()
                    retrieval_timer.start()
                    docs_from_knowledge = await team.aget_relevant_docs_from_knowledge(
                        query=user_msg_content,
                        filters=run_context.knowledge_filters,
                        run_context=run_context,
                        **kwargs,
                    )
                    if docs_from_knowledge is not None:
                        references = MessageReferences(
                            query=user_msg_content,
                            references=docs_from_knowledge,
                            time=round(retrieval_timer.elapsed, 4),
                        )
                        # Add the references to the run_response
                        if run_response.references is None:
                            run_response.references = []
                        run_response.references.append(references)
                    retrieval_timer.stop()
                    log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")
                except Exception as e:
                    log_warning(f"Failed to get references: {e}")

            if team.resolve_in_context:
                user_msg_content = _format_message_with_state_variables(
                    team,
                    user_msg_content,
                    run_context=run_context,
                )

            # Convert to string for concatenation operations
            user_msg_content_str = get_text_from_message(user_msg_content) if user_msg_content is not None else ""

            # 4.1 Add knowledge references to user message
            if (
                team.add_knowledge_to_context
                and references is not None
                and references.references is not None
                and len(references.references) > 0
            ):
                user_msg_content_str += "\n\nUse the following references from the knowledge base if it helps:\n"
                user_msg_content_str += "<references>\n"
                user_msg_content_str += _convert_documents_to_string(team, references.references) + "\n"
                user_msg_content_str += "</references>"
            # 4.2 Add context to user message
            if add_dependencies_to_context and run_context.dependencies is not None:
                user_msg_content_str += "\n\n<additional context>\n"
                user_msg_content_str += _convert_dependencies_to_string(team, run_context.dependencies) + "\n"
                user_msg_content_str += "</additional context>"

            # Use the string version for the final content
            user_msg_content = user_msg_content_str

            # Return the user message
            return Message(
                role="user",
                content=user_msg_content,
                images=None if not team.send_media_to_model else images,
                audio=None if not team.send_media_to_model else audio,
                videos=None if not team.send_media_to_model else videos,
                files=None if not team.send_media_to_model else files,
                **kwargs,
            )


def _get_messages_for_parser_model(
    team: "Team",
    model_response: ModelResponse,
    response_format: Optional[Union[Dict, Type[BaseModel]]],
    run_context: Optional[RunContext] = None,
) -> List[Message]:
    """Get the messages for the parser model."""
    from agno.utils.prompts import get_json_output_prompt

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    system_content = (
        team.parser_model_prompt
        if team.parser_model_prompt is not None
        else "You are tasked with creating a structured output from the provided user message."
    )

    if response_format == {"type": "json_object"} and output_schema is not None:
        system_content += f"{get_json_output_prompt(output_schema)}"  # type: ignore

    return [
        Message(role="system", content=system_content),
        Message(role="user", content=model_response.content),
    ]


def _get_messages_for_parser_model_stream(
    team: "Team",
    run_response: TeamRunOutput,
    response_format: Optional[Union[Dict, Type[BaseModel]]],
    run_context: Optional[RunContext] = None,
) -> List[Message]:
    """Get the messages for the parser model."""
    from agno.utils.prompts import get_json_output_prompt

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    system_content = (
        team.parser_model_prompt
        if team.parser_model_prompt is not None
        else "You are tasked with creating a structured output from the provided data."
    )

    if response_format == {"type": "json_object"} and output_schema is not None:
        system_content += f"{get_json_output_prompt(output_schema)}"  # type: ignore

    return [
        Message(role="system", content=system_content),
        Message(role="user", content=run_response.content),
    ]


def _get_messages_for_output_model(team: "Team", messages: List[Message]) -> List[Message]:
    """Get the messages for the output model."""
    from copy import deepcopy

    # Copy the list and messages to avoid mutating the originals
    messages = [deepcopy(m) for m in messages]

    if team.output_model_prompt is not None:
        system_message_exists = False
        for message in messages:
            if message.role == "system":
                system_message_exists = True
                message.content = team.output_model_prompt
                break
        if not system_message_exists:
            messages.insert(0, Message(role="system", content=team.output_model_prompt))

    # Remove the last assistant message from the messages list
    if messages and messages[-1].role == "assistant":
        messages.pop(-1)

    return messages


def _format_message_with_state_variables(
    team: "Team",
    message: Any,
    run_context: Optional[RunContext] = None,
) -> Any:
    """Format a message with the session state variables from run_context."""
    import re
    import string

    if not isinstance(message, str):
        return message

    # Extract values from run_context
    session_state = run_context.session_state if run_context else None
    dependencies = run_context.dependencies if run_context else None
    metadata = run_context.metadata if run_context else None
    user_id = run_context.user_id if run_context else None

    # Should already be resolved and passed from run() method
    format_variables = ChainMap(
        session_state if session_state is not None else {},
        dependencies or {},
        metadata or {},
        {"user_id": user_id} if user_id is not None else {},
    )
    converted_msg = message
    for var_name in format_variables.keys():
        # Only convert standalone {var_name} patterns, not nested ones
        pattern = r"\{" + re.escape(var_name) + r"\}"
        replacement = "${" + var_name + "}"
        converted_msg = re.sub(pattern, replacement, converted_msg)

    # Use Template to safely substitute variables
    template = string.Template(converted_msg)
    try:
        result = template.safe_substitute(format_variables)
        return result
    except Exception as e:
        log_warning(f"Template substitution failed: {e}")
        return message


def _get_json_output_prompt(
    team: "Team", output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None
) -> str:
    """Return the JSON output prompt for the Agent.

    This is added to the system prompt when the output_schema is set and structured_outputs is False.
    """

    json_output_prompt = "Provide your output as a JSON containing the following fields:"
    if output_schema is not None:
        if isinstance(output_schema, str):
            json_output_prompt += "\n<json_fields>"
            json_output_prompt += f"\n{output_schema}"
            json_output_prompt += "\n</json_fields>"
        elif isinstance(output_schema, list):
            json_output_prompt += "\n<json_fields>"
            json_output_prompt += f"\n{json.dumps(output_schema)}"
            json_output_prompt += "\n</json_fields>"
        elif isinstance(output_schema, dict):
            json_output_prompt += "\n<json_fields>"
            json_output_prompt += f"\n{json.dumps(output_schema)}"
            json_output_prompt += "\n</json_fields>"
        elif isinstance(output_schema, type) and issubclass(output_schema, BaseModel):
            json_schema = output_schema.model_json_schema()
            if json_schema is not None:
                response_model_properties = {}
                json_schema_properties = json_schema.get("properties")
                if json_schema_properties is not None:
                    for field_name, field_properties in json_schema_properties.items():
                        formatted_field_properties = {
                            prop_name: prop_value
                            for prop_name, prop_value in field_properties.items()
                            if prop_name != "title"
                        }
                        response_model_properties[field_name] = formatted_field_properties
                json_schema_defs = json_schema.get("$defs")
                if json_schema_defs is not None:
                    response_model_properties["$defs"] = {}
                    for def_name, def_properties in json_schema_defs.items():
                        def_fields = def_properties.get("properties")
                        formatted_def_properties = {}
                        if def_fields is not None:
                            for field_name, field_properties in def_fields.items():
                                formatted_field_properties = {
                                    prop_name: prop_value
                                    for prop_name, prop_value in field_properties.items()
                                    if prop_name != "title"
                                }
                                formatted_def_properties[field_name] = formatted_field_properties
                        if len(formatted_def_properties) > 0:
                            response_model_properties["$defs"][def_name] = formatted_def_properties

                if len(response_model_properties) > 0:
                    json_output_prompt += "\n<json_fields>"
                    json_output_prompt += (
                        f"\n{json.dumps([key for key in response_model_properties.keys() if key != '$defs'])}"
                    )
                    json_output_prompt += "\n</json_fields>"
                    json_output_prompt += "\n\nHere are the properties for each field:"
                    json_output_prompt += "\n<json_field_properties>"
                    json_output_prompt += f"\n{json.dumps(response_model_properties, indent=2)}"
                    json_output_prompt += "\n</json_field_properties>"
        else:
            log_warning(f"Could not build json schema for {output_schema}")
    else:
        json_output_prompt += "Provide the output as JSON."

    json_output_prompt += "\nStart your response with `{` and end it with `}`."
    json_output_prompt += "\nYour output will be passed to json.loads() to convert it to a Python object."
    json_output_prompt += "\nMake sure it only contains valid JSON."
    return json_output_prompt
