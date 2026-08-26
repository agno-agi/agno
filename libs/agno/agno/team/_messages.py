"""Prompt/message building and deep-copy helpers for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.team import Team

import json
import re
import string
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
from agno.utils.knowledge import get_user_id_kwarg
from agno.utils.log import (
    log_debug,
    log_warning,
)
from agno.utils.message import copy_history_message, filter_tool_calls, get_text_from_message, render_instructions
from agno.utils.team import (
    get_member_id,
)
from agno.utils.timer import Timer


def _input_kwarg(method: Any, input_message: Any) -> Dict[str, Any]:
    """``{"input": ...}`` only when the callee accepts it.

    ``Team.get_system_message`` is a public extension point and this is the
    bound method, so a subclass written against the pre-2.8.4 signature is what
    actually runs. Passing the new kwarg unconditionally makes every run of
    such a team fail.
    """
    import inspect

    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return {}
    if "input" in parameters or any(p.kind == p.VAR_KEYWORD for p in parameters.values()):
        return {"input": input_message}
    return {}


def _get_tool_names(member: Any, async_mode: bool = False) -> List[str]:
    """Extract tool names from a member's tools list."""
    tool_names: List[str] = []
    if member.tools is None or not isinstance(member.tools, list):
        return tool_names
    for _tool in member.tools:
        if isinstance(_tool, Toolkit):
            toolkit_functions = _tool.get_async_functions() if async_mode else _tool.get_functions()
            for _func in toolkit_functions.values():
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
    team: "Team", indent: int = 0, run_context: Optional["RunContext"] = None, async_mode: bool = False
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

        # Only a directly delegable member shows an id: an inner member's id is not a valid
        # delegation target here, and a leader shown one joins it into ids like
        # "sub-team.member" that always fail. The sub-team's own prompt still shows its
        # members' ids, because there they are at the top level.
        if isinstance(member, Team):
            if indent == 0:
                content += f'{pad}<member id="{member_id}" name="{member.name}" type="team">\n'
            else:
                content += f'{pad}<member name="{member.name}" type="team">\n'
            if member.role is not None:
                content += f"{pad}  Role: {member.role}\n"
            if member.description is not None:
                content += f"{pad}  Description: {member.description}\n"
            if member.members is not None:
                content += member.get_members_system_message_content(
                    indent=indent + 2, run_context=run_context, async_mode=async_mode
                )
            content += f"{pad}</member>\n"
        else:
            if indent == 0:
                content += f'{pad}<member id="{member_id}" name="{member.name}">\n'
            else:
                content += f'{pad}<member name="{member.name}">\n'
            if member.role is not None:
                content += f"{pad}  Role: {member.role}\n"
            if member.description is not None:
                content += f"{pad}  Description: {member.description}\n"
            if team.add_member_tools_to_context:
                tool_names = _get_tool_names(member, async_mode=async_mode)
                if tool_names:
                    content += f"{pad}  Tools: {', '.join(tool_names)}\n"
            content += f"{pad}</member>\n"

    return content


def _get_opening_prompt() -> str:
    """Capability statement for a leader that has members available.

    States the leader's job and what it has, never who it is. A persona claim here would
    compete with the description, role and instructions the user wrote — which render
    before this block, so a statement of purpose does not stand ahead of them. The
    coordinator sentence is load-bearing on small models: without it a leader consulting
    a panel of similar members stops at the first one or two.

    The delegation rule is stated as need, never as a comparison with the leader's own
    ability. Asked whether a member fits a sub-task "better than yours", a small model
    keeps every part it believes it can do itself and skips the member the request
    named for it; asked whether the member is needed, it follows the request.
    """
    return (
        "You coordinate this team to fulfill the user's request. "
        "You have a team of specialists, listed below. "
        "Delegate to members when their expertise or tools are needed; "
        "answer directly — including with your own tools — when they are not.\n"
    )


