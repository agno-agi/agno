from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.agent import Agent
from agno.os.routers.agents.schema import AgentResponse
from agno.os.schema import ModelResponse
from agno.os.utils import (
    format_team_tools,
)
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team.team import Team
from agno.utils.agent import aexecute_instructions, aexecute_system_message


class TeamResponse(BaseModel):
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
    response_settings: Optional[Dict[str, Any]] = None
    introduction: Optional[str] = None
    streaming: Optional[Dict[str, Any]] = None
    members: Optional[List[Union[AgentResponse, "TeamResponse"]]] = None
    metadata: Optional[Dict[str, Any]] = None
    input_schema: Optional[Dict[str, Any]] = None

    @classmethod
    async def from_team(cls, team: Team) -> "TeamResponse":
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

        # Define default values for filtering (similar to agent defaults)
        team_defaults = {
            # Sessions defaults
            "add_history_to_context": False,
            "num_history_runs": 3,
            "enable_session_summaries": False,
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
            "search_knowledge": True,
            "read_chat_history": False,
            "get_member_information_tool": False,
            # System message defaults
            "system_message_role": "system",
            "markdown": False,
            "add_datetime_to_context": False,
            "add_location_to_context": False,
            "resolve_in_context": True,
            # Response settings defaults
            "parse_response": True,
            "use_json_mode": False,
            # Streaming defaults
            "stream_events": False,
            "stream_member_events": False,
        }

        run_id = str(uuid4())
        session_id = str(uuid4())
        _tools = team._determine_tools_for_model(
            model=team.model,  # type: ignore
            session=TeamSession(session_id=session_id, session_data={}),
            run_response=TeamRunOutput(run_id=run_id),
            run_context=RunContext(run_id=run_id, session_id=session_id, session_state={}),
            async_mode=True,
            team_run_context={},
            check_mcp_tools=False,
        )
        team_tools = _tools
        formatted_tools = format_team_tools(team_tools) if team_tools else None

        input_schema_dict = None
        if team.input_schema is not None:
            try:
                input_schema_dict = team.input_schema.model_json_schema()
            except Exception:
                pass

        model_name = team.model.name or team.model.__class__.__name__ if team.model else None
        model_provider = team.model.provider or team.model.__class__.__name__ if team.model else ""
        model_id = team.model.id if team.model else None

        if model_provider and model_id:
            model_provider = f"{model_provider} {model_id}"
        elif model_name and model_id:
            model_provider = f"{model_name} {model_id}"
        elif model_id:
            model_provider = model_id

        session_table = team.db.session_table_name if team.db else None
        knowledge_table = team.db.knowledge_table_name if team.db and team.knowledge else None

        tools_info = {
            "tools": formatted_tools,
            "tool_call_limit": team.tool_call_limit,
            "tool_choice": team.tool_choice,
        }

        sessions_info = {
            "session_table": session_table,
            "add_history_to_context": team.add_history_to_context,
            "enable_session_summaries": team.enable_session_summaries,
            "num_history_runs": team.num_history_runs,
            "cache_session": team.cache_session,
        }

        contents_db = getattr(team.knowledge, "contents_db", None) if team.knowledge else None
        knowledge_info = {
            "db_id": contents_db.id if contents_db else None,
            "knowledge_table": knowledge_table,
            "enable_agentic_knowledge_filters": team.enable_agentic_knowledge_filters,
            "knowledge_filters": team.knowledge_filters,
            "references_format": team.references_format,
        }

        memory_info: Optional[Dict[str, Any]] = None
        if team.memory_manager is not None:
            memory_info = {
                "enable_agentic_memory": team.enable_agentic_memory,
                "update_memory_on_run": team.update_memory_on_run,
                "enable_user_memories": team.enable_user_memories,  # Soon to be deprecated. Use update_memory_on_run
                "metadata": team.metadata,
                "memory_table": team.db.memory_table_name if team.db and team.update_memory_on_run else None,
            }

            if team.memory_manager.model is not None:
                memory_info["model"] = ModelResponse(
                    name=team.memory_manager.model.name,
                    model=team.memory_manager.model.id,
                    provider=team.memory_manager.model.provider,
                ).model_dump()

        reasoning_info: Dict[str, Any] = {
            "reasoning": team.reasoning,
            "reasoning_agent_id": team.reasoning_agent.id if team.reasoning_agent else None,
            "reasoning_min_steps": team.reasoning_min_steps,
            "reasoning_max_steps": team.reasoning_max_steps,
        }

        if team.reasoning_model:
            reasoning_info["reasoning_model"] = ModelResponse(
                name=team.reasoning_model.name,
                model=team.reasoning_model.id,
                provider=team.reasoning_model.provider,
            ).model_dump()

        default_tools_info = {
            "search_knowledge": team.search_knowledge,
            "read_chat_history": team.read_chat_history,
            "get_member_information_tool": team.get_member_information_tool,
        }

        team_instructions = team.instructions if team.instructions else None
        if team_instructions and callable(team_instructions):
            team_instructions = await aexecute_instructions(instructions=team_instructions, agent=team, team=team)

        team_system_message = team.system_message if team.system_message else None
        if team_system_message and callable(team_system_message):
            team_system_message = await aexecute_system_message(
                system_message=team_system_message, agent=team, team=team
            )

        system_message_info = {
            "system_message": team_system_message,
            "system_message_role": team.system_message_role,
            "description": team.description,
            "instructions": team_instructions,
            "expected_output": team.expected_output,
            "additional_context": team.additional_context,
            "markdown": team.markdown,
            "add_datetime_to_context": team.add_datetime_to_context,
            "add_location_to_context": team.add_location_to_context,
            "resolve_in_context": team.resolve_in_context,
        }

        # Handle output_schema name for both Pydantic models and JSON schemas
        output_schema_name = None
        if team.output_schema is not None:
            if isinstance(team.output_schema, dict):
                if "json_schema" in team.output_schema:
                    output_schema_name = team.output_schema["json_schema"].get("name", "JSONSchema")
                elif "schema" in team.output_schema and isinstance(team.output_schema["schema"], dict):
                    output_schema_name = team.output_schema["schema"].get("title", "JSONSchema")
                else:
                    output_schema_name = team.output_schema.get("title", "JSONSchema")
            elif hasattr(team.output_schema, "__name__"):
                output_schema_name = team.output_schema.__name__

        response_settings_info: Dict[str, Any] = {
            "output_schema_name": output_schema_name,
            "parser_model_prompt": team.parser_model_prompt,
            "parse_response": team.parse_response,
            "use_json_mode": team.use_json_mode,
        }

        if team.parser_model:
            response_settings_info["parser_model"] = ModelResponse(
                name=team.parser_model.name,
                model=team.parser_model.id,
                provider=team.parser_model.provider,
            ).model_dump()

        streaming_info = {
            "stream": team.stream,
            "stream_events": team.stream_events,
            "stream_member_events": team.stream_member_events,
        }

        # Build team model only if it has at least one non-null field
        _team_model_data: Dict[str, Any] = {}
        if team.model and team.model.name is not None:
            _team_model_data["name"] = team.model.name
        if team.model and team.model.id is not None:
            _team_model_data["model"] = team.model.id
        if team.model and team.model.provider is not None:
            _team_model_data["provider"] = team.model.provider

        members: List[Union[AgentResponse, TeamResponse]] = []
        for member in team.members if isinstance(team.members, list) else []:
            if isinstance(member, Agent):
                agent_response = await AgentResponse.from_agent(member)
                members.append(agent_response)
            if isinstance(member, Team):
                team_response = await TeamResponse.from_team(member)
                members.append(team_response)

        return TeamResponse(
            id=team.id,
            name=team.name,
            db_id=team.db.id if team.db else None,
            description=team.description,
            role=team.role,
            model=ModelResponse(**_team_model_data) if _team_model_data else None,
            tools=filter_meaningful_config(tools_info, {}),
            sessions=filter_meaningful_config(sessions_info, team_defaults),
            knowledge=filter_meaningful_config(knowledge_info, team_defaults),
            memory=filter_meaningful_config(memory_info, team_defaults) if memory_info else None,
            reasoning=filter_meaningful_config(reasoning_info, team_defaults),
            default_tools=filter_meaningful_config(default_tools_info, team_defaults),
            system_message=filter_meaningful_config(system_message_info, team_defaults),
            response_settings=filter_meaningful_config(response_settings_info, team_defaults),
            introduction=team.introduction,
            streaming=filter_meaningful_config(streaming_info, team_defaults),
            members=members if members else None,
            metadata=team.metadata,
            input_schema=input_schema_dict,
        )
