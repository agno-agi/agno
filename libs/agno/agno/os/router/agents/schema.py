from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, model_serializer

from agno.agent import Agent, RemoteAgent
from agno.models.message import Message
from agno.os.router.schema import (
    DatabaseConfigResponse,
    HookResponse,
    MessageResponse,
    ModelResponse,
    TableNameResponse,
    ToolDefinitionResponse,
)
from agno.os.utils import (
    filter_meaningful_config,
    format_tools,
    get_agent_input_schema_dict,
    remove_none_values,
    to_utc_datetime,
)
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.utils.agent import aexecute_instructions, aexecute_system_message


class AgentMinimalResponse(BaseModel):
    id: Optional[str] = Field(None, description="Unique identifier for the agent")
    name: Optional[str] = Field(None, description="Name of the agent")
    description: Optional[str] = Field(None, description="Description of the agent")
    db_id: Optional[str] = Field(None, description="Database identifier")

    # TODO: Add more minimal fields as needed.

    @classmethod
    def from_agent(cls, agent: Union[Agent, RemoteAgent]) -> "AgentMinimalResponse":
        return cls(id=agent.id, name=agent.name, description=agent.description, db_id=agent.db.id if agent.db else None)


class AgentResponse(BaseModel):
    id: str = Field(..., description="The ID of the agent")
    name: Optional[str] = Field(None, description="The name of the agent")
    description: Optional[str] = Field(None, description="The description of the agent")
    model: Optional[ModelResponse] = Field(None, description="The model of the agent")
    tools: Optional[List[ToolDefinitionResponse]] = Field([], description="The tools of the agent")
    attributes: Optional[Dict[str, Any]] = Field({}, description="The attributes of the agent")
    database: Optional[DatabaseConfigResponse] = Field(None, description="The database of the agent")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="The name of the output schema of the agent")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="The name of the input schema of the agent")
    pre_hooks: Optional[List[HookResponse]] = Field(None, description="The pre-hooks of the agent")
    post_hooks: Optional[List[HookResponse]] = Field(None, description="The post-hooks of the agent")
    additional_input: Optional[List[MessageResponse]] = Field(None, description="The additional input of the agent")
    metadata: Optional[Dict[str, Any]] = Field(None, description="The metadata of the agent")

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
            "search_session_history": False,
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

    @classmethod
    async def from_agent(cls, agent: Agent) -> "AgentResponse":
        # Define default values for filtering
        agent_defaults = cls.get_default_values()

        session_id = str(uuid4())
        run_id = str(uuid4())
        agent_tools = await agent.aget_tools(
            session=AgentSession(session_id=session_id, session_data={}),
            run_response=RunOutput(run_id=run_id, session_id=session_id),
            run_context=RunContext(run_id=run_id, session_id=session_id, user_id=agent.user_id),
            check_mcp_tools=False,
        )
        formatted_tools = format_tools(agent_tools) if agent_tools else None

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
        model = ModelResponse(**_agent_model_data) if _agent_model_data else None

        database: Optional[DatabaseConfigResponse] = None
        if agent.db:
            table_names, config = agent.db.to_config()
            database = DatabaseConfigResponse(
                id=agent.db.id,
                table_names=[TableNameResponse(type=type, name=name) for type, name in table_names],
                config=config,
            )

        additional_input = agent.additional_input
        if additional_input and isinstance(additional_input[0], Message):
            additional_input = [
                MessageResponse(
                    role=message.role,  # type: ignore
                    content=message.content,  # type: ignore
                    created_at=to_utc_datetime(message.created_at),  # type: ignore
                )
                for message in additional_input
            ]

        memory_info: Dict[str, Any] = {
            "enable_agentic_memory": agent.enable_agentic_memory,
            "enable_user_memories": agent.enable_user_memories,
        }
        if agent.memory_manager is not None and agent.memory_manager.model is not None:
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

        instructions = agent.instructions if agent.instructions else None
        if instructions and callable(instructions):
            instructions = await aexecute_instructions(instructions=instructions, agent=agent)

        system_message = agent.system_message if agent.system_message else None
        if system_message and callable(system_message):
            system_message = await aexecute_system_message(system_message=system_message, agent=agent)

        system_context_info = {
            "system_message": str(system_message) if system_message else None,
            "system_message_role": agent.system_message_role,
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

        execution_configuration = {
            "stream": agent.stream,
            "stream_events": agent.stream_events,
            "retries": agent.retries,
            "delay_between_retries": agent.delay_between_retries,
            "exponential_backoff": agent.exponential_backoff,
            "parser_model": ModelResponse(
                name=agent.parser_model.name,
                model=agent.parser_model.id,
                provider=agent.parser_model.provider,
            ).model_dump()
            if agent.parser_model
            else None,
            "output_model": ModelResponse(
                name=agent.output_model.name,
                model=agent.output_model.id,
                provider=agent.output_model.provider,
            ).model_dump()
            if agent.output_model
            else None,
            "parse_response": agent.parse_response,
            "structured_outputs": agent.structured_outputs,
            "use_json_mode": agent.use_json_mode,
            "save_response_to_file": agent.save_response_to_file,
        }

        # Extract pre/post hooks information
        pre_hooks_response: Optional[List[HookResponse]] = None
        if agent.pre_hooks:
            pre_hooks_response = [HookResponse.from_hook(hook) for hook in agent.pre_hooks]

        post_hooks_response: Optional[List[HookResponse]] = None
        if agent.post_hooks:
            post_hooks_response = [HookResponse.from_hook(hook) for hook in agent.post_hooks]

        # TODO: Review what works on the FE and looks sensible.
        attributes = {
            "system_context": system_context_info,
            "introduction": agent.introduction,
            "tools": {
                "tool_call_limit": agent.tool_call_limit,
                "tool_choice": agent.tool_choice,
                "built_in_tools": {
                    "read_chat_history": agent.read_chat_history,
                    "search_knowledge": agent.search_knowledge,
                    "update_knowledge": agent.update_knowledge,
                    "read_tool_call_history": agent.read_tool_call_history,
                },
            },
            "memory": memory_info,
            "history": {
                "add_history_to_context": agent.add_history_to_context,
                "enable_session_summaries": agent.enable_session_summaries,
                "num_history_runs": agent.num_history_runs,
                "search_session_history": agent.search_session_history,
                "num_history_sessions": agent.num_history_sessions,
                "cache_session": agent.cache_session,
            },
            "knowledge": {
                "enable_agentic_knowledge_filters": agent.enable_agentic_knowledge_filters,
                "knowledge_filters": agent.knowledge_filters,
                "references_format": agent.references_format,
            },
            "reasoning": reasoning_info,
            "execution": execution_configuration,
        }
        # Handle output_schema name for both Pydantic models and JSON schemas
        output_schema = None
        if agent.output_schema is not None:
            if isinstance(agent.output_schema, dict):
                if "json_schema" in agent.output_schema:
                    output_schema = agent.output_schema["json_schema"]
                elif "schema" in agent.output_schema and isinstance(agent.output_schema["schema"], dict):
                    output_schema = agent.output_schema["schema"]
                else:
                    output_schema = agent.output_schema
            elif hasattr(agent.output_schema, "__name__"):
                output_schema = agent.output_schema.model_json_schema()
        input_schema = get_agent_input_schema_dict(agent)

        return AgentResponse(
            id=agent.id,
            name=agent.name,
            model=model,
            tools=formatted_tools,
            database=database,
            output_schema=output_schema,
            input_schema=input_schema,
            pre_hooks=pre_hooks_response,
            post_hooks=post_hooks_response,
            additional_input=additional_input,
            attributes=filter_meaningful_config(attributes, agent_defaults),
            metadata=agent.metadata,
        )