def _get_mode_instructions(team: "Team", has_sub_team: bool = False) -> str:
    """Return the mode-specific <delegation> block."""
    from agno.team.mode import TeamMode

    # Name only the member fields the roster actually renders, so the leader is never
    # asked to select on evidence it was not given.
    selector = "role, description, and tools" if team.add_member_tools_to_context else "role and description"

    content = "\n<delegation>\n"

    if team.mode == TeamMode.tasks:
        content += (
            "You work from a shared task list: you create tasks, assign each one to a member, "
            "execute them, and deliver the result.\n\n"
            f"- `create_task` sets the assignee — the member whose {selector} fit the work best. "
            "`execute_tasks_parallel` runs each task against the member it was created with, so a task "
            "created without an assignee cannot go in a batch. Titles are unique: creating a task under "
            "an existing title returns that task instead of a new one.\n"
            "- Set `depends_on` only when a task genuinely needs another task's output.\n"
            "- Run one task with `execute_task`, or a batch of independent ones with "
            "`execute_tasks_parallel`. `list_tasks` re-reads the board at any point.\n"
            "- Read every result. On a failure, retry, reassign, or change the plan — do not repeat the "
            "same call unchanged. Record work you did yourself with `update_task_status`, and anything a "
            "later task will need with `add_task_note`.\n"
            "- A task result is evidence, not your answer. When a task fails or a member returns nothing, "
            "say so plainly and name what it reported — never supply a cause or a finding the member did "
            "not state.\n"
            "- `mark_all_complete` ends the loop; the summary you pass it is bookkeeping, not the reply. "
            "Write the answer as your own message in the same turn — that message is what reaches the "
            "user. A list whose tasks have all completed also ends the loop. For a request that needs "
            "no tasks at all — a greeting, a question you can simply answer — write the answer and call "
            "`mark_all_complete` in the same turn: that finishes at once instead of after a reminder. "
            "Call it too when the goal is out of reach: a partial outcome stated plainly beats looping.\n"
        )
    elif team.mode == TeamMode.route:
        content += (
            "You work in route mode: you hand the request to exactly one member with "
            "`delegate_task_to_member`, and its reply is returned to the user as written and ends the "
            "run.\n\n"
            f"- Pick the member whose {selector} are the closest match; if none is a clear fit, pick the "
            "closest and carry the shortfall into the task.\n"
            "- Pass the request whole. Do not reinterpret, narrow, or summarize what the user asked.\n"
            "- State any requirement on the reply — format, length, structure, tone — in the task itself. "
            "Your own formatting rules and expected output are not applied to what the member returns.\n"
            "- Write no text of your own in the turn you hand over: anything you write is prepended to the "
            "member's reply, and you get no turn to review or correct what it sends.\n"
        )
    elif team.mode == TeamMode.broadcast:
        content += (
            "You work in broadcast mode: one call puts the same task to every member, then you write the "
            "answer yourself.\n\n"
            "- Call `delegate_task_to_members` exactly once. One call reaches every member; do not call it "
            "once per member.\n"
            "- Write one whole question each member can answer from its own vantage point, not a sub-task "
            "for one of them.\n"
            "- A member's output is evidence, not your answer. When a member fails, refuses, or returns "
            "nothing, say so plainly and name what it reported — never supply a cause, source, or finding "
            "the member did not state.\n"
            "- Say each finding once: where members agree that is one finding, not three; where they "
            "conflict, reconcile it and say which view you took. Integrate the strongest contributions "
            "thematically — never list the responses in sequence.\n"
        )
    else:
        # coordinate mode (default)
        content += (
            "You work in coordinate mode: you hand sub-tasks to members with "
            "`delegate_task_to_member` and write the answer yourself.\n\n"
            f"- Match each sub-task to the member whose {selector} fit it best. When sub-tasks do not "
            "depend on each other, delegate them in the same turn instead of one per turn.\n"
            "- A member's output is evidence, not your answer. When a member fails, refuses, or returns "
            "nothing, say so plainly and name what it reported — never supply a cause, source, or finding "
            "the member did not state.\n"
            "- If a response is off-target, re-delegate with clearer instructions or try a better-suited "
            "member. If it still misses, answer with what you have and say what is missing — do not work "
            "through the roster.\n"
            "- Write one answer. Resolve contradictions, add structure, and fill gaps only where you can "
            "state the basis for it. Never concatenate member outputs.\n"
        )

    # The delegate tools send the raw user input instead of the leader's task text when
    # determine_input_for_members is off. Task execution always delivers the leader's text.
    if team.mode != TeamMode.tasks and team.determine_input_for_members is False:
        content += (
            "\nMembers do not see this conversation, and each one receives the user's message verbatim "
            "rather than the text you write. Pass a short label; do not restate or rewrite the request.\n"
        )
    elif team.add_team_history_to_members or team.share_member_interactions:
        content += (
            "\nMembers see only what you pass them plus the shared context this team forwards — not the "
            "conversation itself. Carry over every name, number and earlier answer the task depends on, "
            "and say what a good result looks like.\n"
        )
    else:
        content += (
            "\nMembers do not see this conversation. Each one gets only the text you write for it, so "
            "carry over every name, number and earlier answer it needs, and say what a good result looks "
            "like.\n"
        )

    # Broadcast reaches every member with one call and takes no member id.
    if team.mode != TeamMode.broadcast:
        if has_sub_team:
            # A nested roster invites joined ids like "sub-team.member"; the lookup is exact,
            # so every such call fails and costs a round trip before the leader recovers.
            content += (
                "Member ids are the ids shown in the roster above, used exactly as written — never joined "
                "or prefixed. Delegate to a sub-team by the sub-team's own id; its leader hands work to "
                "the members inside it.\n"
            )
        else:
            content += "Member ids are the ids shown in the roster above, used exactly as written.\n"

    content += "</delegation>\n"
    return content


