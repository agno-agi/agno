from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel

from agno.agent import Agent
from agno.models.message import Message
from agno.os.schema import ModelResponse
from agno.os.utils import (
    format_tools,
)
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.utils.agent import aexecute_instructions, aexecute_system_message


class AgentResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    db_id: Optional[str] = None
    description: Optional[str] = None
    role: Optional[str] = None
    model: Optional[ModelResponse] = None
    tools: Optional[Dict[str, Any]] = None
    sessions: Optional[Dict[str, Any]] = None
    knowledge: Optional[Dict[str, Any]] = None
    memory: Optional[Dict[str, Any]] = None
    reasoning: Optional[Dict[str, Any]] = None
    default_tools: Optional[Dict[str, Any]] = None
    system_message: Optional[Dict[str, Any]] = None
    extra_messages: Optional[Dict[str, Any]] = None
    response_settings: Optional[Dict[str, Any]] = None
    introduction: Optional[str] = None
    streaming: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    input_schema: Optional[Dict[str, Any]] = None

    @classmethod
    async def from_agent(cls, agent: Agent) -> "AgentResponse":
        def filter_meaningful_config(d: Dict[str, Any], defaults: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Filter out fields that match their default values, keeping only meaningful user configurations"""
            filtered = {}
            for key, value in d.items():
                if value is None:
                    continue
                # Skip if value matches the default exactly
                if key in defaults and value == defaults[key]:
                    continue
                # Keep non-default values
                filtered[key] = value
            return filtered if filtered else None

        # Define default values for filtering
        agent_defaults = {
            # Sessions defaults
            "add_history_to_context": False,
            "num_history_runs": 3,
            "enable_session_summaries": False,
            "search_session_history": False,
            "cache_session": False,
            # Knowledge defaults
            "add_references": False,
            "references_format": "json",
            "enable_agentic_knowledge_filters": False,
            # Memory defaults
            "enable_agentic_memory": False,
            "update_memory_on_run": False,
            # Reasoning defaults
            "reasoning": False,
            "reasoning_min_steps": 1,
            "reasoning_max_steps": 10,
            # Default tools defaults
            "read_chat_history": False,
            "search_knowledge": True,
            "update_knowledge": False,
            "read_tool_call_history": False,
            # System message defaults
            "system_message_role": "system",
            "build_context": True,
            "markdown": False,
            "add_name_to_context": False,
            "add_datetime_to_context": False,
            "add_location_to_context": False,
            "resolve_in_context": True,
            # Extra messages defaults
            "user_message_role": "user",
            "build_user_context": True,
            # Response settings defaults
            "retries": 0,
            "delay_between_retries": 1,
            "exponential_backoff": False,
            "parse_response": True,
            "use_json_mode": False,
            # Streaming defaults
            "stream_events": False,
        }

        session_id = str(uuid4())
        run_id = str(uuid4())
        agent_tools = await agent.aget_tools(
            session=AgentSession(session_id=session_id, session_data={}),
            run_response=RunOutput(run_id=run_id, session_id=session_id),
            run_context=RunContext(run_id=run_id, session_id=session_id, user_id=agent.user_id),
            check_mcp_tools=False,
        )
        formatted_tools = format_tools(agent_tools) if agent_tools else None

        additional_input = agent.additional_input
        if additional_input and isinstance(additional_input[0], Message):
            additional_input = [message.to_dict() for message in additional_input]  # type: ignore

        input_schema_dict = None
        if agent.input_schema is not None:
            if isinstance(agent.input_schema, dict):
                input_schema_dict = agent.input_schema
            else:
                try:
                    input_schema_dict = agent.input_schema.model_json_schema()
                except Exception:
                    pass

        # Build model only if it has at least one non-null field
        model_name = agent.model.name if (agent.model and agent.model.name) else None
        model_provider = agent.model.provider if (agent.model and agent.model.provider) else None
        model_id = agent.model.id if (agent.model and agent.model.id) else None
        _agent_model_data: Dict[str, Any] = {}
        if model_name is not None:
            _agent_model_data["name"] = model_name
        if model_id is not None:
            _agent_model_data["model"] = model_id
        if model_provider is not None:
            _agent_model_data["provider"] = model_provider

        session_table = agent.db.session_table_name if agent.db else None
        knowledge_table = agent.db.knowledge_table_name if agent.db and agent.knowledge else None

        tools_info = {
            "tools": formatted_tools,
            "tool_call_limit": agent.tool_call_limit,
            "tool_choice": agent.tool_choice,
        }

        sessions_info = {
            "session_table": session_table,
            "add_history_to_context": agent.add_history_to_context,
            "enable_session_summaries": agent.enable_session_summaries,
            "num_history_runs": agent.num_history_runs,
            "search_session_history": agent.search_session_history,
            "num_history_sessions": agent.num_history_sessions,
            "cache_session": agent.cache_session,
        }

        contents_db = getattr(agent.knowledge, "contents_db", None) if agent.knowledge else None
        knowledge_info = {
            "db_id": contents_db.id if contents_db else None,
            "knowledge_table": knowledge_table,
            "enable_agentic_knowledge_filters": agent.enable_agentic_knowledge_filters,
            "knowledge_filters": agent.knowledge_filters,
            "references_format": agent.references_format,
        }

        memory_info: Optional[Dict[str, Any]] = None
        if agent.memory_manager is not None:
            memory_info = {
                "enable_agentic_memory": agent.enable_agentic_memory,
                "update_memory_on_run": agent.update_memory_on_run,
                "enable_user_memories": agent.enable_user_memories,  # Soon to be deprecated. Use update_memory_on_run
                "metadata": agent.metadata,
                "memory_table": agent.db.memory_table_name if agent.db and agent.update_memory_on_run else None,
            }

            if agent.memory_manager.model is not None:
                memory_info["model"] = ModelResponse(
                    name=agent.memory_manager.model.name,
                    model=agent.memory_manager.model.id,
                    provider=agent.memory_manager.model.provider,
                ).model_dump()

        reasoning_info: Dict[str, Any] = {
            "reasoning": agent.reasoning,
            "reasoning_agent_id": agent.reasoning_agent.id if agent.reasoning_agent else None,
            "reasoning_min_steps": agent.reasoning_min_steps,
            "reasoning_max_steps": agent.reasoning_max_steps,
        }

        if agent.reasoning_model:
            reasoning_info["reasoning_model"] = ModelResponse(
                name=agent.reasoning_model.name,
                model=agent.reasoning_model.id,
                provider=agent.reasoning_model.provider,
            ).model_dump()

        default_tools_info = {
            "read_chat_history": agent.read_chat_history,
            "search_knowledge": agent.search_knowledge,
            "update_knowledge": agent.update_knowledge,
            "read_tool_call_history": agent.read_tool_call_history,
        }

        instructions = agent.instructions if agent.instructions else None
        if instructions and callable(instructions):
            instructions = await aexecute_instructions(instructions=instructions, agent=agent)

        system_message = agent.system_message if agent.system_message else None
        if system_message and callable(system_message):
            system_message = await aexecute_system_message(system_message=system_message, agent=agent)

        system_message_info = {
            "system_message": str(system_message) if system_message else None,
            "system_message_role": agent.system_message_role,
            "build_context": agent.build_context,
            "description": agent.description,
            "instructions": instructions,
            "expected_output": agent.expected_output,
            "additional_context": agent.additional_context,
            "markdown": agent.markdown,
            "add_name_to_context": agent.add_name_to_context,
            "add_datetime_to_context": agent.add_datetime_to_context,
            "add_location_to_context": agent.add_location_to_context,
            "timezone_identifier": agent.timezone_identifier,
            "resolve_in_context": agent.resolve_in_context,
        }

        extra_messages_info = {
            "additional_input": additional_input,  # type: ignore
            "user_message_role": agent.user_message_role,
            "build_user_context": agent.build_user_context,
        }

        # Handle output_schema name for both Pydantic models and JSON schemas
        output_schema_name = None
        if agent.output_schema is not None:
            if isinstance(agent.output_schema, dict):
                if "json_schema" in agent.output_schema:
                    output_schema_name = agent.output_schema["json_schema"].get("name", "JSONSchema")
                elif "schema" in agent.output_schema and isinstance(agent.output_schema["schema"], dict):
                    output_schema_name = agent.output_schema["schema"].get("title", "JSONSchema")
                else:
                    output_schema_name = agent.output_schema.get("title", "JSONSchema")
            elif hasattr(agent.output_schema, "__name__"):
                output_schema_name = agent.output_schema.__name__

        response_settings_info: Dict[str, Any] = {
            "retries": agent.retries,
            "delay_between_retries": agent.delay_between_retries,
            "exponential_backoff": agent.exponential_backoff,
            "output_schema_name": output_schema_name,
            "parser_model_prompt": agent.parser_model_prompt,
            "parse_response": agent.parse_response,
            "structured_outputs": agent.structured_outputs,
            "use_json_mode": agent.use_json_mode,
            "save_response_to_file": agent.save_response_to_file,
        }

        if agent.parser_model:
            response_settings_info["parser_model"] = ModelResponse(
                name=agent.parser_model.name,
                model=agent.parser_model.id,
                provider=agent.parser_model.provider,
            ).model_dump()

        streaming_info = {
            "stream": agent.stream,
            "stream_events": agent.stream_events,
        }

        return AgentResponse(
            id=agent.id,
            name=agent.name,
            db_id=agent.db.id if agent.db else None,
            description=agent.description,
            role=agent.role,
            model=ModelResponse(**_agent_model_data) if _agent_model_data else None,
            tools=filter_meaningful_config(tools_info, {}),
            sessions=filter_meaningful_config(sessions_info, agent_defaults),
            knowledge=filter_meaningful_config(knowledge_info, agent_defaults),
            memory=filter_meaningful_config(memory_info, agent_defaults) if memory_info else None,
            reasoning=filter_meaningful_config(reasoning_info, agent_defaults),
            default_tools=filter_meaningful_config(default_tools_info, agent_defaults),
            system_message=filter_meaningful_config(system_message_info, agent_defaults),
            extra_messages=filter_meaningful_config(extra_messages_info, agent_defaults),
            response_settings=filter_meaningful_config(response_settings_info, agent_defaults),
            streaming=filter_meaningful_config(streaming_info, agent_defaults),
            introduction=agent.introduction,
            metadata=agent.metadata,
            input_schema=input_schema_dict,
        )
