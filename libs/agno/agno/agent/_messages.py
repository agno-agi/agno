"""System and user message construction helpers for Agent."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Type,
    Union,
)

from pydantic import BaseModel

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.agent._utils import convert_dependencies_to_string, convert_documents_to_string
from agno.filters import FilterExpr
from agno.media import Audio, File, Image, Video
from agno.models.message import Message, MessageReferences
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.messages import RunMessages
from agno.session import AgentSession
from agno.tools.function import Function
from agno.utils.agent import (
    aexecute_instructions,
    aexecute_system_message,
    execute_instructions,
    execute_system_message,
)
from agno.utils.common import is_typed_dict
from agno.utils.log import log_debug, log_warning
from agno.utils.message import filter_tool_calls, get_text_from_message
from agno.utils.prompts import get_json_output_prompt, get_response_model_format_prompt
from agno.utils.timer import Timer


def _get_resolved_knowledge(agent: "Agent", run_context: Optional[RunContext] = None) -> Any:
    """Get the resolved knowledge, preferring run_context over agent.knowledge."""
    from agno.utils.callables import get_resolved_knowledge

    return get_resolved_knowledge(agent, run_context)


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def format_message_with_state_variables(
    agent: Agent,
    message: Any,
    run_context: Optional[RunContext] = None,
) -> Any:
    """Format a message with the session state variables from run_context."""
    import re
    import string
    from collections import ChainMap
    from copy import deepcopy

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

    converted_msg = deepcopy(message)
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


# ---------------------------------------------------------------------------
# System message
# ---------------------------------------------------------------------------


def get_system_message(
    agent: Agent,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    tools: Optional[List[Union[Function, dict]]] = None,
    add_session_state_to_context: Optional[bool] = None,
) -> Optional[Message]:
    """Return the system message for the Agent.

    1. If the system_message is provided, use that.
    2. If build_context is False, return None.
    3. Build and return the default system message for the Agent.
    """

    # Extract values from run_context
    from agno.agent._init import set_culture_manager, set_memory_manager

    session_state = run_context.session_state if run_context else None
    user_id = run_context.user_id if run_context else None

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    # 1. If the system_message is provided, use that.
    if agent.system_message is not None:
        if isinstance(agent.system_message, Message):
            return agent.system_message

        sys_message_content: str = ""
        if isinstance(agent.system_message, str):
            sys_message_content = agent.system_message
        elif callable(agent.system_message):
            sys_message_content = execute_system_message(
                agent=agent, system_message=agent.system_message, session_state=session_state, run_context=run_context
            )
            if not isinstance(sys_message_content, str):
                raise Exception("system_message must return a string")

        if agent.resolve_in_context:
            sys_message_content = format_message_with_state_variables(
                agent,
                sys_message_content,
                run_context=run_context,
            )

        # type: ignore
        return Message(role=agent.system_message_role, content=sys_message_content)

    # 2. If build_context is False, return None.
    if not agent.build_context:
        return None

    if agent.model is None:
        raise Exception("model not set")

    # 3. Build and return the default system message for the Agent.
    # 3.1 Build the list of instructions for the system message
    instructions: List[str] = []
    if agent.instructions is not None:
        _instructions = agent.instructions
        if callable(agent.instructions):
            _instructions = execute_instructions(
                agent=agent, instructions=agent.instructions, session_state=session_state, run_context=run_context
            )

        if isinstance(_instructions, str):
            instructions.append(_instructions)
        elif isinstance(_instructions, list):
            instructions.extend(_instructions)

    # 3.1.1 Add instructions from the Model
    _model_instructions = agent.model.get_instructions_for_model(tools)
    if _model_instructions is not None:
        instructions.extend(_model_instructions)

    # 3.2 Build a list of additional information for the system message
    additional_information: List[str] = []
    # 3.2.1 Add instructions for using markdown
    if agent.markdown and output_schema is None:
        additional_information.append("Use markdown to format your answers.")
    # 3.2.2 Add the current datetime
    if agent.add_datetime_to_context:
        from datetime import datetime

        tz = None

        if agent.timezone_identifier:
            try:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(agent.timezone_identifier)
            except Exception:
                log_warning("Invalid timezone identifier")

        time = datetime.now(tz) if tz else datetime.now()

        additional_information.append(f"The current time is {time}.")

    # 3.2.3 Add the current location
    if agent.add_location_to_context:
        from agno.utils.location import get_location

        location = get_location()
        if location:
            location_str = ", ".join(
                filter(
                    None,
                    [
                        location.get("city"),
                        location.get("region"),
                        location.get("country"),
                    ],
                )
            )
            if location_str:
                additional_information.append(f"Your approximate location is: {location_str}.")

    # 3.2.4 Add agent name if provided
    if agent.name is not None and agent.add_name_to_context:
        additional_information.append(f"Your name is: {agent.name}.")

    # 3.3 Build the default system message for the Agent.
    system_message_content: str = ""
    # 3.3.1 First add the Agent description if provided
    if agent.description is not None:
        system_message_content += f"{agent.description}\n"
    # 3.3.2 Then add the Agent role if provided
    if agent.role is not None:
        system_message_content += f"\n<your_role>\n{agent.role}\n</your_role>\n\n"
    # 3.3.3 Then add instructions for the Agent
    if len(instructions) > 0:
        if agent.use_instruction_tags:
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
    # 3.3.4 Add additional information
    if len(additional_information) > 0:
        system_message_content += "<additional_information>"
        for _ai in additional_information:
            system_message_content += f"\n- {_ai}"
        system_message_content += "\n</additional_information>\n\n"
    # 3.3.5 Then add instructions for the tools
    if agent._tool_instructions is not None:
        for _ti in agent._tool_instructions:
            system_message_content += f"{_ti}\n"

    # Format the system message with the session state variables
    if agent.resolve_in_context:
        system_message_content = format_message_with_state_variables(
            agent,
            system_message_content,
            run_context=run_context,
        )

    # 3.3.7 Then add the expected output
    if agent.expected_output is not None:
        system_message_content += f"<expected_output>\n{agent.expected_output.strip()}\n</expected_output>\n\n"
    # 3.3.8 Then add additional context
    if agent.additional_context is not None:
        system_message_content += f"{agent.additional_context}\n"
    # 3.3.8.1 Then add skills to the system prompt
    if agent.skills is not None:
        skills_snippet = agent.skills.get_system_prompt_snippet()
        if skills_snippet:
            system_message_content += f"\n{skills_snippet}\n"
    # 3.3.9 Then add memories to the system prompt
    if agent.add_memories_to_context:
        _memory_manager_not_set = False
        if not user_id:
            user_id = "default"
        if agent.memory_manager is None:
            set_memory_manager(agent)
            _memory_manager_not_set = True

        user_memories = agent.memory_manager.get_user_memories(user_id=user_id)  # type: ignore

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
            agent.memory_manager = None

        if agent.enable_agentic_memory:
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

    # 3.3.10 Then add cultural knowledge to the system prompt
    if agent.add_culture_to_context:
        _culture_manager_not_set = False
        if not agent.culture_manager:
            set_culture_manager(agent)
            _culture_manager_not_set = True

        cultural_knowledge = agent.culture_manager.get_all_knowledge()  # type: ignore

        if cultural_knowledge and len(cultural_knowledge) > 0:
            system_message_content += (
                "You have access to shared **Cultural Knowledge**, which provides context, norms, rules and guidance "
                "for your reasoning, communication, and decision-making. "
                "Cultural Knowledge represents the collective understanding, values, rules and practices that have "
                "emerged across agents and teams. It encodes collective experience — including preferred "
                "approaches, common patterns, lessons learned, and ethical guardrails.\n\n"
                "When performing any task:\n"
                "- **Reference Cultural Knowledge** to align with shared norms and best practices.\n"
                "- **Apply it contextually**, not mechanically — adapt principles to the current situation.\n"
                "- **Preserve consistency** with cultural values (tone, reasoning, and style) unless explicitly told otherwise.\n"
                "- **Extend it** when you discover new insights — your outputs may become future Cultural Knowledge.\n"
                "- **Clarify conflicts** if Cultural Knowledge appears to contradict explicit user instructions.\n\n"
                "Your goal is to act not only intelligently but also *culturally coherently* — reflecting the "
                "collective intelligence of the system.\n\n"
                "Below is the currently available Cultural Knowledge for this context:\n\n"
            )
            system_message_content += "<cultural_knowledge>"
            for _knowledge in cultural_knowledge:  # type: ignore
                system_message_content += "\n---"
                system_message_content += f"\nName: {_knowledge.name}"
                system_message_content += f"\nSummary: {_knowledge.summary}"
                system_message_content += f"\nContent: {_knowledge.content}"
            system_message_content += "\n</cultural_knowledge>\n"
        else:
            system_message_content += (
                "You have the capability to access shared **Cultural Knowledge**, which normally provides "
                "context, norms, and guidance for your behavior and reasoning. However, no cultural knowledge "
                "is currently available in this session.\n"
                "Proceed thoughtfully and document any useful insights you create — they may become future "
                "Cultural Knowledge for others.\n\n"
            )

        if _culture_manager_not_set:
            agent.culture_manager = None

        if agent.enable_agentic_culture:
            system_message_content += (
                "\n<contributing_to_culture>\n"
                "When you discover an insight, pattern, rule, or best practice that will help future agents, use the `create_or_update_cultural_knowledge` tool to add or update entries in the shared cultural knowledge.\n"
                "\n"
                "When to contribute:\n"
                "- You discover a reusable insight, pattern, rule, or best practice that will help future agents.\n"
                "- You correct or clarify an existing cultural entry.\n"
                "- You capture a guardrail, decision rationale, postmortem lesson, or example template.\n"
                "- You identify missing context that should persist across sessions or teams.\n"
                "\n"
                "Cultural knowledge should capture reusable insights, best practices, or contextual knowledge that transcends individual conversations.\n"
                "Mention your contribution to the user only if it is relevant to their request or they asked to be notified.\n"
                "</contributing_to_culture>\n\n"
            )

    # 3.3.11 Then add a summary of the interaction to the system prompt
    if agent.add_session_summary_to_context and session.summary is not None:
        system_message_content += "Here is a brief summary of your previous interactions:\n\n"
        system_message_content += "<summary_of_previous_interactions>\n"
        system_message_content += session.summary.summary
        system_message_content += "\n</summary_of_previous_interactions>\n\n"
        system_message_content += (
            "Note: this information is from previous interactions and may be outdated. "
            "You should ALWAYS prefer information from this conversation over the past summary.\n\n"
        )

    # 3.3.12 then add learnings to the system prompt
    if agent._learning is not None and agent.add_learnings_to_context:
        learning_context = agent._learning.build_context(
            user_id=user_id,
            session_id=session.session_id if session else None,
            agent_id=agent.id,
        )
        if learning_context:
            system_message_content += learning_context + "\n"

    # 3.3.13 then add search_knowledge instructions to the system prompt
    _resolved_knowledge = _get_resolved_knowledge(agent, run_context)
    if _resolved_knowledge is not None and agent.search_knowledge and agent.add_search_knowledge_instructions:
        build_context_fn = getattr(_resolved_knowledge, "build_context", None)
        if callable(build_context_fn):
            knowledge_context = build_context_fn(
                enable_agentic_filters=agent.enable_agentic_knowledge_filters,
            )
            if knowledge_context is not None:
                system_message_content += knowledge_context + "\n"

    # 3.3.14 Add the system message from the Model
    system_message_from_model = agent.model.get_system_message_for_model(tools)
    if system_message_from_model is not None:
        system_message_content += system_message_from_model

    # 3.3.15 Add the JSON output prompt if output_schema is provided and the model does not support native structured outputs or JSON schema outputs
    # or if use_json_mode is True
    if (
        output_schema is not None
        and agent.parser_model is None
        and not (
            (agent.model.supports_native_structured_outputs or agent.model.supports_json_schema_outputs)
            and (not agent.use_json_mode or agent.structured_outputs is True)
        )
    ):
        system_message_content += f"{get_json_output_prompt(output_schema)}"  # type: ignore

    # 3.3.16 Add the response model format prompt if output_schema is provided (Pydantic only)
    if output_schema is not None and agent.parser_model is not None and not isinstance(output_schema, dict):
        system_message_content += f"{get_response_model_format_prompt(output_schema)}"

    # 3.3.17 Add the session state to the system message
    if add_session_state_to_context and session_state is not None:
        system_message_content += f"\n<session_state>\n{session_state}\n</session_state>\n\n"

    # Return the system message
    return (
        Message(role=agent.system_message_role, content=system_message_content.strip())  # type: ignore
        if system_message_content
        else None
    )


async def aget_system_message(
    agent: Agent,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    tools: Optional[List[Union[Function, dict]]] = None,
    add_session_state_to_context: Optional[bool] = None,
) -> Optional[Message]:
    """Return the system message for the Agent.

    1. If the system_message is provided, use that.
    2. If build_context is False, return None.
    3. Build and return the default system message for the Agent.
    """

    # Extract values from run_context
    from agno.agent._init import has_async_db, set_culture_manager, set_memory_manager

    session_state = run_context.session_state if run_context else None
    user_id = run_context.user_id if run_context else None

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    # 1. If the system_message is provided, use that.
    if agent.system_message is not None:
        if isinstance(agent.system_message, Message):
            return agent.system_message

        sys_message_content: str = ""
        if isinstance(agent.system_message, str):
            sys_message_content = agent.system_message
        elif callable(agent.system_message):
            sys_message_content = await aexecute_system_message(
                agent=agent, system_message=agent.system_message, session_state=session_state, run_context=run_context
            )
            if not isinstance(sys_message_content, str):
                raise Exception("system_message must return a string")

        # Format the system message with the session state variables
        if agent.resolve_in_context:
            sys_message_content = format_message_with_state_variables(
                agent,
                sys_message_content,
                run_context=run_context,
            )

        # type: ignore
        return Message(role=agent.system_message_role, content=sys_message_content)

    # 2. If build_context is False, return None.
    if not agent.build_context:
        return None

    if agent.model is None:
        raise Exception("model not set")

    # 3. Build and return the default system message for the Agent.
    # 3.1 Build the list of instructions for the system message
    instructions: List[str] = []
    if agent.instructions is not None:
        _instructions = agent.instructions
        if callable(agent.instructions):
            _instructions = await aexecute_instructions(
                agent=agent, instructions=agent.instructions, session_state=session_state, run_context=run_context
            )

        if isinstance(_instructions, str):
            instructions.append(_instructions)
        elif isinstance(_instructions, list):
            instructions.extend(_instructions)

    # 3.1.1 Add instructions from the Model
    _model_instructions = agent.model.get_instructions_for_model(tools)
    if _model_instructions is not None:
        instructions.extend(_model_instructions)

    # 3.2 Build a list of additional information for the system message
    additional_information: List[str] = []
    # 3.2.1 Add instructions for using markdown
    if agent.markdown and output_schema is None:
        additional_information.append("Use markdown to format your answers.")
    # 3.2.2 Add the current datetime
    if agent.add_datetime_to_context:
        from datetime import datetime

        tz = None

        if agent.timezone_identifier:
            try:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(agent.timezone_identifier)
            except Exception:
                log_warning("Invalid timezone identifier")

        time = datetime.now(tz) if tz else datetime.now()

        additional_information.append(f"The current time is {time}.")

    # 3.2.3 Add the current location
    if agent.add_location_to_context:
        from agno.utils.location import get_location

        location = get_location()
        if location:
            location_str = ", ".join(
                filter(
                    None,
                    [
                        location.get("city"),
                        location.get("region"),
                        location.get("country"),
                    ],
                )
            )
            if location_str:
                additional_information.append(f"Your approximate location is: {location_str}.")

    # 3.2.4 Add agent name if provided
    if agent.name is not None and agent.add_name_to_context:
        additional_information.append(f"Your name is: {agent.name}.")

    # 3.3 Build the default system message for the Agent.
    system_message_content: str = ""
    # 3.3.1 First add the Agent description if provided
    if agent.description is not None:
        system_message_content += f"{agent.description}\n"
    # 3.3.2 Then add the Agent role if provided
    if agent.role is not None:
        system_message_content += f"\n<your_role>\n{agent.role}\n</your_role>\n\n"
    # 3.3.3 Then add instructions for the Agent
    if len(instructions) > 0:
        if agent.use_instruction_tags:
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
    # 3.3.4 Add additional information
    if len(additional_information) > 0:
        system_message_content += "<additional_information>"
        for _ai in additional_information:
            system_message_content += f"\n- {_ai}"
        system_message_content += "\n</additional_information>\n\n"
    # 3.3.5 Then add instructions for the tools
    if agent._tool_instructions is not None:
        for _ti in agent._tool_instructions:
            system_message_content += f"{_ti}\n"

    # Format the system message with the session state variables
    if agent.resolve_in_context:
        system_message_content = format_message_with_state_variables(
            agent,
            system_message_content,
            run_context=run_context,
        )

    # 3.3.7 Then add the expected output
    if agent.expected_output is not None:
        system_message_content += f"<expected_output>\n{agent.expected_output.strip()}\n</expected_output>\n\n"
    # 3.3.8 Then add additional context
    if agent.additional_context is not None:
        system_message_content += f"{agent.additional_context}\n"
    # 3.3.8.1 Then add skills to the system prompt
    if agent.skills is not None:
        skills_snippet = agent.skills.get_system_prompt_snippet()
        if skills_snippet:
            system_message_content += f"\n{skills_snippet}\n"
    # 3.3.9 Then add memories to the system prompt
    if agent.add_memories_to_context:
        _memory_manager_not_set = False
        if not user_id:
            user_id = "default"
        if agent.memory_manager is None:
            set_memory_manager(agent)
            _memory_manager_not_set = True

        if has_async_db(agent):
            user_memories = await agent.memory_manager.aget_user_memories(user_id=user_id)  # type: ignore
        else:
            user_memories = agent.memory_manager.get_user_memories(user_id=user_id)  # type: ignore

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
            agent.memory_manager = None

        if agent.enable_agentic_memory:
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

    # 3.3.10 Then add cultural knowledge to the system prompt
    if agent.add_culture_to_context:
        _culture_manager_not_set = False
        if not agent.culture_manager:
            set_culture_manager(agent)
            _culture_manager_not_set = True

        cultural_knowledge = await agent.culture_manager.aget_all_knowledge()  # type: ignore

        if cultural_knowledge and len(cultural_knowledge) > 0:
            system_message_content += (
                "You have access to shared **Cultural Knowledge**, which provides context, norms, rules and guidance "
                "for your reasoning, communication, and decision-making.\n\n"
                "Cultural Knowledge represents the collective understanding, values, rules and practices that have "
                "emerged across agents and teams. It encodes collective experience — including preferred "
                "approaches, common patterns, lessons learned, and ethical guardrails.\n\n"
                "When performing any task:\n"
                "- **Reference Cultural Knowledge** to align with shared norms and best practices.\n"
                "- **Apply it contextually**, not mechanically — adapt principles to the current situation.\n"
                "- **Preserve consistency** with cultural values (tone, reasoning, and style) unless explicitly told otherwise.\n"
                "- **Extend it** when you discover new insights — your outputs may become future Cultural Knowledge.\n"
                "- **Clarify conflicts** if Cultural Knowledge appears to contradict explicit user instructions.\n\n"
                "Your goal is to act not only intelligently but also *culturally coherently* — reflecting the "
                "collective intelligence of the system.\n\n"
                "Below is the currently available Cultural Knowledge for this context:\n\n"
            )
            system_message_content += "<cultural_knowledge>"
            for _knowledge in cultural_knowledge:  # type: ignore
                system_message_content += "\n---"
                system_message_content += f"\nName: {_knowledge.name}"
                system_message_content += f"\nSummary: {_knowledge.summary}"
                system_message_content += f"\nContent: {_knowledge.content}"
            system_message_content += "\n</cultural_knowledge>\n"
        else:
            system_message_content += (
                "You have the capability to access shared **Cultural Knowledge**, which normally provides "
                "context, norms, and guidance for your behavior and reasoning. However, no cultural knowledge "
                "is currently available in this session.\n"
                "Proceed thoughtfully and document any useful insights you create — they may become future "
                "Cultural Knowledge for others.\n\n"
            )

        if _culture_manager_not_set:
            agent.culture_manager = None

        if agent.enable_agentic_culture:
            system_message_content += (
                "\n<contributing_to_culture>\n"
                "When you discover an insight, pattern, rule, or best practice that will help future agents, use the `create_or_update_cultural_knowledge` tool to add or update entries in the shared cultural knowledge.\n"
                "\n"
                "When to contribute:\n"
                "- You discover a reusable insight, pattern, rule, or best practice that will help future agents.\n"
                "- You correct or clarify an existing cultural entry.\n"
                "- You capture a guardrail, decision rationale, postmortem lesson, or example template.\n"
                "- You identify missing context that should persist across sessions or teams.\n"
                "\n"
                "Cultural knowledge should capture reusable insights, best practices, or contextual knowledge that transcends individual conversations.\n"
                "Mention your contribution to the user only if it is relevant to their request or they asked to be notified.\n"
                "</contributing_to_culture>\n\n"
            )

    # 3.3.11 Then add a summary of the interaction to the system prompt
    if agent.add_session_summary_to_context and session.summary is not None:
        system_message_content += "Here is a brief summary of your previous interactions:\n\n"
        system_message_content += "<summary_of_previous_interactions>\n"
        system_message_content += session.summary.summary
        system_message_content += "\n</summary_of_previous_interactions>\n\n"
        system_message_content += (
            "Note: this information is from previous interactions and may be outdated. "
            "You should ALWAYS prefer information from this conversation over the past summary.\n\n"
        )

    # 3.3.12 then add learnings to the system prompt
    if agent._learning is not None and agent.add_learnings_to_context:
        learning_context = await agent._learning.abuild_context(
            user_id=user_id,
            session_id=session.session_id if session else None,
            agent_id=agent.id,
        )
        if learning_context:
            system_message_content += learning_context + "\n"

    # 3.3.13 then add search_knowledge instructions to the system prompt
    _resolved_knowledge = _get_resolved_knowledge(agent, run_context)
    if _resolved_knowledge is not None and agent.search_knowledge and agent.add_search_knowledge_instructions:
        # Prefer async version if available for async databases
        abuild_context_fn = getattr(_resolved_knowledge, "abuild_context", None)
        build_context_fn = getattr(_resolved_knowledge, "build_context", None)
        if callable(abuild_context_fn):
            knowledge_context = await abuild_context_fn(
                enable_agentic_filters=agent.enable_agentic_knowledge_filters,
            )
            if knowledge_context is not None:
                system_message_content += knowledge_context + "\n"
        elif callable(build_context_fn):
            knowledge_context = build_context_fn(
                enable_agentic_filters=agent.enable_agentic_knowledge_filters,
            )
            if knowledge_context is not None:
                system_message_content += knowledge_context + "\n"

    # 3.3.14 Add the system message from the Model
    system_message_from_model = agent.model.get_system_message_for_model(tools)
    if system_message_from_model is not None:
        system_message_content += system_message_from_model

    # 3.3.15 Add the JSON output prompt if output_schema is provided and the model does not support native structured outputs or JSON schema outputs
    # or if use_json_mode is True
    if (
        output_schema is not None
        and agent.parser_model is None
        and not (
            (agent.model.supports_native_structured_outputs or agent.model.supports_json_schema_outputs)
            and (not agent.use_json_mode or agent.structured_outputs is True)
        )
    ):
        system_message_content += f"{get_json_output_prompt(output_schema)}"  # type: ignore

    # 3.3.16 Add the response model format prompt if output_schema is provided (Pydantic only)
    if output_schema is not None and agent.parser_model is not None and not isinstance(output_schema, dict):
        system_message_content += f"{get_response_model_format_prompt(output_schema)}"

    # 3.3.17 Add the session state to the system message
    if add_session_state_to_context and session_state is not None:
        system_message_content += get_formatted_session_state_for_system_message(agent, session_state)

    # Return the system message
    return (
        Message(role=agent.system_message_role, content=system_message_content.strip())  # type: ignore
        if system_message_content
        else None
    )


def get_formatted_session_state_for_system_message(agent: Agent, session_state: Dict[str, Any]) -> str:
    return f"\n<session_state>\n{session_state}\n</session_state>\n\n"


# ---------------------------------------------------------------------------
# User message
# ---------------------------------------------------------------------------


def get_user_message(
    agent: Agent,
    *,
    run_response: RunOutput,
    run_context: Optional[RunContext] = None,
    input: Optional[Union[str, List, Dict, Message, BaseModel, List[Message]]] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    **kwargs: Any,
) -> Optional[Message]:
    """Return the user message for the Agent.

    1. If the user_message is provided, use that.
    2. If build_user_context is False or if the message is a list, return the message as is.
    3. Build the default user message for the Agent
    """
    # Extract values from run_context
    dependencies = run_context.dependencies if run_context else None
    knowledge_filters = run_context.knowledge_filters if run_context else None
    # Get references from the knowledge base to use in the user message
    references = None

    # 1. If build_user_context is False or message is a list, return the message as is.
    if not agent.build_user_context:
        return Message(
            role=agent.user_message_role or "user",
            content=input,  # type: ignore
            images=None if not agent.send_media_to_model else images,
            audio=None if not agent.send_media_to_model else audio,
            videos=None if not agent.send_media_to_model else videos,
            files=None if not agent.send_media_to_model else files,
            **kwargs,
        )
    # 2. Build the user message for the Agent
    elif input is None:
        # If we have any media, return a message with empty content
        if images is not None or audio is not None or videos is not None or files is not None:
            return Message(
                role=agent.user_message_role or "user",
                content="",
                images=None if not agent.send_media_to_model else images,
                audio=None if not agent.send_media_to_model else audio,
                videos=None if not agent.send_media_to_model else videos,
                files=None if not agent.send_media_to_model else files,
                **kwargs,
            )
        else:
            # If the input is None, return None
            return None

    else:
        # Handle list messages by converting to string
        if isinstance(input, list):
            # Convert list to string (join with newlines if all elements are strings)
            if all(isinstance(item, str) for item in input):
                message_content = "\n".join(input)  # type: ignore
            else:
                message_content = str(input)

            return Message(
                role=agent.user_message_role,
                content=message_content,
                images=None if not agent.send_media_to_model else images,
                audio=None if not agent.send_media_to_model else audio,
                videos=None if not agent.send_media_to_model else videos,
                files=None if not agent.send_media_to_model else files,
                **kwargs,
            )

        # If message is provided as a Message, use it directly
        elif isinstance(input, Message):
            return input
        # If message is provided as a dict, try to validate it as a Message
        elif isinstance(input, dict):
            try:
                return Message.model_validate(input)
            except Exception as e:
                log_warning(f"Failed to validate message: {e}")
                raise Exception(f"Failed to validate message: {e}")

        # If message is provided as a BaseModel, convert it to a Message
        elif isinstance(input, BaseModel):
            try:
                # Create a user message with the BaseModel content
                content = input.model_dump_json(indent=2, exclude_none=True)
                return Message(role=agent.user_message_role, content=content)
            except Exception as e:
                log_warning(f"Failed to convert BaseModel to message: {e}")
                raise Exception(f"Failed to convert BaseModel to message: {e}")
        else:
            user_msg_content = input
            if agent.add_knowledge_to_context:
                if isinstance(input, str):
                    user_msg_content = input
                elif callable(input):
                    user_msg_content = input(agent=agent)
                else:
                    raise Exception("message must be a string or a callable when add_references is True")

                try:
                    retrieval_timer = Timer()
                    retrieval_timer.start()
                    docs_from_knowledge = get_relevant_docs_from_knowledge(
                        agent, query=user_msg_content, filters=knowledge_filters, run_context=run_context, **kwargs
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

            if agent.resolve_in_context:
                user_msg_content = format_message_with_state_variables(
                    agent,
                    user_msg_content,
                    run_context=run_context,
                )

            # Convert to string for concatenation operations
            user_msg_content_str = get_text_from_message(user_msg_content) if user_msg_content is not None else ""

            # 4.1 Add knowledge references to user message
            if (
                agent.add_knowledge_to_context
                and references is not None
                and references.references is not None
                and len(references.references) > 0
            ):
                user_msg_content_str += "\n\nUse the following references from the knowledge base if it helps:\n"
                user_msg_content_str += "<references>\n"
                user_msg_content_str += convert_documents_to_string(agent, references.references) + "\n"
                user_msg_content_str += "</references>"
            # 4.2 Add context to user message
            if add_dependencies_to_context and dependencies is not None:
                user_msg_content_str += "\n\n<additional context>\n"
                user_msg_content_str += convert_dependencies_to_string(agent, dependencies) + "\n"
                user_msg_content_str += "</additional context>"

            # Use the string version for the final content
            user_msg_content = user_msg_content_str

            # Return the user message
            return Message(
                role=agent.user_message_role,
                content=user_msg_content,
                audio=None if not agent.send_media_to_model else audio,
                images=None if not agent.send_media_to_model else images,
                videos=None if not agent.send_media_to_model else videos,
                files=None if not agent.send_media_to_model else files,
                **kwargs,
            )


async def aget_user_message(
    agent: Agent,
    *,
    run_response: RunOutput,
    run_context: Optional[RunContext] = None,
    input: Optional[Union[str, List, Dict, Message, BaseModel, List[Message]]] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    **kwargs: Any,
) -> Optional[Message]:
    """Return the user message for the Agent (async version).

    1. If the user_message is provided, use that.
    2. If build_user_context is False or if the message is a list, return the message as is.
    3. Build the default user message for the Agent
    """
    # Extract values from run_context
    dependencies = run_context.dependencies if run_context else None
    knowledge_filters = run_context.knowledge_filters if run_context else None
    # Get references from the knowledge base to use in the user message
    references = None

    # 1. If build_user_context is False or message is a list, return the message as is.
    if not agent.build_user_context:
        return Message(
            role=agent.user_message_role or "user",
            content=input,  # type: ignore
            images=None if not agent.send_media_to_model else images,
            audio=None if not agent.send_media_to_model else audio,
            videos=None if not agent.send_media_to_model else videos,
            files=None if not agent.send_media_to_model else files,
            **kwargs,
        )
    # 2. Build the user message for the Agent
    elif input is None:
        # If we have any media, return a message with empty content
        if images is not None or audio is not None or videos is not None or files is not None:
            return Message(
                role=agent.user_message_role or "user",
                content="",
                images=None if not agent.send_media_to_model else images,
                audio=None if not agent.send_media_to_model else audio,
                videos=None if not agent.send_media_to_model else videos,
                files=None if not agent.send_media_to_model else files,
                **kwargs,
            )
        else:
            # If the input is None, return None
            return None

    else:
        # Handle list messages by converting to string
        if isinstance(input, list):
            # Convert list to string (join with newlines if all elements are strings)
            if all(isinstance(item, str) for item in input):
                message_content = "\n".join(input)  # type: ignore
            else:
                message_content = str(input)

            return Message(
                role=agent.user_message_role,
                content=message_content,
                images=None if not agent.send_media_to_model else images,
                audio=None if not agent.send_media_to_model else audio,
                videos=None if not agent.send_media_to_model else videos,
                files=None if not agent.send_media_to_model else files,
                **kwargs,
            )

        # If message is provided as a Message, use it directly
        elif isinstance(input, Message):
            return input
        # If message is provided as a dict, try to validate it as a Message
        elif isinstance(input, dict):
            try:
                return Message.model_validate(input)
            except Exception as e:
                log_warning(f"Failed to validate message: {e}")
                raise Exception(f"Failed to validate message: {e}")

        # If message is provided as a BaseModel, convert it to a Message
        elif isinstance(input, BaseModel):
            try:
                # Create a user message with the BaseModel content
                content = input.model_dump_json(indent=2, exclude_none=True)
                return Message(role=agent.user_message_role, content=content)
            except Exception as e:
                log_warning(f"Failed to convert BaseModel to message: {e}")
                raise Exception(f"Failed to convert BaseModel to message: {e}")
        else:
            user_msg_content = input
            if agent.add_knowledge_to_context:
                if isinstance(input, str):
                    user_msg_content = input
                elif callable(input):
                    user_msg_content = input(agent=agent)
                else:
                    raise Exception("message must be a string or a callable when add_references is True")

                try:
                    retrieval_timer = Timer()
                    retrieval_timer.start()
                    docs_from_knowledge = await aget_relevant_docs_from_knowledge(
                        agent, query=user_msg_content, filters=knowledge_filters, run_context=run_context, **kwargs
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

            if agent.resolve_in_context:
                user_msg_content = format_message_with_state_variables(
                    agent,
                    user_msg_content,
                    run_context=run_context,
                )

            # Convert to string for concatenation operations
            user_msg_content_str = get_text_from_message(user_msg_content) if user_msg_content is not None else ""

            # 4.1 Add knowledge references to user message
            if (
                agent.add_knowledge_to_context
                and references is not None
                and references.references is not None
                and len(references.references) > 0
            ):
                user_msg_content_str += "\n\nUse the following references from the knowledge base if it helps:\n"
                user_msg_content_str += "<references>\n"
                user_msg_content_str += convert_documents_to_string(agent, references.references) + "\n"
                user_msg_content_str += "</references>"
            # 4.2 Add context to user message
            if add_dependencies_to_context and dependencies is not None:
                user_msg_content_str += "\n\n<additional context>\n"
                user_msg_content_str += convert_dependencies_to_string(agent, dependencies) + "\n"
                user_msg_content_str += "</additional context>"

            # Use the string version for the final content
            user_msg_content = user_msg_content_str

            # Return the user message
            return Message(
                role=agent.user_message_role,
                content=user_msg_content,
                audio=None if not agent.send_media_to_model else audio,
                images=None if not agent.send_media_to_model else images,
                videos=None if not agent.send_media_to_model else videos,
                files=None if not agent.send_media_to_model else files,
                **kwargs,
            )


# ---------------------------------------------------------------------------
# Run messages
# ---------------------------------------------------------------------------


def get_run_messages(
    agent: Agent,
    *,
    run_response: RunOutput,
    run_context: RunContext,
    input: Union[str, List, Dict, Message, BaseModel, List[Message]],
    session: AgentSession,
    user_id: Optional[str] = None,
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
    2. Add extra messages to run_messages if provided
    3. Add history to run_messages
    4. Add user message to run_messages (if input is single content)
    5. Add input messages to run_messages if provided (if input is List[Message])

    Returns:
        RunMessages object with the following attributes:
            - system_message: The system message for this run
            - user_message: The user message for this run
            - messages: List of all messages to send to the model

    Typical usage:
    run_messages = get_run_messages(
        agent, input=input, session_id=session_id, user_id=user_id, audio=audio, images=images, videos=videos, files=files, **kwargs
    )
    """

    # Initialize the RunMessages object (no media here - that's in RunInput now)
    run_messages = RunMessages()

    # 1. Add system message to run_messages
    system_message = get_system_message(
        agent,
        session=session,
        run_context=run_context,
        tools=tools,
        add_session_state_to_context=add_session_state_to_context,
    )
    if system_message is not None:
        run_messages.system_message = system_message
        run_messages.messages.append(system_message)

    # 2. Add extra messages to run_messages if provided
    if agent.additional_input is not None:
        messages_to_add_to_run_response: List[Message] = []
        if run_messages.extra_messages is None:
            run_messages.extra_messages = []

        for _m in agent.additional_input:
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
            agent.system_message_role if agent.system_message_role not in ["user", "assistant", "tool"] else None
        )

        history: List[Message] = session.get_messages(
            last_n_runs=agent.num_history_runs,
            limit=agent.num_history_messages,
            skip_roles=[skip_role] if skip_role else None,
            agent_id=agent.id if agent.team_id is not None else None,
        )

        if len(history) > 0:
            # Create a deep copy of the history messages to avoid modifying the original messages
            history_copy = [deepcopy(msg) for msg in history]

            # Tag each message as coming from history
            for _msg in history_copy:
                _msg.from_history = True

            # Filter tool calls from history if limit is set (before adding to run_messages)
            if agent.max_tool_calls_from_history is not None:
                filter_tool_calls(history_copy, agent.max_tool_calls_from_history)

            log_debug(f"Adding {len(history_copy)} messages from history")

            run_messages.messages += history_copy

    # 4. Add user message to run_messages
    user_message: Optional[Message] = None

    # 4.1 Build user message if input is None, str or list and not a list of Message/dict objects
    if (
        input is None
        or isinstance(input, str)
        or (
            isinstance(input, list)
            and not (
                len(input) > 0
                and (isinstance(input[0], Message) or (isinstance(input[0], dict) and "role" in input[0]))
            )
        )
    ):
        user_message = get_user_message(
            agent,
            run_response=run_response,
            run_context=run_context,
            input=input,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            add_dependencies_to_context=add_dependencies_to_context,
            **kwargs,
        )

    # 4.2 If input is provided as a Message, use it directly
    elif isinstance(input, Message):
        user_message = input

    # 4.3 If input is provided as a dict, try to validate it as a Message
    elif isinstance(input, dict):
        try:
            if agent.input_schema and is_typed_dict(agent.input_schema):
                import json

                content = json.dumps(input, indent=2, ensure_ascii=False)
                user_message = Message(role=agent.user_message_role, content=content)
            else:
                user_message = Message.model_validate(input)
        except Exception as e:
            log_warning(f"Failed to validate message: {e}")

    # 4.4 If input is provided as a BaseModel, convert it to a Message
    elif isinstance(input, BaseModel):
        try:
            # Create a user message with the BaseModel content
            content = input.model_dump_json(indent=2, exclude_none=True)
            user_message = Message(role=agent.user_message_role, content=content)
        except Exception as e:
            log_warning(f"Failed to convert BaseModel to message: {e}")

    # 5. Add input messages to run_messages if provided (List[Message] or List[Dict])
    if (
        isinstance(input, list)
        and len(input) > 0
        and (isinstance(input[0], Message) or (isinstance(input[0], dict) and "role" in input[0]))
    ):
        for _m in input:
            if isinstance(_m, Message):
                run_messages.messages.append(_m)
                if run_messages.extra_messages is None:
                    run_messages.extra_messages = []
                run_messages.extra_messages.append(_m)
            elif isinstance(_m, dict):
                try:
                    msg = Message.model_validate(_m)
                    run_messages.messages.append(msg)
                    if run_messages.extra_messages is None:
                        run_messages.extra_messages = []
                    run_messages.extra_messages.append(msg)
                except Exception as e:
                    log_warning(f"Failed to validate message: {e}")

    # Add user message to run_messages
    if user_message is not None:
        run_messages.user_message = user_message
        run_messages.messages.append(user_message)

    return run_messages


