from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, model_serializer

from agno.agent import Agent
from agno.os.routers.agents.schema import AgentResponse
from agno.os.schema import DatabaseConfigResponse, ModelResponse, ToolDefinitionResponse, filter_meaningful_config
from agno.os.utils import (
    format_team_tools,
    get_team_input_schema_dict,
    remove_none_values,
)
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team.team import Team
from agno.utils.agent import aexecute_instructions, aexecute_system_message


class TeamResponse(BaseModel):
    id: str = Field(..., description="The ID of the team")
    name: Optional[str] = Field(None, description="The name of the team")
    description: Optional[str] = Field(None, description="The description of the team")
    model: Optional[ModelResponse] = Field(None, description="The model of the team")
    tools: Optional[List[ToolDefinitionResponse]] = Field([], description="The tools of the team")
    attributes: Optional[Dict[str, Any]] = Field({}, description="The attributes of the team")
    database: Optional[DatabaseConfigResponse] = Field(None, description="The database of the team")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="The output schema of the team")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="The input schema of the team")
    members: Optional[List[Union[AgentResponse, "TeamResponse"]]] = Field(None, description="The members of the team")
    metadata: Optional[Dict[str, Any]] = Field(None, description="The metadata of the team")

    @model_serializer(mode="wrap")
    def serialize_model(self, handler) -> Dict[str, Any]:
        """Custom serializer that recursively removes None values from nested structures."""
        data = handler(self)
        return remove_none_values(data)

    @staticmethod
    def get_default_values() -> Dict[str, Any]:
        return {
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
            "enable_user_memories": False,
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

    @classmethod
    async def from_team(cls, team: Team) -> "TeamResponse":
        # Define default values for filtering
        team_defaults = cls.get_default_values()

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
        formatted_tools = format_team_tools(_tools) if _tools else None

        # Build model only if it has at least one non-null field
        model_name = team.model.name if (team.model and team.model.name) else None
        model_provider = team.model.provider if (team.model and team.model.provider) else None
        model_id = team.model.id if (team.model and team.model.id) else None
        _team_model_data: Dict[str, Any] = {}
        if model_name is not None:
            _team_model_data["name"] = model_name
        if model_id is not None:
            _team_model_data["model"] = model_id
        if model_provider is not None:
            _team_model_data["provider"] = model_provider
        model = ModelResponse(**_team_model_data) if _team_model_data else None

        database: Optional[DatabaseConfigResponse] = None
        if team.db:
            table_names, config = team.db.to_config()
            database = DatabaseConfigResponse(
                id=team.db.id,
                table_names=table_names,
                config=config,
            )

        memory_info = {
            "enable_agentic_memory": team.enable_agentic_memory,
            "enable_user_memories": team.enable_user_memories,
        }
        if team.memory_manager is not None and team.memory_manager.model is not None:
            memory_info["model"] = ModelResponse(
                name=team.memory_manager.model.name,
                model=team.memory_manager.model.id,
                provider=team.memory_manager.model.provider,
            ).model_dump()

        reasoning_info = {
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

        team_instructions = team.instructions if team.instructions else None
        if team_instructions and callable(team_instructions):
            team_instructions = await aexecute_instructions(instructions=team_instructions, agent=team, team=team)

        team_system_message = team.system_message if team.system_message else None
        if team_system_message and callable(team_system_message):
            team_system_message = await aexecute_system_message(
                system_message=team_system_message, agent=team, team=team
            )

        system_context_info = {
            "system_message": str(team_system_message) if team_system_message else None,
            "system_message_role": team.system_message_role,
            "description": team.description,
            "instructions": team_instructions,
            "expected_output": team.expected_output,
            "additional_context": team.additional_context,
            "markdown": team.markdown,
            "add_datetime_to_context": team.add_datetime_to_context,
            "add_location_to_context": team.add_location_to_context,
            "timezone_identifier": team.timezone_identifier,
            "resolve_in_context": team.resolve_in_context,
        }

        execution_configuration = {
            "stream": team.stream,
            "stream_events": team.stream_events,
            "stream_member_events": team.stream_member_events,
            "parser_model": ModelResponse(
                name=team.parser_model.name,
                model=team.parser_model.id,
                provider=team.parser_model.provider,
            ).model_dump() if team.parser_model else None,
            "parse_response": team.parse_response,
            "use_json_mode": team.use_json_mode,
        }

        attributes = {
            "system_context": system_context_info,
            "introduction": team.introduction,
            "tools": {
                "tool_call_limit": team.tool_call_limit,
                "tool_choice": team.tool_choice,
                "built_in_tools": {
                    "search_knowledge": team.search_knowledge,
                    "read_chat_history": team.read_chat_history,
                    "get_member_information_tool": team.get_member_information_tool,
                },
            },
            "memory": memory_info,
            "history": {
                "add_history_to_context": team.add_history_to_context,
                "enable_session_summaries": team.enable_session_summaries,
                "num_history_runs": team.num_history_runs,
                "cache_session": team.cache_session,
            },
            "knowledge": {
                "enable_agentic_knowledge_filters": team.enable_agentic_knowledge_filters,
                "knowledge_filters": team.knowledge_filters,
                "references_format": team.references_format,
            },
            "reasoning": reasoning_info,
            "execution": execution_configuration,
        }

        # Handle output_schema for both Pydantic models and JSON schemas
        output_schema = None
        if team.output_schema is not None:
            if isinstance(team.output_schema, dict):
                if "json_schema" in team.output_schema:
                    output_schema = team.output_schema["json_schema"]
                elif "schema" in team.output_schema and isinstance(team.output_schema["schema"], dict):
                    output_schema = team.output_schema["schema"]
                else:
                    output_schema = team.output_schema
            elif hasattr(team.output_schema, "__name__"):
                output_schema = team.output_schema.model_json_schema()

        members: List[Union[AgentResponse, TeamResponse]] = []
        for member in team.members:
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
            model=model,
            tools=formatted_tools,
            database=database,
            output_schema=output_schema,
            input_schema=get_team_input_schema_dict(team),
            introduction=team.introduction,
            members=members if members else None,
            attributes=filter_meaningful_config(attributes, team_defaults),
            metadata=team.metadata,
        )
