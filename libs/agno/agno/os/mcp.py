"""Router for MCP interface providing Model Context Protocol endpoints."""

import logging
from typing import TYPE_CHECKING, List, Optional, cast
from uuid import uuid4

from fastmcp import FastMCP
from fastmcp.server.http import (
    StarletteWithLifespan,
)

from agno.db.base import AsyncBaseDb, SessionType
from agno.db.schemas import UserMemory
from agno.os.routers.memory.schemas import (
    UserMemorySchema,
)
from agno.os.schema import (
    AgentSummaryResponse,
    ConfigResponse,
    InterfaceResponse,
    SessionSchema,
    TeamSummaryResponse,
    WorkflowSummaryResponse,
)
from agno.os.utils import (
    get_agent_by_id,
    get_db,
    get_team_by_id,
    get_workflow_by_id,
)
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput

if TYPE_CHECKING:
    from agno.os.app import AgentOS

logger = logging.getLogger(__name__)


def get_mcp_server(
    os: "AgentOS",
) -> StarletteWithLifespan:
    """Attach MCP routes to the provided router."""

    # Create an MCP server
    mcp = FastMCP(os.name or "AgentOS")

    @mcp.tool(
        name="get_agentos_config",
        description="Get the configuration of the AgentOS",
        tags={"core"},
        output_schema=ConfigResponse.model_json_schema(),
    )  # type: ignore
    async def config() -> ConfigResponse:
        return ConfigResponse(
            os_id=os.id or "AgentOS",
            description=os.description,
            available_models=os.config.available_models if os.config else [],
            databases=[db.id for db in os.dbs.values()],
            chat=os.config.chat if os.config else None,
            session=os._get_session_config(),
            memory=os._get_memory_config(),
            knowledge=os._get_knowledge_config(),
            evals=os._get_evals_config(),
            metrics=os._get_metrics_config(),
            agents=[AgentSummaryResponse.from_agent(agent) for agent in os.agents] if os.agents else [],
            teams=[TeamSummaryResponse.from_team(team) for team in os.teams] if os.teams else [],
            workflows=[WorkflowSummaryResponse.from_workflow(w) for w in os.workflows] if os.workflows else [],
            interfaces=[
                InterfaceResponse(type=interface.type, version=interface.version, route=interface.prefix)
                for interface in os.interfaces
            ],
        )

    @mcp.tool(name="run_agent", description="Run an agent", tags={"core"})  # type: ignore
    async def run_agent(agent_id: str, message: str) -> RunOutput:
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise Exception(f"Agent {agent_id} not found")
        return await agent.arun(message)

    @mcp.tool(name="run_team", description="Run a team", tags={"core"})  # type: ignore
    async def run_team(team_id: str, message: str) -> TeamRunOutput:
        team = get_team_by_id(team_id, os.teams)
        if team is None:
            raise Exception(f"Team {team_id} not found")
        return await team.arun(message)

    @mcp.tool(name="run_workflow", description="Run a workflow", tags={"core"})  # type: ignore
    async def run_workflow(workflow_id: str, message: str) -> WorkflowRunOutput:
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise Exception(f"Workflow {workflow_id} not found")
        return await workflow.arun(message)

    # Session Management Tools
    @mcp.tool(name="get_sessions_for_agent", description="Get list of sessions for an agent", tags={"session"})  # type: ignore
    async def get_sessions_for_agent(
        agent_id: str,
        db_id: str,
        user_id: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        db = get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            sessions = await db.get_sessions(
                session_type=SessionType.AGENT,
                component_id=agent_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            sessions = db.get_sessions(
                session_type=SessionType.AGENT,
                component_id=agent_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )

        return {
            "data": [SessionSchema.from_dict(session) for session in sessions],  # type: ignore
        }

    @mcp.tool(name="get_sessions_for_team", description="Get list of sessions for a team", tags={"session"})  # type: ignore
    async def get_sessions_for_team(
        team_id: str,
        db_id: str,
        user_id: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        db = get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            sessions = await db.get_sessions(
                session_type=SessionType.TEAM,
                component_id=team_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            sessions = db.get_sessions(
                session_type=SessionType.TEAM,
                component_id=team_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )

        return {
            "data": [SessionSchema.from_dict(session) for session in sessions],  # type: ignore
        }

    @mcp.tool(name="get_sessions_for_workflow", description="Get list of sessions for a workflow", tags={"session"})  # type: ignore
    async def get_sessions_for_workflow(
        workflow_id: str,
        db_id: str,
        user_id: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        db = get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            sessions = await db.get_sessions(
                session_type=SessionType.WORKFLOW,
                component_id=workflow_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            sessions = db.get_sessions(
                session_type=SessionType.WORKFLOW,
                component_id=workflow_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )

        return {
            "data": [SessionSchema.from_dict(session) for session in sessions],  # type: ignore
        }

    # Memory Management Tools
    @mcp.tool(name="create_memory", description="Create a new user memory", tags={"memory"})  # type: ignore
    async def create_memory(
        db_id: str,
        memory: str,
        user_id: str,
        topics: Optional[List[str]] = None,
    ) -> UserMemorySchema:
        db = get_db(os.dbs, db_id)
        user_memory = db.upsert_user_memory(
            memory=UserMemory(
                memory_id=str(uuid4()),
                memory=memory,
                topics=topics or [],
                user_id=user_id,
            ),
            deserialize=False,
        )
        if not user_memory:
            raise Exception("Failed to create memory")

        return UserMemorySchema.from_dict(user_memory)  # type: ignore

    @mcp.tool(name="get_memories_for_user", description="Get a list of memories for a user", tags={"memory"})  # type: ignore
    async def get_memories_for_user(
        user_id: str,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        db_id: Optional[str] = None,
    ):
        db = get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memories = await db.get_user_memories(
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            user_memories = db.get_user_memories(
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        return {
            "data": [UserMemorySchema.from_dict(user_memory) for user_memory in user_memories],  # type: ignore
        }

    @mcp.tool(name="update_memory", description="Update a memory", tags={"memory"})  # type: ignore
    async def update_memory(
        db_id: str,
        memory_id: str,
        memory: str,
        user_id: str,
    ) -> UserMemorySchema:
        db = get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memory = await db.upsert_user_memory(
                memory=UserMemory(
                    memory_id=memory_id,
                    memory=memory,
                    user_id=user_id,
                ),
                deserialize=False,
            )
        else:
            user_memory = db.upsert_user_memory(
                memory=UserMemory(
                    memory_id=memory_id,
                    memory=memory,
                    user_id=user_id,
                ),
                deserialize=False,
            )
        if not user_memory:
            raise Exception("Failed to update memory")

        return UserMemorySchema.from_dict(user_memory)  # type: ignore

    @mcp.tool(name="delete_memory", description="Delete a memory by ID", tags={"memory"})  # type: ignore
    async def delete_memory(
        db_id: str,
        memory_id: str,
    ) -> None:
        db = get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_user_memory(memory_id=memory_id)
        else:
            db.delete_user_memory(memory_id=memory_id)

    mcp_app = mcp.http_app(path="/mcp")
    return mcp_app