async def aget_run_messages(
    agent: Agent,
    *,
    run_response: RunOutput,
    run_context: RunContext,
    input: Union[str, List, Dict, Message, BaseModel, List[Message]],
    session: AgentSession,
    user_id: Optional[str] = None,
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
    2. Add extra messages to run_messages if provided
    3. Add history to run_messages
    4. Add user message to run_messages (if input is single content)
    5. Add input messages to run_messages if provided (if input is List[Message])

    Returns:
        RunMessages object with the following attributes:
            - system_message: The system message for this run
            - user_message: The user message for this run
            - messages: List of all messages to send to the model

    Typical usage:
    run_messages = await aget_run_messages(
        agent, input=input, session_id=session_id, user_id=user_id, audio=audio, images=images, videos=videos, files=files, **kwargs
    )
    """

    # Initialize the RunMessages object (no media here - that's in RunInput now)
    run_messages = RunMessages()

    # 1. Add system message to run_messages
    system_message = await aget_system_message(
        agent,
        session=session,
        run_context=run_context,
        tools=tools,
        add_session_state_to_context=add_session_state_to_context,
    )
    if system_message is not None:
        run_messages.system_message = system_message
        run_messages.messages.append(system_message)

    # 2. Add extra messages to run_messages if provided
    if agent.additional_input is not None:
        messages_to_add_to_run_response: List[Message] = []
        if run_messages.extra_messages is None:
            run_messages.extra_messages = []

        for _m in agent.additional_input:
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
            agent.system_message_role if agent.system_message_role not in ["user", "assistant", "tool"] else None
        )

        history: List[Message] = session.get_messages(
            last_n_runs=agent.num_history_runs,
            limit=agent.num_history_messages,
            skip_roles=[skip_role] if skip_role else None,
            agent_id=agent.id if agent.team_id is not None else None,
        )

        if len(history) > 0:
            # Create a deep copy of the history messages to avoid modifying the original messages
            history_copy = [deepcopy(msg) for msg in history]

            # Tag each message as coming from history
            for _msg in history_copy:
                _msg.from_history = True

            # Filter tool calls from history if limit is set (before adding to run_messages)
            if agent.max_tool_calls_from_history is not None:
                filter_tool_calls(history_copy, agent.max_tool_calls_from_history)

            log_debug(f"Adding {len(history_copy)} messages from history")

            run_messages.messages += history_copy

    # 4. Add user message to run_messages
    user_message: Optional[Message] = None

    # 4.1 Build user message if input is None, str or list and not a list of Message/dict objects
    if (
        input is None
        or isinstance(input, str)
        or (
            isinstance(input, list)
            and not (
                len(input) > 0
                and (isinstance(input[0], Message) or (isinstance(input[0], dict) and "role" in input[0]))
            )
        )
    ):
        user_message = await aget_user_message(
            agent,
            run_response=run_response,
            run_context=run_context,
            input=input,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            add_dependencies_to_context=add_dependencies_to_context,
            **kwargs,
        )

    # 4.2 If input is provided as a Message, use it directly
    elif isinstance(input, Message):
        user_message = input

    # 4.3 If input is provided as a dict, try to validate it as a Message
    elif isinstance(input, dict):
        try:
            if agent.input_schema and is_typed_dict(agent.input_schema):
                import json

                content = json.dumps(input, indent=2, ensure_ascii=False)
                user_message = Message(role=agent.user_message_role, content=content)
            else:
                user_message = Message.model_validate(input)
        except Exception as e:
            log_warning(f"Failed to validate message: {e}")

    # 4.4 If input is provided as a BaseModel, convert it to a Message
    elif isinstance(input, BaseModel):
        try:
            # Create a user message with the BaseModel content
            content = input.model_dump_json(indent=2, exclude_none=True)
            user_message = Message(role=agent.user_message_role, content=content)
        except Exception as e:
            log_warning(f"Failed to convert BaseModel to message: {e}")

    # 5. Add input messages to run_messages if provided (List[Message] or List[Dict])
    if (
        isinstance(input, list)
        and len(input) > 0
        and (isinstance(input[0], Message) or (isinstance(input[0], dict) and "role" in input[0]))
    ):
        for _m in input:
            if isinstance(_m, Message):
                run_messages.messages.append(_m)
                if run_messages.extra_messages is None:
                    run_messages.extra_messages = []
                run_messages.extra_messages.append(_m)
            elif isinstance(_m, dict):
                try:
                    msg = Message.model_validate(_m)
                    run_messages.messages.append(msg)
                    if run_messages.extra_messages is None:
                        run_messages.extra_messages = []
                    run_messages.extra_messages.append(msg)
                except Exception as e:
                    log_warning(f"Failed to validate message: {e}")

    # Add user message to run_messages
    if user_message is not None:
        run_messages.user_message = user_message
        run_messages.messages.append(user_message)

    return run_messages


def get_continue_run_messages(
    agent: Agent,
    input: List[Message],
) -> RunMessages:
    """This function returns a RunMessages object with the following attributes:
        - system_message: The system message for this run
        - user_message: The user message for this run
        - messages: List of messages to send to the model

    It continues from a previous run and completes a tool call that was paused.
    """

    # Initialize the RunMessages object
    run_messages = RunMessages()

    # Extract most recent user message from messages as the original user message
    user_message = None
    for msg in reversed(input):
        if msg.role == agent.user_message_role:
            user_message = msg
            break

    # Extract system message from messages
    system_message = None
    for msg in input:
        if msg.role == agent.system_message_role:
            system_message = msg
            break

    run_messages.system_message = system_message
    run_messages.user_message = user_message
    run_messages.messages = input

    return run_messages


# ---------------------------------------------------------------------------
# Parser / output model messages
# ---------------------------------------------------------------------------


def get_messages_for_parser_model(
    agent: Agent,
    model_response: ModelResponse,
    response_format: Optional[Union[Dict, Type[BaseModel]]],
    run_context: Optional[RunContext] = None,
) -> List[Message]:
    """Get the messages for the parser model."""
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    system_content = (
        agent.parser_model_prompt
        if agent.parser_model_prompt is not None
        else "You are tasked with creating a structured output from the provided user message."
    )

    if response_format == {"type": "json_object"} and output_schema is not None:
        system_content += f"{get_json_output_prompt(output_schema)}"  # type: ignore

    return [
        Message(role="system", content=system_content),
        Message(role="user", content=model_response.content),
    ]


def get_messages_for_parser_model_stream(
    agent: Agent,
    run_response: RunOutput,
    response_format: Optional[Union[Dict, Type[BaseModel]]],
    run_context: Optional[RunContext] = None,
) -> List[Message]:
    """Get the messages for the parser model."""
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    system_content = (
        agent.parser_model_prompt
        if agent.parser_model_prompt is not None
        else "You are tasked with creating a structured output from the provided data."
    )

    if response_format == {"type": "json_object"} and output_schema is not None:
        system_content += f"{get_json_output_prompt(output_schema)}"  # type: ignore

    return [
        Message(role="system", content=system_content),
        Message(role="user", content=run_response.content),
    ]


def get_messages_for_output_model(agent: Agent, messages: List[Message]) -> List[Message]:
    """Get the messages for the output model."""

    if agent.output_model_prompt is not None:
        system_message_exists = False
        for message in messages:
            if message.role == "system":
                system_message_exists = True
                message.content = agent.output_model_prompt
                break
        if not system_message_exists:
            messages.insert(0, Message(role="system", content=agent.output_model_prompt))

    # Remove the last assistant message from the messages list
    messages.pop(-1)

    return messages


# ---------------------------------------------------------------------------
# Knowledge retrieval
# ---------------------------------------------------------------------------


def get_relevant_docs_from_knowledge(
    agent: Agent,
    query: str,
    num_documents: Optional[int] = None,
    filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    validate_filters: bool = False,
    run_context: Optional[RunContext] = None,
    **kwargs: Any,
) -> Optional[List[Union[Dict[str, Any], str]]]:
    """Get relevant docs from the knowledge base to answer a query.

    Args:
        agent: The Agent instance.
        query (str): The query to search for.
        num_documents (Optional[int]): Number of documents to return.
        filters (Optional[Dict[str, Any]]): Filters to apply to the search.
        validate_filters (bool): Whether to validate the filters against known valid filter keys.
        run_context (Optional[RunContext]): Runtime context containing dependencies and other context.
        **kwargs: Additional keyword arguments.

    Returns:
        Optional[List[Dict[str, Any]]]: List of relevant document dicts.
    """
    from agno.knowledge.document import Document

    # Extract dependencies from run_context if available
    dependencies = run_context.dependencies if run_context else None

    resolved_knowledge = _get_resolved_knowledge(agent, run_context)

    if num_documents is None and resolved_knowledge is not None:
        num_documents = getattr(resolved_knowledge, "max_results", None)
    # Validate the filters against known valid filter keys
    if resolved_knowledge is not None and filters is not None:
        if validate_filters:
            valid_filters, invalid_keys = resolved_knowledge.validate_filters(filters)  # type: ignore

            # Warn about invalid filter keys
            if invalid_keys:
                # type: ignore
                log_warning(f"Invalid filter keys provided: {invalid_keys}. These filters will be ignored.")

                # Only use valid filters
                filters = valid_filters
                if not filters:
                    log_warning("No valid filters remain after validation. Search will proceed without filters.")

            if invalid_keys == [] and valid_filters == {}:
                log_warning("No valid filters provided. Search will proceed without filters.")
                filters = None

    if agent.knowledge_retriever is not None and callable(agent.knowledge_retriever):
        from inspect import signature

        try:
            sig = signature(agent.knowledge_retriever)
            knowledge_retriever_kwargs: Dict[str, Any] = {}
            if "agent" in sig.parameters:
                knowledge_retriever_kwargs = {"agent": agent}
            if "filters" in sig.parameters:
                knowledge_retriever_kwargs["filters"] = filters
            if "run_context" in sig.parameters:
                knowledge_retriever_kwargs["run_context"] = run_context
            elif "dependencies" in sig.parameters:
                # Backward compatibility: support dependencies parameter
                knowledge_retriever_kwargs["dependencies"] = dependencies
            knowledge_retriever_kwargs.update({"query": query, "num_documents": num_documents, **kwargs})
            return agent.knowledge_retriever(**knowledge_retriever_kwargs)
        except Exception as e:
            log_warning(f"Knowledge retriever failed: {e}")
            raise e

    # Use knowledge protocol's retrieve method
    try:
        if resolved_knowledge is None:
            return None

        # Use protocol retrieve() method if available
        retrieve_fn = getattr(resolved_knowledge, "retrieve", None)
        if not callable(retrieve_fn):
            log_debug("Knowledge does not implement retrieve()")
            return None

        if num_documents is None:
            num_documents = getattr(resolved_knowledge, "max_results", 10)

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
    agent: Agent,
    query: str,
    num_documents: Optional[int] = None,
    filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    validate_filters: bool = False,
    run_context: Optional[RunContext] = None,
    **kwargs: Any,
) -> Optional[List[Union[Dict[str, Any], str]]]:
    """Get relevant documents from knowledge base asynchronously."""
    from agno.knowledge.document import Document

    # Extract dependencies from run_context if available
    dependencies = run_context.dependencies if run_context else None

    resolved_knowledge = _get_resolved_knowledge(agent, run_context)

    if num_documents is None and resolved_knowledge is not None:
        num_documents = getattr(resolved_knowledge, "max_results", None)

    # Validate the filters against known valid filter keys
    if resolved_knowledge is not None and filters is not None:
        if validate_filters:
            valid_filters, invalid_keys = await resolved_knowledge.avalidate_filters(filters)  # type: ignore

            # Warn about invalid filter keys
            if invalid_keys:  # type: ignore
                log_warning(f"Invalid filter keys provided: {invalid_keys}. These filters will be ignored.")

                # Only use valid filters
                filters = valid_filters
                if not filters:
                    log_warning("No valid filters remain after validation. Search will proceed without filters.")

            if invalid_keys == [] and valid_filters == {}:
                log_warning("No valid filters provided. Search will proceed without filters.")
                filters = None

    if agent.knowledge_retriever is not None and callable(agent.knowledge_retriever):
        from inspect import isawaitable, signature

        try:
            sig = signature(agent.knowledge_retriever)
            knowledge_retriever_kwargs: Dict[str, Any] = {}
            if "agent" in sig.parameters:
                knowledge_retriever_kwargs = {"agent": agent}
            if "filters" in sig.parameters:
                knowledge_retriever_kwargs["filters"] = filters
            if "run_context" in sig.parameters:
                knowledge_retriever_kwargs["run_context"] = run_context
            elif "dependencies" in sig.parameters:
                # Backward compatibility: support dependencies parameter
                knowledge_retriever_kwargs["dependencies"] = dependencies
            knowledge_retriever_kwargs.update({"query": query, "num_documents": num_documents, **kwargs})
            result = agent.knowledge_retriever(**knowledge_retriever_kwargs)

            if isawaitable(result):
                result = await result

            return result
        except Exception as e:
            log_warning(f"Knowledge retriever failed: {e}")
            raise e

    # Use knowledge protocol's retrieve method
    try:
        if resolved_knowledge is None:
            return None

        # Use protocol aretrieve() or retrieve() method if available
        aretrieve_fn = getattr(resolved_knowledge, "aretrieve", None)
        retrieve_fn = getattr(resolved_knowledge, "retrieve", None)

        if not callable(aretrieve_fn) and not callable(retrieve_fn):
            log_debug("Knowledge does not implement retrieve()")
            return None

        if num_documents is None:
            num_documents = getattr(resolved_knowledge, "max_results", 10)

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
