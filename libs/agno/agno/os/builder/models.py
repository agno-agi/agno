from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class BuilderModelResponse(BaseModel):
    name: Optional[str] = Field(None, description="Name of the model")
    model: Optional[str] = Field(None, description="Model identifier")
    provider: Optional[str] = Field(None, description="Model provider")


class BuilderDatabaseResponse(BaseModel):
    id: str = Field(..., description="Database identifier")
    type: str = Field(..., description="Database type")


class BuilderToolResponse(BaseModel):
    id: str = Field(..., description="Tool identifier")
    name: str = Field(..., description="Name of the tool")
    description: Optional[str] = Field(None, description="Description of the tool")


class BuilderConfigResponse(BaseModel):
    tools: Optional[List[BuilderToolResponse]] = Field(None, description="List of available tools")
    models: Optional[List[BuilderModelResponse]] = Field(None, description="List of available models")
    databases: Optional[List[BuilderDatabaseResponse]] = Field(None, description="List of available databases")


class BuilderAgentRequest(BaseModel):
    name: str = Field(..., description="Name of the agent")
    model: Optional[BuilderModelResponse] = Field(None, description="Model configuration")
    output_model: Optional[BuilderModelResponse] = Field(None, description="Output model configuration")
    description: Optional[str] = Field(None, description="Description of the agent")
    instructions: Optional[str] = Field(None, description="Agent instructions")
    tools: Optional[List[str]] = Field(None, description="List of tool identifiers")
    database_id: Optional[str] = Field(None, description="Database identifier")
    # Agent Capabilities
    add_history_to_context: bool = Field(False, description="Add chat history to context")
    read_chat_history: bool = Field(False, description="Enable tool to read chat history")
    search_knowledge: bool = Field(False, description="Enable knowledge search")
    reasoning: bool = Field(False, description="Enable reasoning")
    # Memory & State
    memory: bool = Field(False, description="Enable persistent memory")
    add_session_state_to_context: bool = Field(False, description="Add session state to context")
    # UX/Display
    markdown: bool = Field(True, description="Enable markdown output")
    show_tool_calls: bool = Field(True, description="Show tool calls in output")
    # Parameters
    tool_call_limit: Optional[int] = Field(None, description="Maximum number of tool calls")
    num_history_runs: int = Field(3, description="Number of history runs to include")
