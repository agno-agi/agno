"""Prompt/message building and deep-copy helpers for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.team import Team

import json
from collections import ChainMap
from copy import copy
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
from agno.team.trait.base import TeamTraitBase
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
    log_error,
    log_warning,
)
from agno.utils.message import filter_tool_calls, get_text_from_message
from agno.utils.team import (
    get_member_id,
)
from agno.utils.timer import Timer


def _team_type() -> type["Team"]:
    from agno.team.team import Team

    return Team


class TeamMessagesTrait(TeamTraitBase):
    def get_members_system_message_content(self, indent: int = 0) -> str:
        system_message_content = ""
        for idx, member in enumerate(self.members):
            url_safe_member_id = get_member_id(member)

            if isinstance(member, _team_type()):
                system_message_content += f"{indent * ' '} - Team: {member.name}\n"
                system_message_content += f"{indent * ' '} - ID: {url_safe_member_id}\n"
                if member.members is not None:
                    system_message_content += member.get_members_system_message_content(indent=indent + 2)
            else:
                system_message_content += f"{indent * ' '} - Agent {idx + 1}:\n"
                if url_safe_member_id is not None:
                    system_message_content += f"{indent * ' '}   - ID: {url_safe_member_id}\n"
                if member.name is not None:
                    system_message_content += f"{indent * ' '}   - Name: {member.name}\n"
                if member.role is not None:
                    system_message_content += f"{indent * ' '}   - Role: {member.role}\n"
                if member.tools is not None and member.tools != [] and self.add_member_tools_to_context:
                    system_message_content += f"{indent * ' '}   - Member tools:\n"
                    for _tool in member.tools:
                        if isinstance(_tool, Toolkit):
                            for _func in _tool.functions.values():
                                if _func.entrypoint:
                                    system_message_content += f"{indent * ' '}    - {_func.name}\n"
                        elif isinstance(_tool, Function) and _tool.entrypoint:
                            system_message_content += f"{indent * ' '}    - {_tool.name}\n"
                        elif callable(_tool):
                            system_message_content += f"{indent * ' '}    - {_tool.__name__}\n"
                        elif isinstance(_tool, dict) and "name" in _tool and _tool.get("name") is not None:
                            system_message_content += f"{indent * ' '}    - {_tool['name']}\n"
                        else:
                            system_message_content += f"{indent * ' '}    - {str(_tool)}\n"

        return system_message_content

    def get_system_message(
        self,
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
        session_state = run_context.session_state if run_context else None
        user_id = run_context.user_id if run_context else None

        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        # 1. If the system_message is provided, use that.
        if self.system_message is not None:
            if isinstance(self.system_message, Message):
                return self.system_message

            sys_message_content: str = ""
            if isinstance(self.system_message, str):
                sys_message_content = self.system_message
            elif callable(self.system_message):
                sys_message_content = execute_system_message(
                    system_message=self.system_message,
                    agent=cast(Any, self),
                    team=cast(Any, self),
                    session_state=session_state,
                    run_context=run_context,
                )
                if not isinstance(sys_message_content, str):
                    raise Exception("system_message must return a string")

            # Format the system message with the session state variables
            if self.resolve_in_context:
                sys_message_content = self._format_message_with_state_variables(
                    sys_message_content,
                    run_context=run_context,
                )

            # type: ignore
            return Message(role=self.system_message_role, content=sys_message_content)

        # 1. Build and return the default system message for the Team.
        # 1.1 Build the list of instructions for the system message
        self.model = cast(Model, self.model)
        instructions: List[str] = []
        if self.instructions is not None:
            _instructions = self.instructions
            if callable(self.instructions):
                _instructions = execute_instructions(
                    instructions=self.instructions,
                    agent=cast(Any, self),
                    team=cast(Any, self),
                    session_state=session_state,
                    run_context=run_context,
                )

            if isinstance(_instructions, str):
                instructions.append(_instructions)
            elif isinstance(_instructions, list):
                instructions.extend(_instructions)

        # 1.2 Add instructions from the Model
        _model_instructions = self.model.get_instructions_for_model(tools)
        if _model_instructions is not None:
            instructions.extend(_model_instructions)

        # 1.3 Build a list of additional information for the system message
        additional_information: List[str] = []
        # 1.3.1 Add instructions for using markdown
        if self.markdown and output_schema is None:
            additional_information.append("Use markdown to format your answers.")
        # 1.3.2 Add the current datetime
        if self.add_datetime_to_context:
            from datetime import datetime

            tz = None

            if self.timezone_identifier:
                try:
                    from zoneinfo import ZoneInfo

                    tz = ZoneInfo(self.timezone_identifier)
                except Exception:
                    log_warning("Invalid timezone identifier")

            time = datetime.now(tz) if tz else datetime.now()

            additional_information.append(f"The current time is {time}.")

        # 1.3.3 Add the current location
        if self.add_location_to_context:
            from agno.utils.location import get_location

            location = get_location()
            if location:
                location_str = ", ".join(
                    filter(None, [location.get("city"), location.get("region"), location.get("country")])
                )
                if location_str:
                    additional_information.append(f"Your approximate location is: {location_str}.")

        # 1.3.4 Add team name if provided
        if self.name is not None and self.add_name_to_context:
            additional_information.append(f"Your name is: {self.name}.")

        # 2 Build the default system message for the Agent.
        system_message_content: str = ""
        if self.members is not None and len(self.members) > 0:
            system_message_content += "You are the leader of a team and sub-teams of AI Agents.\n"
            system_message_content += "Your task is to coordinate the team to complete the user's request.\n"

            system_message_content += "\nHere are the members in your team:\n"
            system_message_content += "<team_members>\n"
            system_message_content += self.get_members_system_message_content()
            if self.get_member_information_tool:
                system_message_content += "If you need to get information about your team members, you can use the `get_member_information` tool at any time.\n"
            system_message_content += "</team_members>\n"

            system_message_content += "\n<how_to_respond>\n"

            if self.delegate_to_all_members:
                system_message_content += (
                    "- You can either respond directly or use the `delegate_task_to_members` tool to delegate a task to all members in your team to get a collaborative response.\n"
                    "- To delegate a task to all members in your team, call `delegate_task_to_members` ONLY once. This will delegate a task to all members in your team.\n"
                    "- Analyze the responses from all members and evaluate whether the task has been completed.\n"
                    "- If you feel the task has been completed, you can stop and respond to the user.\n"
                )
            else:
                system_message_content += (
                    "- Your role is to delegate tasks to members in your team with the highest likelihood of completing the user's request.\n"
                    "- Carefully analyze the tools available to the members and their roles before delegating tasks.\n"
                    "- You cannot use a member tool directly. You can only delegate tasks to members.\n"
                    "- When you delegate a task to another member, make sure to include:\n"
                    "  - member_id (str): The ID of the member to delegate the task to. Use only the ID of the member, not the ID of the team followed by the ID of the member.\n"
                    "  - task (str): A clear description of the task. Determine the best way to describe the task to the member.\n"
                    "- You can delegate tasks to multiple members at once.\n"
                    "- You must always analyze the responses from members before responding to the user.\n"
                    "- After analyzing the responses from the members, if you feel the task has been completed, you can stop and respond to the user.\n"
                    "- If you are NOT satisfied with the responses from the members, you should re-assign the task to a different member.\n"
                    "- For simple greetings, thanks, or questions about the team itself, you should respond directly.\n"
                    "- For all work requests, tasks, or questions requiring expertise, route to appropriate team members.\n"
                )
            system_message_content += "</how_to_respond>\n\n"

        # Attached media
        if audio is not None or images is not None or videos is not None or files is not None:
            system_message_content += "<attached_media>\n"
            system_message_content += "You have the following media attached to your message:\n"
            if audio is not None and len(audio) > 0:
                system_message_content += " - Audio\n"
            if images is not None and len(images) > 0:
                system_message_content += " - Images\n"
            if videos is not None and len(videos) > 0:
                system_message_content += " - Videos\n"
            if files is not None and len(files) > 0:
                system_message_content += " - Files\n"
            system_message_content += "</attached_media>\n\n"

        # Then add memories to the system prompt
        if self.add_memories_to_context:
            _memory_manager_not_set = False
            if not user_id:
                user_id = "default"
            if self.memory_manager is None:
                self._set_memory_manager()
                _memory_manager_not_set = True
            user_memories = self.memory_manager.get_user_memories(user_id=user_id)  # type: ignore
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
                self.memory_manager = None

            if self.enable_agentic_memory:
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

        # Then add a summary of the interaction to the system prompt
        if self.add_session_summary_to_context and session.summary is not None:
            system_message_content += "Here is a brief summary of your previous interactions:\n\n"
            system_message_content += "<summary_of_previous_interactions>\n"
            system_message_content += session.summary.summary
            system_message_content += "\n</summary_of_previous_interactions>\n\n"
            system_message_content += (
                "Note: this information is from previous interactions and may be outdated. "
                "You should ALWAYS prefer information from this conversation over the past summary.\n\n"
            )

        # Add search_knowledge instructions to the system prompt
        if self.knowledge is not None and self.search_knowledge and self.add_search_knowledge_instructions:
            build_context_fn = getattr(self.knowledge, "build_context", None)
            if callable(build_context_fn):
                knowledge_context = build_context_fn(
                    enable_agentic_filters=self.enable_agentic_knowledge_filters,
                )
                if knowledge_context:
                    system_message_content += knowledge_context + "\n"

        if self.description is not None:
            system_message_content += f"<description>\n{self.description}\n</description>\n\n"

        if self.role is not None:
            system_message_content += f"\n<your_role>\n{self.role}\n</your_role>\n\n"

        # 3.3.5 Then add instructions for the Team
        if len(instructions) > 0:
            if self.use_instruction_tags:
                system_message_content += "<instructions>"
                if len(instructions) > 1:
                    for _upi in instructions:
                        system_message_content += f"\n- {_upi}"
                else:
                    system_message_content += "\n" + instructions[0]
                system_message_content += "\n</instructions>\n\n"
            else:
                if len(instructions) > 1:
                    for _upi in instructions:
                        system_message_content += f"- {_upi}\n"
                else:
                    system_message_content += instructions[0] + "\n\n"
        # 3.3.6 Add additional information
        if len(additional_information) > 0:
            system_message_content += "<additional_information>"
            for _ai in additional_information:
                system_message_content += f"\n- {_ai}"
            system_message_content += "\n</additional_information>\n\n"
        # 3.3.7 Then add instructions for the tools
        if self._tool_instructions is not None:
            for _ti in self._tool_instructions:
                system_message_content += f"{_ti}\n"

        # Format the system message with the session state variables
        if self.resolve_in_context:
            system_message_content = self._format_message_with_state_variables(
                system_message_content,
                run_context=run_context,
            )

        system_message_from_model = self.model.get_system_message_for_model(tools)
        if system_message_from_model is not None:
            system_message_content += system_message_from_model

        if self.expected_output is not None:
            system_message_content += f"<expected_output>\n{self.expected_output.strip()}\n</expected_output>\n\n"

        if self.additional_context is not None:
            system_message_content += (
                f"<additional_context>\n{self.additional_context.strip()}\n</additional_context>\n\n"
            )

        if add_session_state_to_context and session_state is not None:
            system_message_content += self._get_formatted_session_state_for_system_message(session_state)

        # Add the JSON output prompt if output_schema is provided and the model does not support native structured outputs
        # or JSON schema outputs, or if use_json_mode is True
        if (
            output_schema is not None
            and self.parser_model is None
            and self.model
            and not (
                (self.model.supports_native_structured_outputs or self.model.supports_json_schema_outputs)
                and not self.use_json_mode
            )
        ):
            system_message_content += f"{self._get_json_output_prompt(output_schema)}"

        return Message(role=self.system_message_role, content=system_message_content.strip())

    async def aget_system_message(
        self,
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
        session_state = run_context.session_state if run_context else None
        user_id = run_context.user_id if run_context else None

        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        # 1. If the system_message is provided, use that.
        if self.system_message is not None:
            if isinstance(self.system_message, Message):
                return self.system_message

            sys_message_content: str = ""
            if isinstance(self.system_message, str):
                sys_message_content = self.system_message
            elif callable(self.system_message):
                sys_message_content = await aexecute_system_message(
                    system_message=self.system_message,
                    agent=cast(Any, self),
                    team=cast(Any, self),
                    session_state=session_state,
                    run_context=run_context,
                )
                if not isinstance(sys_message_content, str):
                    raise Exception("system_message must return a string")

            # Format the system message with the session state variables
            if self.resolve_in_context:
                sys_message_content = self._format_message_with_state_variables(
                    sys_message_content,
                    run_context=run_context,
                )

            # type: ignore
            return Message(role=self.system_message_role, content=sys_message_content)

        # 1. Build and return the default system message for the Team.
        # 1.1 Build the list of instructions for the system message
        self.model = cast(Model, self.model)
        instructions: List[str] = []
        if self.instructions is not None:
            _instructions = self.instructions
            if callable(self.instructions):
                _instructions = await aexecute_instructions(
                    instructions=self.instructions,
                    agent=cast(Any, self),
                    team=cast(Any, self),
                    session_state=session_state,
                    run_context=run_context,
                )

            if isinstance(_instructions, str):
                instructions.append(_instructions)
            elif isinstance(_instructions, list):
                instructions.extend(_instructions)

        # 1.2 Add instructions from the Model
        _model_instructions = self.model.get_instructions_for_model(tools)
        if _model_instructions is not None:
            instructions.extend(_model_instructions)

        # 1.3 Build a list of additional information for the system message
        additional_information: List[str] = []
        # 1.3.1 Add instructions for using markdown
        if self.markdown and output_schema is None:
            additional_information.append("Use markdown to format your answers.")
        # 1.3.2 Add the current datetime
        if self.add_datetime_to_context:
            from datetime import datetime

            tz = None

            if self.timezone_identifier:
                try:
                    from zoneinfo import ZoneInfo

                    tz = ZoneInfo(self.timezone_identifier)
                except Exception:
                    log_warning("Invalid timezone identifier")

            time = datetime.now(tz) if tz else datetime.now()

            additional_information.append(f"The current time is {time}.")

        # 1.3.3 Add the current location
        if self.add_location_to_context:
            from agno.utils.location import get_location

            location = get_location()
            if location:
                location_str = ", ".join(
                    filter(None, [location.get("city"), location.get("region"), location.get("country")])
                )
                if location_str:
                    additional_information.append(f"Your approximate location is: {location_str}.")

        # 1.3.4 Add team name if provided
        if self.name is not None and self.add_name_to_context:
            additional_information.append(f"Your name is: {self.name}.")

        # 2 Build the default system message for the Agent.
        system_message_content: str = ""
        system_message_content += "You are the leader of a team and sub-teams of AI Agents.\n"
        system_message_content += "Your task is to coordinate the team to complete the user's request.\n"

        system_message_content += "\nHere are the members in your team:\n"
        system_message_content += "<team_members>\n"
        system_message_content += self.get_members_system_message_content()
        if self.get_member_information_tool:
            system_message_content += "If you need to get information about your team members, you can use the `get_member_information` tool at any time.\n"
        system_message_content += "</team_members>\n"

        system_message_content += "\n<how_to_respond>\n"

        if self.delegate_to_all_members:
            system_message_content += (
                "- Your role is to forward tasks to members in your team with the highest likelihood of completing the user's request.\n"
                "- You can either respond directly or use the `delegate_task_to_members` tool to delegate a task to all members in your team to get a collaborative response.\n"
                "- To delegate a task to all members in your team, call `delegate_task_to_members` ONLY once. This will delegate a task to all members in your team.\n"
                "- Analyze the responses from all members and evaluate whether the task has been completed.\n"
                "- If you feel the task has been completed, you can stop and respond to the user.\n"
            )
        else:
            system_message_content += (
                "- Your role is to delegate tasks to members in your team with the highest likelihood of completing the user's request.\n"
                "- Carefully analyze the tools available to the members and their roles before delegating tasks.\n"
                "- You cannot use a member tool directly. You can only delegate tasks to members.\n"
                "- When you delegate a task to another member, make sure to include:\n"
                "  - member_id (str): The ID of the member to delegate the task to. Use only the ID of the member, not the ID of the team followed by the ID of the member.\n"
                "  - task (str): A clear description of the task.\n"
                "- You can delegate tasks to multiple members at once.\n"
                "- You must always analyze the responses from members before responding to the user.\n"
                "- After analyzing the responses from the members, if you feel the task has been completed, you can stop and respond to the user.\n"
                "- If you are not satisfied with the responses from the members, you should re-assign the task.\n"
                "- For simple greetings, thanks, or questions about the team itself, you should respond directly.\n"
                "- For all work requests, tasks, or questions requiring expertise, route to appropriate team members.\n"
            )
        system_message_content += "</how_to_respond>\n\n"

        # Attached media
        if audio is not None or images is not None or videos is not None or files is not None:
            system_message_content += "<attached_media>\n"
            system_message_content += "You have the following media attached to your message:\n"
            if audio is not None and len(audio) > 0:
                system_message_content += " - Audio\n"
            if images is not None and len(images) > 0:
                system_message_content += " - Images\n"
            if videos is not None and len(videos) > 0:
                system_message_content += " - Videos\n"
            if files is not None and len(files) > 0:
                system_message_content += " - Files\n"
            system_message_content += "</attached_media>\n\n"

        # Then add memories to the system prompt
        if self.add_memories_to_context:
            _memory_manager_not_set = False
            if not user_id:
                user_id = "default"
            if self.memory_manager is None:
                self._set_memory_manager()
                _memory_manager_not_set = True

            if self._has_async_db():
                user_memories = await self.memory_manager.aget_user_memories(user_id=user_id)  # type: ignore
            else:
                user_memories = self.memory_manager.get_user_memories(user_id=user_id)  # type: ignore

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
                self.memory_manager = None

            if self.enable_agentic_memory:
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

        # Then add a summary of the interaction to the system prompt
        if self.add_session_summary_to_context and session.summary is not None:
            system_message_content += "Here is a brief summary of your previous interactions:\n\n"
            system_message_content += "<summary_of_previous_interactions>\n"
            system_message_content += session.summary.summary
            system_message_content += "\n</summary_of_previous_interactions>\n\n"
            system_message_content += (
                "Note: this information is from previous interactions and may be outdated. "
                "You should ALWAYS prefer information from this conversation over the past summary.\n\n"
            )

        # Add search_knowledge instructions to the system prompt
        if self.knowledge is not None and self.search_knowledge and self.add_search_knowledge_instructions:
            build_context_fn = getattr(self.knowledge, "build_context", None)
            if callable(build_context_fn):
                knowledge_context = build_context_fn(
                    enable_agentic_filters=self.enable_agentic_knowledge_filters,
                )
                if knowledge_context:
                    system_message_content += knowledge_context + "\n"

        if self.description is not None:
            system_message_content += f"<description>\n{self.description}\n</description>\n\n"

        if self.role is not None:
            system_message_content += f"\n<your_role>\n{self.role}\n</your_role>\n\n"

        # 3.3.5 Then add instructions for the Team
        if len(instructions) > 0:
            if self.use_instruction_tags:
                system_message_content += "<instructions>"
                if len(instructions) > 1:
                    for _upi in instructions:
                        system_message_content += f"\n- {_upi}"
                else:
                    system_message_content += "\n" + instructions[0]
                system_message_content += "\n</instructions>\n\n"
            else:
                if len(instructions) > 1:
                    for _upi in instructions:
                        system_message_content += f"- {_upi}\n"
                else:
                    system_message_content += instructions[0] + "\n\n"
        # 3.3.6 Add additional information
        if len(additional_information) > 0:
            system_message_content += "<additional_information>"
            for _ai in additional_information:
                system_message_content += f"\n- {_ai}"
            system_message_content += "\n</additional_information>\n\n"
        # 3.3.7 Then add instructions for the tools
        if self._tool_instructions is not None:
            for _ti in self._tool_instructions:
                system_message_content += f"{_ti}\n"

        # Format the system message with the session state variables
        if self.resolve_in_context:
            system_message_content = self._format_message_with_state_variables(
                system_message_content,
                run_context=run_context,
            )

        system_message_from_model = self.model.get_system_message_for_model(tools)
        if system_message_from_model is not None:
            system_message_content += system_message_from_model

        if self.expected_output is not None:
            system_message_content += f"<expected_output>\n{self.expected_output.strip()}\n</expected_output>\n\n"

        if self.additional_context is not None:
            system_message_content += (
                f"<additional_context>\n{self.additional_context.strip()}\n</additional_context>\n\n"
            )

        if add_session_state_to_context and session_state is not None:
            system_message_content += self._get_formatted_session_state_for_system_message(session_state)

        # Add the JSON output prompt if output_schema is provided and the model does not support native structured outputs
        # or JSON schema outputs, or if use_json_mode is True
        if (
            output_schema is not None
            and self.parser_model is None
            and self.model
            and not (
                (self.model.supports_native_structured_outputs or self.model.supports_json_schema_outputs)
                and not self.use_json_mode
            )
        ):
            system_message_content += f"{self._get_json_output_prompt(output_schema)}"

        return Message(role=self.system_message_role, content=system_message_content.strip())

    def _get_formatted_session_state_for_system_message(self, session_state: Dict[str, Any]) -> str:
        return f"\n<session_state>\n{session_state}\n</session_state>\n\n"

    def _get_run_messages(
        self,
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
        system_message = self.get_system_message(
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
        if self.additional_input is not None:
            messages_to_add_to_run_response: List[Message] = []
            if run_messages.extra_messages is None:
                run_messages.extra_messages = []

            for _m in self.additional_input:
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
            skip_role = (
                self.system_message_role if self.system_message_role not in ["user", "assistant", "tool"] else None
            )

            history = session.get_messages(
                last_n_runs=self.num_history_runs,
                limit=self.num_history_messages,
                skip_roles=[skip_role] if skip_role else None,
                team_id=self.id if self.parent_team_id is not None else None,
            )

            if len(history) > 0:
                # Create a deep copy of the history messages to avoid modifying the original messages
                history_copy = [deepcopy(msg) for msg in history]

                # Tag each message as coming from history
                for _msg in history_copy:
                    _msg.from_history = True

                # Filter tool calls from history messages
                if self.max_tool_calls_from_history is not None:
                    filter_tool_calls(history_copy, self.max_tool_calls_from_history)

                log_debug(f"Adding {len(history_copy)} messages from history")

                # Extend the messages with the history
                run_messages.messages += history_copy

        # 5. Add user message to run_messages (message second as per Dirk's requirement)
        # 5.1 Build user message if message is None, str or list
        user_message = self._get_user_message(
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
        self,
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
        system_message = await self.aget_system_message(
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
        if self.additional_input is not None:
            messages_to_add_to_run_response: List[Message] = []
            if run_messages.extra_messages is None:
                run_messages.extra_messages = []

            for _m in self.additional_input:
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
            skip_role = (
                self.system_message_role if self.system_message_role not in ["user", "assistant", "tool"] else None
            )
            history = session.get_messages(
                last_n_runs=self.num_history_runs,
                limit=self.num_history_messages,
                skip_roles=[skip_role] if skip_role else None,
                team_id=self.id,
            )

            if len(history) > 0:
                # Create a deep copy of the history messages to avoid modifying the original messages
                history_copy = [deepcopy(msg) for msg in history]

                # Tag each message as coming from history
                for _msg in history_copy:
                    _msg.from_history = True

                # Filter tool calls from history messages
                if self.max_tool_calls_from_history is not None:
                    filter_tool_calls(history_copy, self.max_tool_calls_from_history)

                log_debug(f"Adding {len(history_copy)} messages from history")

                # Extend the messages with the history
                run_messages.messages += history_copy

        # 5. Add user message to run_messages (message second as per Dirk's requirement)
        # 5.1 Build user message if message is None, str or list
        user_message = await self._aget_user_message(
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
        self,
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
        references = None

        if input_message is None:
            # If we have any media, return a message with empty content
            if images is not None or audio is not None or videos is not None or files is not None:
                return Message(
                    role="user",
                    content="",
                    images=None if not self.send_media_to_model else images,
                    audio=None if not self.send_media_to_model else audio,
                    videos=None if not self.send_media_to_model else videos,
                    files=None if not self.send_media_to_model else files,
                    **kwargs,
                )
            else:
                # If the input is None, return None
                return None

        else:
            if isinstance(input_message, list):
                input_content: Union[str, list[Any], list[Message]]
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
                    images=None if not self.send_media_to_model else images,
                    audio=None if not self.send_media_to_model else audio,
                    videos=None if not self.send_media_to_model else videos,
                    files=None if not self.send_media_to_model else files,
                    **kwargs,
                )

            # If message is provided as a Message, use it directly
            elif isinstance(input_message, Message):
                return input_message
            # If message is provided as a dict, try to validate it as a Message
            elif isinstance(input_message, dict):
                try:
                    if self.input_schema and is_typed_dict(self.input_schema):
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
                if self.add_knowledge_to_context:
                    if isinstance(input_message, str):
                        user_msg_content = input_message
                    elif callable(input_message):
                        user_msg_content = input_message(agent=self)
                    else:
                        raise Exception("input must be a string or a callable when add_references is True")

                    try:
                        retrieval_timer = Timer()
                        retrieval_timer.start()
                        docs_from_knowledge = self.get_relevant_docs_from_knowledge(
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

                if self.resolve_in_context:
                    user_msg_content = self._format_message_with_state_variables(
                        user_msg_content,
                        run_context=run_context,
                    )

                # Convert to string for concatenation operations
                user_msg_content_str = get_text_from_message(user_msg_content) if user_msg_content is not None else ""

                # 4.1 Add knowledge references to user message
                if (
                    self.add_knowledge_to_context
                    and references is not None
                    and references.references is not None
                    and len(references.references) > 0
                ):
                    user_msg_content_str += "\n\nUse the following references from the knowledge base if it helps:\n"
                    user_msg_content_str += "<references>\n"
                    user_msg_content_str += self._convert_documents_to_string(references.references) + "\n"
                    user_msg_content_str += "</references>"
                # 4.2 Add context to user message
                if add_dependencies_to_context and run_context.dependencies is not None:
                    user_msg_content_str += "\n\n<additional context>\n"
                    user_msg_content_str += self._convert_dependencies_to_string(run_context.dependencies) + "\n"
                    user_msg_content_str += "</additional context>"

                # Use the string version for the final content
                user_msg_content = user_msg_content_str

                # Return the user message
                return Message(
                    role="user",
                    content=user_msg_content,
                    images=None if not self.send_media_to_model else images,
                    audio=None if not self.send_media_to_model else audio,
                    videos=None if not self.send_media_to_model else videos,
                    files=None if not self.send_media_to_model else files,
                    **kwargs,
                )

    async def _aget_user_message(
        self,
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
        references = None

        if input_message is None:
            # If we have any media, return a message with empty content
            if images is not None or audio is not None or videos is not None or files is not None:
                return Message(
                    role="user",
                    content="",
                    images=None if not self.send_media_to_model else images,
                    audio=None if not self.send_media_to_model else audio,
                    videos=None if not self.send_media_to_model else videos,
                    files=None if not self.send_media_to_model else files,
                    **kwargs,
                )
            else:
                # If the input is None, return None
                return None

        else:
            if isinstance(input_message, list):
                input_content: Union[str, list[Any], list[Message]]
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
                    images=None if not self.send_media_to_model else images,
                    audio=None if not self.send_media_to_model else audio,
                    videos=None if not self.send_media_to_model else videos,
                    files=None if not self.send_media_to_model else files,
                    **kwargs,
                )

            # If message is provided as a Message, use it directly
            elif isinstance(input_message, Message):
                return input_message
            # If message is provided as a dict, try to validate it as a Message
            elif isinstance(input_message, dict):
                try:
                    if self.input_schema and is_typed_dict(self.input_schema):
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
                if self.add_knowledge_to_context:
                    if isinstance(input_message, str):
                        user_msg_content = input_message
                    elif callable(input_message):
                        user_msg_content = input_message(agent=self)
                    else:
                        raise Exception("input must be a string or a callable when add_references is True")

                    try:
                        retrieval_timer = Timer()
                        retrieval_timer.start()
                        docs_from_knowledge = await self.aget_relevant_docs_from_knowledge(
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

                if self.resolve_in_context:
                    user_msg_content = self._format_message_with_state_variables(
                        user_msg_content,
                        run_context=run_context,
                    )

                # Convert to string for concatenation operations
                user_msg_content_str = get_text_from_message(user_msg_content) if user_msg_content is not None else ""

                # 4.1 Add knowledge references to user message
                if (
                    self.add_knowledge_to_context
                    and references is not None
                    and references.references is not None
                    and len(references.references) > 0
                ):
                    user_msg_content_str += "\n\nUse the following references from the knowledge base if it helps:\n"
                    user_msg_content_str += "<references>\n"
                    user_msg_content_str += self._convert_documents_to_string(references.references) + "\n"
                    user_msg_content_str += "</references>"
                # 4.2 Add context to user message
                if add_dependencies_to_context and run_context.dependencies is not None:
                    user_msg_content_str += "\n\n<additional context>\n"
                    user_msg_content_str += self._convert_dependencies_to_string(run_context.dependencies) + "\n"
                    user_msg_content_str += "</additional context>"

                # Use the string version for the final content
                user_msg_content = user_msg_content_str

                # Return the user message
                return Message(
                    role="user",
                    content=user_msg_content,
                    images=None if not self.send_media_to_model else images,
                    audio=None if not self.send_media_to_model else audio,
                    videos=None if not self.send_media_to_model else videos,
                    files=None if not self.send_media_to_model else files,
                    **kwargs,
                )

    def _get_messages_for_parser_model(
        self,
        model_response: ModelResponse,
        response_format: Optional[Union[Dict, Type[BaseModel]]],
        run_context: Optional[RunContext] = None,
    ) -> List[Message]:
        from agno.utils.prompts import get_json_output_prompt

        """Get the messages for the parser model."""
        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        system_content = (
            self.parser_model_prompt
            if self.parser_model_prompt is not None
            else "You are tasked with creating a structured output from the provided user message."
        )

        if response_format == {"type": "json_object"} and output_schema is not None:
            system_content += f"{get_json_output_prompt(output_schema)}"  # type: ignore

        return [
            Message(role="system", content=system_content),
            Message(role="user", content=model_response.content),
        ]

    def _get_messages_for_parser_model_stream(
        self,
        run_response: TeamRunOutput,
        response_format: Optional[Union[Dict, Type[BaseModel]]],
        run_context: Optional[RunContext] = None,
    ) -> List[Message]:
        """Get the messages for the parser model."""
        from agno.utils.prompts import get_json_output_prompt

        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        system_content = (
            self.parser_model_prompt
            if self.parser_model_prompt is not None
            else "You are tasked with creating a structured output from the provided data."
        )

        if response_format == {"type": "json_object"} and output_schema is not None:
            system_content += f"{get_json_output_prompt(output_schema)}"  # type: ignore

        return [
            Message(role="system", content=system_content),
            Message(role="user", content=run_response.content),
        ]

    def _get_messages_for_output_model(self, messages: List[Message]) -> List[Message]:
        """Get the messages for the output model."""

        if self.output_model_prompt is not None:
            system_message_exists = False
            for message in messages:
                if message.role == "system":
                    system_message_exists = True
                    message.content = self.output_model_prompt
                    break
            if not system_message_exists:
                messages.insert(0, Message(role="system", content=self.output_model_prompt))

        # Remove the last assistant message from the messages list
        messages.pop(-1)

        return messages

    def _format_message_with_state_variables(
        self,
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

    def _convert_dependencies_to_string(self, context: Dict[str, Any]) -> str:
        """Convert the context dictionary to a string representation.

        Args:
            context: Dictionary containing context data

        Returns:
            String representation of the context, or empty string if conversion fails
        """

        if context is None:
            return ""

        try:
            return json.dumps(context, indent=2, default=str)
        except (TypeError, ValueError, OverflowError) as e:
            log_warning(f"Failed to convert context to JSON: {e}")
            # Attempt a fallback conversion for non-serializable objects
            sanitized_context = {}
            for key, value in context.items():
                try:
                    # Try to serialize each value individually
                    json.dumps({key: value}, default=str)
                    sanitized_context[key] = value
                except Exception as e:
                    log_error(f"Failed to serialize to JSON: {e}")
                    # If serialization fails, convert to string representation
                    sanitized_context[key] = str(value)

            try:
                return json.dumps(sanitized_context, indent=2)
            except Exception as e:
                log_error(f"Failed to convert sanitized context to JSON: {e}")
                return str(context)

    def _get_json_output_prompt(self, output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None) -> str:
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

    def deep_copy(self, *, update: Optional[Dict[str, Any]] = None) -> "Team":
        """Create and return a deep copy of this Team, optionally updating fields.

        This creates a fresh Team instance with isolated mutable state while sharing
        heavy resources like database connections and models. Member agents are also
        deep copied to ensure complete isolation.

        Args:
            update: Optional dictionary of fields to override in the new Team.

        Returns:
            Team: A new Team instance with copied state.
        """
        from dataclasses import fields

        # Extract the fields to set for the new Team
        fields_for_new_team: Dict[str, Any] = {}

        for f in fields(cast(Any, self)):
            # Skip private fields (not part of __init__ signature)
            if f.name.startswith("_"):
                continue

            field_value = getattr(self, f.name)
            if field_value is not None:
                try:
                    fields_for_new_team[f.name] = self._deep_copy_field(f.name, field_value)
                except Exception as e:
                    log_warning(f"Failed to deep copy field '{f.name}': {e}. Using original value.")
                    fields_for_new_team[f.name] = field_value

        # Update fields if provided
        if update:
            fields_for_new_team.update(update)

        # Create a new Team
        try:
            new_team = self.__class__(**fields_for_new_team)
            log_debug(f"Created new {self.__class__.__name__}")
            return cast("Team", new_team)
        except Exception as e:
            log_error(f"Failed to create deep copy of {self.__class__.__name__}: {e}")
            raise

    def _deep_copy_field(self, field_name: str, field_value: Any) -> Any:
        """Helper method to deep copy a field based on its type."""
        from copy import deepcopy

        # For members, deep copy each agent/team
        if field_name == "members" and field_value is not None:
            copied_members = []
            for member in field_value:
                if hasattr(member, "deep_copy"):
                    copied_members.append(member.deep_copy())
                else:
                    copied_members.append(member)
            return copied_members

        # For tools, share MCP tools but copy others
        if field_name == "tools" and field_value is not None:
            try:
                copied_tools = []
                for tool in field_value:
                    try:
                        # Share MCP tools (they maintain server connections)
                        is_mcp_tool = hasattr(type(tool), "__mro__") and any(
                            c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
                        )
                        if is_mcp_tool:
                            copied_tools.append(tool)
                        else:
                            try:
                                copied_tools.append(deepcopy(tool))
                            except Exception:
                                # Tool can't be deep copied, share by reference
                                copied_tools.append(tool)
                    except Exception:
                        # MCP detection failed, share tool by reference to be safe
                        copied_tools.append(tool)
                return copied_tools
            except Exception as e:
                # If entire tools processing fails, log and return original list
                log_warning(f"Failed to process tools for deep copy: {e}")
                return field_value

        # Share heavy resources - these maintain connections/pools that shouldn't be duplicated
        if field_name in (
            "db",
            "model",
            "reasoning_model",
            "knowledge",
            "memory_manager",
            "parser_model",
            "output_model",
            "session_summary_manager",
            "culture_manager",
            "compression_manager",
            "learning",
            "skills",
        ):
            return field_value

        # For compound types, attempt a deep copy
        if isinstance(field_value, (list, dict, set)):
            try:
                return deepcopy(field_value)
            except Exception:
                try:
                    return copy(field_value)
                except Exception as e:
                    log_warning(f"Failed to copy field: {field_name} - {e}")
                    return field_value

        # For pydantic models, attempt a model_copy
        if isinstance(field_value, BaseModel):
            try:
                return field_value.model_copy(deep=True)
            except Exception:
                try:
                    return field_value.model_copy(deep=False)
                except Exception as e:
                    log_warning(f"Failed to copy field: {field_name} - {e}")
                    return field_value

        # For other types, attempt a shallow copy first
        try:
            return copy(field_value)
        except Exception:
            # If copy fails, return as is
            return field_value
