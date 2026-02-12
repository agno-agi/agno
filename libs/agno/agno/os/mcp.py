"""Router for MCP interface providing Model Context Protocol endpoints."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast
from uuid import uuid4

from fastmcp import FastMCP
from fastmcp.server.http import (
    StarletteWithLifespan,
)

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.db.schemas import UserMemory
from agno.os.routers.memory.schemas import (
    UserMemorySchema,
)
from agno.os.schema import (
    AgentSessionDetailSchema,
    AgentSummaryResponse,
    ConfigResponse,
    InterfaceResponse,
    RunSchema,
    SessionSchema,
    TeamRunSchema,
    TeamSessionDetailSchema,
    TeamSummaryResponse,
    WorkflowRunSchema,
    WorkflowSessionDetailSchema,
    WorkflowSummaryResponse,
)
from agno.os.utils import (
    get_agent_by_id,
    get_db,
    get_team_by_id,
    get_workflow_by_id,
)
from agno.remote.base import RemoteDb
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, TeamSession, WorkflowSession

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
            databases=[db.id for db_list in os.dbs.values() for db in db_list],
            chat=os.config.chat if os.config else None,
            session=os._get_session_config(),
            memory=os._get_memory_config(),
            knowledge=os._get_knowledge_config(),
            evals=os._get_evals_config(),
            metrics=os._get_metrics_config(),
            traces=os._get_traces_config(),
            agents=[AgentSummaryResponse.from_agent(agent) for agent in os.agents] if os.agents else [],
            teams=[TeamSummaryResponse.from_team(team) for team in os.teams] if os.teams else [],
            workflows=[WorkflowSummaryResponse.from_workflow(w) for w in os.workflows] if os.workflows else [],
            interfaces=[
                InterfaceResponse(type=interface.type, version=interface.version, route=interface.prefix)
                for interface in os.interfaces
            ],
        )

    # ==================== Core Run Tools ====================

    @mcp.tool(name="run_agent", description="Run an agent with a message", tags={"core"})  # type: ignore
    async def run_agent(agent_id: str, message: str) -> RunOutput:
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise Exception(f"Agent {agent_id} not found")
        return await agent.arun(message)  # type: ignore[misc]

    @mcp.tool(name="run_team", description="Run a team with a message", tags={"core"})  # type: ignore
    async def run_team(team_id: str, message: str) -> TeamRunOutput:
        team = get_team_by_id(team_id, os.teams)
        if team is None:
            raise Exception(f"Team {team_id} not found")
        return await team.arun(message)  # type: ignore[misc]

    @mcp.tool(name="run_workflow", description="Run a workflow with a message", tags={"core"})  # type: ignore
    async def run_workflow(workflow_id: str, message: str) -> WorkflowRunOutput:
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise Exception(f"Workflow {workflow_id} not found")
        return await workflow.arun(message)

    # ==================== Session Management Tools ====================

    @mcp.tool(
        name="get_sessions",
        description="Get paginated list of sessions with optional filtering by type, component, user, and name",
        tags={"session"},
    )  # type: ignore
    async def get_sessions(
        db_id: str,
        session_type: str = "agent",
        component_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_name: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type)
        if isinstance(db, RemoteDb):
            result = await db.get_sessions(
                session_type=session_type_enum,
                component_id=component_id,
                user_id=user_id,
                session_name=session_name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                db_id=db_id,
            )
            return result.model_dump()

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            sessions, total_count = await db.get_sessions(
                session_type=session_type_enum,
                component_id=component_id,
                user_id=user_id,
                session_name=session_name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            sessions, total_count = db.get_sessions(
                session_type=session_type_enum,
                component_id=component_id,
                user_id=user_id,
                session_name=session_name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )

        return {
            "data": [SessionSchema.from_dict(session).model_dump() for session in sessions],  # type: ignore
            "meta": {
                "page": page,
                "limit": limit,
                "total_count": total_count,
                "total_pages": (total_count + limit - 1) // limit if limit > 0 else 0,  # type: ignore
            },
        }

    @mcp.tool(
        name="get_session",
        description="Get detailed information about a specific session by ID",
        tags={"session"},
    )  # type: ignore
    async def get_session(
        session_id: str,
        db_id: str,
        session_type: str = "agent",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type)

        if isinstance(db, RemoteDb):
            result = await db.get_session(
                session_id=session_id,
                session_type=session_type_enum,
                user_id=user_id,
                db_id=db_id,
            )
            return result.model_dump()

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            session = await db.get_session(session_id=session_id, session_type=session_type_enum, user_id=user_id)
        else:
            db = cast(BaseDb, db)
            session = db.get_session(session_id=session_id, session_type=session_type_enum, user_id=user_id)

        if not session:
            raise Exception(f"Session {session_id} not found")

        if session_type_enum == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(session).model_dump()  # type: ignore
        elif session_type_enum == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(session).model_dump()  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(session).model_dump()  # type: ignore

    @mcp.tool(
        name="create_session",
        description="Create a new session for an agent, team, or workflow",
        tags={"session"},
    )  # type: ignore
    async def create_session(
        db_id: str,
        session_type: str = "agent",
        session_id: Optional[str] = None,
        session_name: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        import time

        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type)

        # Generate session_id if not provided
        session_id = session_id or str(uuid4())

        if isinstance(db, RemoteDb):
            result = await db.create_session(
                session_type=session_type_enum,
                session_id=session_id,
                session_name=session_name,
                session_state=session_state,
                metadata=metadata,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                db_id=db_id,
            )
            return result.model_dump()

        # Prepare session_data
        session_data: Dict[str, Any] = {}
        if session_state is not None:
            session_data["session_state"] = session_state
        if session_name is not None:
            session_data["session_name"] = session_name

        current_time = int(time.time())

        # Create the appropriate session type
        session: Union[AgentSession, TeamSession, WorkflowSession]
        if session_type_enum == SessionType.AGENT:
            session = AgentSession(
                session_id=session_id,
                agent_id=agent_id,
                user_id=user_id,
                session_data=session_data if session_data else None,
                metadata=metadata,
                created_at=current_time,
                updated_at=current_time,
            )
        elif session_type_enum == SessionType.TEAM:
            session = TeamSession(
                session_id=session_id,
                team_id=team_id,
                user_id=user_id,
                session_data=session_data if session_data else None,
                metadata=metadata,
                created_at=current_time,
                updated_at=current_time,
            )
        else:
            session = WorkflowSession(
                session_id=session_id,
                workflow_id=workflow_id,
                user_id=user_id,
                session_data=session_data if session_data else None,
                metadata=metadata,
                created_at=current_time,
                updated_at=current_time,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            created_session = await db.upsert_session(session, deserialize=True)
        else:
            created_session = db.upsert_session(session, deserialize=True)

        if not created_session:
            raise Exception("Failed to create session")

        if session_type_enum == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(created_session).model_dump()  # type: ignore
        elif session_type_enum == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(created_session).model_dump()  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(created_session).model_dump()  # type: ignore

    @mcp.tool(
        name="get_session_runs",
        description="Get all runs for a specific session",
        tags={"session"},
    )  # type: ignore
    async def get_session_runs(
        session_id: str,
        db_id: str,
        session_type: str = "agent",
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type)

        if isinstance(db, RemoteDb):
            result = await db.get_session_runs(
                session_id=session_id,
                session_type=session_type_enum,
                user_id=user_id,
                db_id=db_id,
            )
            return [r.model_dump() for r in result]

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            session = await db.get_session(
                session_id=session_id, session_type=session_type_enum, user_id=user_id, deserialize=False
            )
        else:
            session = db.get_session(
                session_id=session_id, session_type=session_type_enum, user_id=user_id, deserialize=False
            )

        if not session:
            raise Exception(f"Session {session_id} not found")

        runs = session.get("runs")  # type: ignore
        if not runs:
            return []

        run_responses: List[Dict[str, Any]] = []
        for run in runs:
            if session_type_enum == SessionType.AGENT:
                run_responses.append(RunSchema.from_dict(run).model_dump())
            elif session_type_enum == SessionType.TEAM:
                if run.get("agent_id") is not None:
                    run_responses.append(RunSchema.from_dict(run).model_dump())
                else:
                    run_responses.append(TeamRunSchema.from_dict(run).model_dump())
            else:
                if run.get("workflow_id") is not None:
                    run_responses.append(WorkflowRunSchema.from_dict(run).model_dump())
                elif run.get("team_id") is not None:
                    run_responses.append(TeamRunSchema.from_dict(run).model_dump())
                else:
                    run_responses.append(RunSchema.from_dict(run).model_dump())

        return run_responses

    @mcp.tool(
        name="get_session_run",
        description="Get a specific run from a session",
        tags={"session"},
    )  # type: ignore
    async def get_session_run(
        session_id: str,
        run_id: str,
        db_id: str,
        session_type: str = "agent",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type)

        if isinstance(db, RemoteDb):
            result = await db.get_session_run(
                session_id=session_id,
                run_id=run_id,
                session_type=session_type_enum,
                user_id=user_id,
                db_id=db_id,
            )
            return result.model_dump()

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            session = await db.get_session(
                session_id=session_id, session_type=session_type_enum, user_id=user_id, deserialize=False
            )
        else:
            session = db.get_session(
                session_id=session_id, session_type=session_type_enum, user_id=user_id, deserialize=False
            )

        if not session:
            raise Exception(f"Session {session_id} not found")

        runs = session.get("runs")  # type: ignore
        if not runs:
            raise Exception(f"Session {session_id} has no runs")

        target_run = None
        for run in runs:
            if run.get("run_id") == run_id:
                target_run = run
                break

        if not target_run:
            raise Exception(f"Run {run_id} not found in session {session_id}")

        if target_run.get("workflow_id") is not None:
            return WorkflowRunSchema.from_dict(target_run).model_dump()
        elif target_run.get("team_id") is not None:
            return TeamRunSchema.from_dict(target_run).model_dump()
        else:
            return RunSchema.from_dict(target_run).model_dump()

    @mcp.tool(
        name="rename_session",
        description="Rename an existing session",
        tags={"session"},
    )  # type: ignore
    async def rename_session(
        session_id: str,
        session_name: str,
        db_id: str,
        session_type: str = "agent",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type)

        if isinstance(db, RemoteDb):
            result = await db.rename_session(
                session_id=session_id,
                session_name=session_name,
                session_type=session_type_enum,
                db_id=db_id,
            )
            return result.model_dump()

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            session = await db.rename_session(
                session_id=session_id, session_type=session_type_enum, session_name=session_name, user_id=user_id
            )
        else:
            db = cast(BaseDb, db)
            session = db.rename_session(
                session_id=session_id, session_type=session_type_enum, session_name=session_name, user_id=user_id
            )

        if not session:
            raise Exception(f"Session {session_id} not found")

        if session_type_enum == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(session).model_dump()  # type: ignore
        elif session_type_enum == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(session).model_dump()  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(session).model_dump()  # type: ignore

    @mcp.tool(
        name="update_session",
        description="Update session properties like name, state, metadata, or summary",
        tags={"session"},
    )  # type: ignore
    async def update_session(
        session_id: str,
        db_id: str,
        session_type: str = "agent",
        session_name: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        summary: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type)

        if isinstance(db, RemoteDb):
            result = await db.update_session(
                session_id=session_id,
                session_type=session_type_enum,
                session_name=session_name,
                session_state=session_state,
                metadata=metadata,
                summary=summary,
                user_id=user_id,
                db_id=db_id,
            )
            return result.model_dump()

        # Get the existing session
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            existing_session = await db.get_session(
                session_id=session_id, session_type=session_type_enum, user_id=user_id, deserialize=True
            )
        else:
            existing_session = db.get_session(
                session_id=session_id, session_type=session_type_enum, user_id=user_id, deserialize=True
            )

        if not existing_session:
            raise Exception(f"Session {session_id} not found")

        # Update session properties
        if session_name is not None:
            if existing_session.session_data is None:  # type: ignore
                existing_session.session_data = {}  # type: ignore
            existing_session.session_data["session_name"] = session_name  # type: ignore

        if session_state is not None:
            if existing_session.session_data is None:  # type: ignore
                existing_session.session_data = {}  # type: ignore
            existing_session.session_data["session_state"] = session_state  # type: ignore

        if metadata is not None:
            existing_session.metadata = metadata  # type: ignore

        if summary is not None:
            from agno.session.summary import SessionSummary

            existing_session.summary = SessionSummary.from_dict(summary)  # type: ignore

        # Upsert the updated session
        if isinstance(db, AsyncBaseDb):
            updated_session = await db.upsert_session(existing_session, deserialize=True)  # type: ignore
        else:
            updated_session = db.upsert_session(existing_session, deserialize=True)  # type: ignore

        if not updated_session:
            raise Exception("Failed to update session")

        if session_type_enum == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(updated_session).model_dump()  # type: ignore
        elif session_type_enum == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(updated_session).model_dump()  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(updated_session).model_dump()  # type: ignore

    @mcp.tool(
        name="delete_session",
        description="Delete a specific session and all its runs",
        tags={"session"},
    )  # type: ignore
    async def delete_session(
        session_id: str,
        db_id: str,
        user_id: Optional[str] = None,
    ) -> str:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            await db.delete_session(session_id=session_id, db_id=db_id)
            return "Session deleted successfully"

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_session(session_id=session_id, user_id=user_id)
        else:
            db = cast(BaseDb, db)
            db.delete_session(session_id=session_id, user_id=user_id)

        return "Session deleted successfully"

    @mcp.tool(
        name="delete_sessions",
        description="Delete multiple sessions by their IDs",
        tags={"session"},
    )  # type: ignore
    async def delete_sessions(
        session_ids: List[str],
        db_id: str,
        session_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> str:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            # Convert session_types strings to SessionType enums
            session_type_enums = [SessionType(st) for st in session_types] if session_types else []
            await db.delete_sessions(session_ids=session_ids, session_types=session_type_enums, db_id=db_id)
            return "Sessions deleted successfully"

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_sessions(session_ids=session_ids, user_id=user_id)
        else:
            db = cast(BaseDb, db)
            db.delete_sessions(session_ids=session_ids, user_id=user_id)

        return "Sessions deleted successfully"

    # ==================== Memory Management Tools ====================

    @mcp.tool(name="create_memory", description="Create a new user memory", tags={"memory"})  # type: ignore
    async def create_memory(
        db_id: str,
        memory: str,
        user_id: str,
        topics: Optional[List[str]] = None,
    ) -> UserMemorySchema:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            return await db.create_memory(
                memory=memory,
                topics=topics or [],
                user_id=user_id,
                db_id=db_id,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memory = await db.upsert_user_memory(
                memory=UserMemory(
                    memory_id=str(uuid4()),
                    memory=memory,
                    topics=topics or [],
                    user_id=user_id,
                ),
                deserialize=False,
            )
        else:
            db = cast(BaseDb, db)
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

    @mcp.tool(
        name="get_memory",
        description="Get a specific memory by ID",
        tags={"memory"},
    )  # type: ignore
    async def get_memory(
        memory_id: str,
        db_id: str,
        user_id: Optional[str] = None,
    ) -> UserMemorySchema:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            return await db.get_memory(memory_id=memory_id, user_id=user_id, db_id=db_id)

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memory = await db.get_user_memory(memory_id=memory_id, user_id=user_id, deserialize=False)
        else:
            db = cast(BaseDb, db)
            user_memory = db.get_user_memory(memory_id=memory_id, user_id=user_id, deserialize=False)

        if not user_memory:
            raise Exception(f"Memory {memory_id} not found")

        return UserMemorySchema.from_dict(user_memory)  # type: ignore

    @mcp.tool(
        name="get_memories",
        description="Get a paginated list of memories with optional filtering",
        tags={"memory"},
    )  # type: ignore
    async def get_memories(
        db_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            result = await db.get_memories(
                user_id=user_id or "",
                agent_id=agent_id,
                team_id=team_id,
                topics=topics,
                search_content=search_content,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                db_id=db_id,
            )
            return result.model_dump()

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memories, total_count = await db.get_user_memories(
                limit=limit,
                page=page,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                topics=topics,
                search_content=search_content,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            db = cast(BaseDb, db)
            user_memories, total_count = db.get_user_memories(
                limit=limit,
                page=page,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                topics=topics,
                search_content=search_content,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )

        memories = [UserMemorySchema.from_dict(m) for m in user_memories]  # type: ignore
        return {
            "data": [m.model_dump() for m in memories if m is not None],
            "meta": {
                "page": page,
                "limit": limit,
                "total_count": total_count,
                "total_pages": (total_count + limit - 1) // limit if limit > 0 else 0,  # type: ignore
            },
        }

    @mcp.tool(name="update_memory", description="Update an existing memory", tags={"memory"})  # type: ignore
    async def update_memory(
        db_id: str,
        memory_id: str,
        memory: str,
        user_id: str,
        topics: Optional[List[str]] = None,
    ) -> UserMemorySchema:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            return await db.update_memory(
                memory_id=memory_id,
                memory=memory,
                topics=topics or [],
                user_id=user_id,
                db_id=db_id,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memory = await db.upsert_user_memory(
                memory=UserMemory(
                    memory_id=memory_id,
                    memory=memory,
                    topics=topics or [],
                    user_id=user_id,
                ),
                deserialize=False,
            )
        else:
            db = cast(BaseDb, db)
            user_memory = db.upsert_user_memory(
                memory=UserMemory(
                    memory_id=memory_id,
                    memory=memory,
                    topics=topics or [],
                    user_id=user_id,
                ),
                deserialize=False,
            )

        if not user_memory:
            raise Exception("Failed to update memory")

        return UserMemorySchema.from_dict(user_memory)  # type: ignore

    @mcp.tool(name="delete_memory", description="Delete a specific memory by ID", tags={"memory"})  # type: ignore
    async def delete_memory(
        db_id: str,
        memory_id: str,
        user_id: Optional[str] = None,
    ) -> str:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            await db.delete_memory(memory_id=memory_id, user_id=user_id, db_id=db_id)
            return "Memory deleted successfully"

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_user_memory(memory_id=memory_id, user_id=user_id)
        else:
            db = cast(BaseDb, db)
            db.delete_user_memory(memory_id=memory_id, user_id=user_id)

        return "Memory deleted successfully"

    @mcp.tool(
        name="delete_memories",
        description="Delete multiple memories by their IDs",
        tags={"memory"},
    )  # type: ignore
    async def delete_memories(
        memory_ids: List[str],
        db_id: str,
        user_id: Optional[str] = None,
    ) -> str:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            await db.delete_memories(memory_ids=memory_ids, user_id=user_id, db_id=db_id)
            return "Memories deleted successfully"

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_user_memories(memory_ids=memory_ids, user_id=user_id)
        else:
            db = cast(BaseDb, db)
            db.delete_user_memories(memory_ids=memory_ids, user_id=user_id)

        return "Memories deleted successfully"

    # Use http_app for Streamable HTTP transport (modern MCP standard)
    mcp_app = mcp.http_app(path="/mcp")

    # Add JWT middleware to MCP app if authorization is enabled
    if os.authorization and os.authorization_config:
        from agno.os.middleware.jwt import JWTMiddleware

        mcp_app.add_middleware(
            JWTMiddleware,
            verification_keys=os.authorization_config.verification_keys,
            jwks_file=os.authorization_config.jwks_file,
            algorithm=os.authorization_config.algorithm or "RS256",
            authorization=os.authorization,
            verify_audience=os.authorization_config.verify_audience or False,
        )

    return mcp_app