def _build_team_context(
    team: "Team",
    run_context: Optional["RunContext"] = None,
    async_mode: bool = False,
) -> str:
    """Build the <team> block: capability statement, roster, and delegation instructions.

    One wrapping element so the framework's mechanics read as subordinate to whatever
    identity the user wrote, rather than as three more top-level siblings alongside it.

    Shared between sync and async system-message builders.
    """
    from agno.team.mode import TeamMode
    from agno.utils.callables import get_resolved_members

    content = ""
    resolved_members = get_resolved_members(team, run_context)
    if resolved_members is not None and len(resolved_members) > 0:
        content += "<team>\n"
        content += _get_opening_prompt()
        content += "\n<team_members>\n"
        content += team.get_members_system_message_content(run_context=run_context, async_mode=async_mode)
        content += "</team_members>\n"
        # Outside the roster: <team_members> holds member records, not prose.
        # Tasks mode takes the task-tool branch, which never attaches this one.
        if team.get_member_information_tool and team.mode != TeamMode.tasks:
            content += "Call `get_member_information` at any time to re-read this list.\n"
        from agno.team.team import Team

        has_sub_team = any(isinstance(member, Team) for member in resolved_members)
        content += _get_mode_instructions(team, has_sub_team=has_sub_team)
        content += "</team>\n\n"
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
        rendered = render_instructions(instructions)
        if team.use_instruction_tags:
            content += f"<instructions>\n{rendered}\n</instructions>\n\n"
        else:
            content += rendered + "\n\n"
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

    # Add skills to the system prompt
    if team.skills is not None:
        skills_snippet = team.skills.get_system_prompt_snippet()
        if skills_snippet:
            content += f"\n{skills_snippet}\n"

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
    input: Optional[Any] = None,
) -> Optional[Message]:
    """Get the system message for the team.

    1. If the system_message is provided, use that.
    2. Otherwise build and return the default system message for the Team.
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

    # 2. Build and return the default system message for the Team.
    # 2.1 Build the list of instructions for the system message
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
            except Exception as e:
                log_warning(f"Invalid timezone identifier: {str(e)}")

        time = datetime.now(tz) if tz else datetime.now()

        if team.datetime_format:
            formatted_time = time.strftime(team.datetime_format)
        else:
            formatted_time = str(time)

        additional_information.append(f"The current time is {formatted_time}.")

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

    # 1.3.5 Tell the model what a result envelope is and how to read the rest
    if team._result_store is not None:
        from agno.offload.tools import OFFLOAD_INSTRUCTION

        additional_information.append(OFFLOAD_INSTRUCTION)

    # 2 Build the default system message for the Team.
    system_message_content: str = ""

    # 2.1 Identity sections first: description, role, instructions.
    # The user's identity opens the prompt, as it does for an Agent. Framework
    # mechanics that follow read as instructions to that identity rather than as a
    # competing one.
    system_message_content += _build_identity_sections(team, instructions)

    # 2.2 Team members + delegation instructions
    system_message_content += _build_team_context(team, run_context=run_context)

    # 2.3 Learning context: guidance + data, concatenated so the automatic door
    # renders exactly what the manual door's instructions() + build_context() would
    if team._learning is not None and team.add_learnings_to_context:
        from agno.agent._messages import _learning_message_text

        learning_guidance = team._learning._framework_instructions()
        learning_context = team._learning.build_context(
            user_id=user_id,
            session_id=session.session_id if session else None,
            team_id=team.id,
            message=_learning_message_text(input),
            run_context=run_context,
            metadata=run_context.metadata if run_context else None,
            dependencies=run_context.dependencies if run_context else None,
            session_state=run_context.session_state if run_context else None,
        )
        learning_block = "\n".join(part for part in (learning_guidance, learning_context) if part)
        if learning_block:
            system_message_content += learning_block + "\n"

    # 2.4 Knowledge base instructions
    if team.knowledge is not None and team.search_knowledge and team.add_search_knowledge_instructions:
        build_context_fn = getattr(team.knowledge, "build_context", None)
        if callable(build_context_fn):
            # Filter keys rendered into the prompt come from stored content, so scope them like retrieval
            build_context_kwargs: Dict[str, Any] = {"enable_agentic_filters": team.enable_agentic_knowledge_filters}
            build_context_kwargs.update(
                get_user_id_kwarg(build_context_fn, run_context.user_id if run_context else team.user_id)
            )
            knowledge_context = build_context_fn(**build_context_kwargs)
            if knowledge_context:
                system_message_content += knowledge_context + "\n"

    # 2.5 Memories
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
                "Note: this information is from previous interactions and may be outdated. "
                "You should ALWAYS prefer information from this conversation over the past memories.\n\n"
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
    input: Optional[Any] = None,
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

    # 2. Build and return the default system message for the Team.
    # 2.1 Build the list of instructions for the system message
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
            except Exception as e:
                log_warning(f"Invalid timezone identifier: {str(e)}")

        time = datetime.now(tz) if tz else datetime.now()

        if team.datetime_format:
            formatted_time = time.strftime(team.datetime_format)
        else:
            formatted_time = str(time)

        additional_information.append(f"The current time is {formatted_time}.")

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

    # 1.3.5 Tell the model what a result envelope is and how to read the rest
    if team._result_store is not None:
        from agno.offload.tools import OFFLOAD_INSTRUCTION

        additional_information.append(OFFLOAD_INSTRUCTION)

    # 2 Build the default system message for the Team.
    system_message_content: str = ""

    # 2.1 Identity sections first (see the sync twin)
    system_message_content += _build_identity_sections(team, instructions)

    # 2.2 Team members + delegation instructions
    system_message_content += _build_team_context(team, run_context=run_context, async_mode=True)

    # 2.3 Learning context (see the sync twin)
    if team._learning is not None and team.add_learnings_to_context:
        from agno.agent._messages import _learning_message_text

        learning_guidance = team._learning._framework_instructions()
        learning_context = await team._learning.abuild_context(
            user_id=user_id,
            session_id=session.session_id if session else None,
            team_id=team.id,
            message=_learning_message_text(input),
            run_context=run_context,
            metadata=run_context.metadata if run_context else None,
            dependencies=run_context.dependencies if run_context else None,
            session_state=run_context.session_state if run_context else None,
        )
        learning_block = "\n".join(part for part in (learning_guidance, learning_context) if part)
        if learning_block:
            system_message_content += learning_block + "\n"

    # 2.4 Knowledge base instructions
    if team.knowledge is not None and team.search_knowledge and team.add_search_knowledge_instructions:
        # Prefer async version if available for async databases
        abuild_context_fn = getattr(team.knowledge, "abuild_context", None)
        build_context_fn = getattr(team.knowledge, "build_context", None)
        scope_uid = run_context.user_id if run_context else team.user_id
        if callable(abuild_context_fn):
            abuild_context_kwargs: Dict[str, Any] = {"enable_agentic_filters": team.enable_agentic_knowledge_filters}
            abuild_context_kwargs.update(get_user_id_kwarg(abuild_context_fn, scope_uid))
            knowledge_context = await abuild_context_fn(**abuild_context_kwargs)
            if knowledge_context:
                system_message_content += knowledge_context + "\n"
        elif callable(build_context_fn):
            build_context_kwargs: Dict[str, Any] = {"enable_agentic_filters": team.enable_agentic_knowledge_filters}
            build_context_kwargs.update(get_user_id_kwarg(build_context_fn, scope_uid))
            knowledge_context = build_context_fn(**build_context_kwargs)
            if knowledge_context:
                system_message_content += knowledge_context + "\n"

    # 2.5 Memories
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
                "Note: this information is from previous interactions and may be outdated. "
                "You should ALWAYS prefer information from this conversation over the past memories.\n\n"
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
        **_input_kwarg(team.get_system_message, input_message),
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
                    log_warning(f"Failed to validate message: {str(e)}")
        # Add the extra messages to the run_response
        if len(messages_to_add_to_run_response) > 0:
            log_debug(f"Adding {len(messages_to_add_to_run_response)} extra messages")
            if run_response.additional_input is None:
                run_response.additional_input = messages_to_add_to_run_response
            else:
                run_response.additional_input.extend(messages_to_add_to_run_response)

    # 3. Add history to run_messages
    if add_history_to_context:
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
            history_copy = [copy_history_message(msg) for msg in history]

            # Refresh pre-signed URLs for media loaded from history
            if team.media_storage is not None:
                from agno.utils.media_offload import refresh_messages_media

                refresh_messages_media(history_copy, team.media_storage)

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

    # Set messages on run_context so tool hooks can access the current message history
    run_context.messages = run_messages.messages

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
        **_input_kwarg(team.aget_system_message, input_message),
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
                    log_warning(f"Failed to validate message: {str(e)}")
        # Add the extra messages to the run_response
        if len(messages_to_add_to_run_response) > 0:
            log_debug(f"Adding {len(messages_to_add_to_run_response)} extra messages")
            if run_response.additional_input is None:
                run_response.additional_input = messages_to_add_to_run_response
            else:
                run_response.additional_input.extend(messages_to_add_to_run_response)

    # 3. Add history to run_messages
    if add_history_to_context:
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
            history_copy = [copy_history_message(msg) for msg in history]

            # Refresh pre-signed URLs for media loaded from history
            if team.media_storage is not None:
                from agno.utils.media_offload import arefresh_messages_media

                await arefresh_messages_media(history_copy, team.media_storage)

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

    # Set messages on run_context so tool hooks can access the current message history
    run_context.messages = run_messages.messages

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
                log_warning(f"Failed to validate input: {str(e)}")

        # If message is provided as a BaseModel, convert it to a Message
        elif isinstance(input_message, BaseModel):
            try:
                # Create a user message with the BaseModel content
                content = input_message.model_dump_json(indent=2, exclude_none=True)
                return Message(role="user", content=content)
            except Exception as e:
                log_warning(f"Failed to convert BaseModel to message: {str(e)}")
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
                    log_warning(f"Failed to get references: {str(e)}")

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
                log_warning(f"Failed to validate input: {str(e)}")

        # If message is provided as a BaseModel, convert it to a Message
        elif isinstance(input_message, BaseModel):
            try:
                # Create a user message with the BaseModel content
                content = input_message.model_dump_json(indent=2, exclude_none=True)
                return Message(role="user", content=content)
            except Exception as e:
                log_warning(f"Failed to convert BaseModel to message: {str(e)}")
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
                    log_warning(f"Failed to get references: {str(e)}")

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
    if not isinstance(message, str):
        return message

    # A message without "{" cannot contain a {var} placeholder, and without "$"
    # Template.safe_substitute is an identity transform - skip the regex and
    # template machinery entirely for the common plain-text case.
    if "{" not in message and "$" not in message:
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
        log_warning(f"Template substitution failed: {str(e)}")
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
            json_output_prompt += f"\n{json.dumps(output_schema, ensure_ascii=False)}"
            json_output_prompt += "\n</json_fields>"
        elif isinstance(output_schema, dict):
            json_output_prompt += "\n<json_fields>"
            json_output_prompt += f"\n{json.dumps(output_schema, ensure_ascii=False)}"
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
                    json_output_prompt += f"\n{json.dumps([key for key in response_model_properties.keys() if key != '$defs'], ensure_ascii=False)}"
                    json_output_prompt += "\n</json_fields>"
                    json_output_prompt += "\n\nHere are the properties for each field:"
                    json_output_prompt += "\n<json_field_properties>"
                    json_output_prompt += f"\n{json.dumps(response_model_properties, indent=2, ensure_ascii=False)}"
                    json_output_prompt += "\n</json_field_properties>"
        else:
            log_warning(f"Could not build json schema for {output_schema}")
    else:
        json_output_prompt += "Provide the output as JSON."

    json_output_prompt += "\nStart your response with `{` and end it with `}`."
    json_output_prompt += "\nYour output will be passed to json.loads() to convert it to a Python object."
    json_output_prompt += "\nMake sure it only contains valid JSON."
    return json_output_prompt
