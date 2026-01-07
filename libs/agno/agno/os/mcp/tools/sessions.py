"""Session management MCP tools for AgentOS."""

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from fastmcp import FastMCP

from agno.db.base import AsyncBaseDb, SessionType
from agno.os.schema import (
    AgentSessionDetailSchema,
    RunSchema,
    SessionSchema,
    TeamRunSchema,
    TeamSessionDetailSchema,
    WorkflowRunSchema,
    WorkflowSessionDetailSchema,
)
from agno.os.utils import get_db
from agno.remote.base import RemoteDb
from agno.session import AgentSession, TeamSession, WorkflowSession

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_session_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register session management MCP tools."""

    @mcp.tool(
        name="get_sessions",
        description="Get paginated list of sessions with filtering and sorting options",
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
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        st = SessionType(session_type)

        if isinstance(db, RemoteDb):
            result = await db.get_sessions(
                session_type=st,
                component_id=component_id,
                user_id=user_id,
                session_name=session_name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            return {
                "data": [s.model_dump() for s in result.data],
                "total_count": result.meta.total_count if result.meta else 0,
                "page": page,
                "limit": limit,
            }

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            sessions, total_count = await db.get_sessions(
                session_type=st,
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
            sessions, total_count = db.get_sessions(  # type: ignore
                session_type=st,
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
            "total_count": total_count,
            "page": page,
            "limit": limit,
        }

    @mcp.tool(
        name="create_session",
        description="Create a new empty session for an agent, team, or workflow",
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
    ) -> dict:
        from uuid import uuid4

        db = await get_db(os.dbs, db_id)
        st = SessionType(session_type)

        # Generate session_id if not provided
        sid = session_id or str(uuid4())

        if isinstance(db, RemoteDb):
            created_session = await db.create_session(
                session_id=sid,
                session_name=session_name,
                session_state=session_state,
                metadata=metadata,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                session_type=st,
            )
            return created_session.model_dump()

        # Prepare session_data
        session_data: Dict[str, Any] = {}
        if session_state is not None:
            session_data["session_state"] = session_state
        if session_name is not None:
            session_data["session_name"] = session_name

        current_time = int(time.time())

        # Create the appropriate session type
        session: Any
        if st == SessionType.AGENT:
            session = AgentSession(
                session_id=sid,
                agent_id=agent_id,
                user_id=user_id,
                session_data=session_data if session_data else None,
                metadata=metadata,
                created_at=current_time,
                updated_at=current_time,
            )
        elif st == SessionType.TEAM:
            session = TeamSession(
                session_id=sid,
                team_id=team_id,
                user_id=user_id,
                session_data=session_data if session_data else None,
                metadata=metadata,
                created_at=current_time,
                updated_at=current_time,
            )
        elif st == SessionType.WORKFLOW:
            session = WorkflowSession(
                session_id=sid,
                workflow_id=workflow_id,
                user_id=user_id,
                session_data=session_data if session_data else None,
                metadata=metadata,
                created_at=current_time,
                updated_at=current_time,
            )
        else:
            raise Exception(f"Invalid session type: {session_type}")

        # Upsert the session
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            created_session = await db.upsert_session(session, deserialize=True)  # type: ignore
        else:
            created_session = db.upsert_session(session, deserialize=True)  # type: ignore

        if not created_session:
            raise Exception("Failed to create session")

        # Return appropriate schema based on session type
        if st == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(created_session).model_dump()  # type: ignore
        elif st == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(created_session).model_dump()  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(created_session).model_dump()  # type: ignore

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
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        st = SessionType(session_type)

        if isinstance(db, RemoteDb):
            session = await db.get_session(session_id=session_id, session_type=st, user_id=user_id)
            return session.model_dump()

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            local_session = await db.get_session(session_id=session_id, session_type=st, user_id=user_id)
        else:
            local_session = db.get_session(session_id=session_id, session_type=st, user_id=user_id)  # type: ignore

        if not local_session:
            raise Exception(f"Session with id '{session_id}' not found")

        if st == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(local_session).model_dump()  # type: ignore
        elif st == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(local_session).model_dump()  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(local_session).model_dump()  # type: ignore

    @mcp.tool(
        name="get_session_runs",
        description="Get all runs (executions) for a specific session",
        tags={"session"},
    )  # type: ignore
    async def get_session_runs(
        session_id: str,
        db_id: str,
        session_type: str = "agent",
        user_id: Optional[str] = None,
        created_after: Optional[int] = None,
        created_before: Optional[int] = None,
    ) -> List[dict]:
        db = await get_db(os.dbs, db_id)
        st = SessionType(session_type)

        if isinstance(db, RemoteDb):
            remote_runs = await db.get_session_runs(
                session_id=session_id,
                session_type=st,
                user_id=user_id,
                created_after=created_after,
                created_before=created_before,
            )
            return [r.model_dump() for r in remote_runs]

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            local_session = await db.get_session(
                session_id=session_id, session_type=st, user_id=user_id, deserialize=False
            )
        else:
            local_session = db.get_session(session_id=session_id, session_type=st, user_id=user_id, deserialize=False)  # type: ignore

        if not local_session:
            raise Exception(f"Session with ID {session_id} not found")

        runs = local_session.get("runs")  # type: ignore
        if not runs:
            return []

        # Filter runs by timestamp if specified
        filtered_runs = []
        for run in runs:
            if created_after or created_before:
                run_created_at = run.get("created_at")
                if run_created_at:
                    if created_after and run_created_at < created_after:
                        continue
                    if created_before and run_created_at > created_before:
                        continue
            filtered_runs.append(run)

        if not filtered_runs:
            return []

        # Convert to appropriate schema
        results = []
        if st == SessionType.AGENT:
            results = [RunSchema.from_dict(run).model_dump() for run in filtered_runs]
        elif st == SessionType.TEAM:
            for run in filtered_runs:
                if run.get("agent_id") is not None:
                    results.append(RunSchema.from_dict(run).model_dump())
                elif run.get("team_id") is not None:
                    results.append(TeamRunSchema.from_dict(run).model_dump())
        elif st == SessionType.WORKFLOW:
            for run in filtered_runs:
                if run.get("workflow_id") is not None:
                    results.append(WorkflowRunSchema.from_dict(run).model_dump())
                elif run.get("team_id") is not None:
                    results.append(TeamRunSchema.from_dict(run).model_dump())
                else:
                    results.append(RunSchema.from_dict(run).model_dump())

        return results

    @mcp.tool(
        name="get_session_run",
        description="Get a specific run by ID from a session",
        tags={"session"},
    )  # type: ignore
    async def get_session_run(
        session_id: str,
        run_id: str,
        db_id: str,
        session_type: str = "agent",
        user_id: Optional[str] = None,
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        st = SessionType(session_type)

        if isinstance(db, RemoteDb):
            run = await db.get_session_run(session_id=session_id, run_id=run_id, session_type=st, user_id=user_id)
            return run.model_dump()

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            session = await db.get_session(session_id=session_id, session_type=st, user_id=user_id, deserialize=False)
        else:
            session = db.get_session(session_id=session_id, session_type=st, user_id=user_id, deserialize=False)

        if not session:
            raise Exception(f"Session with ID {session_id} not found")

        runs = session.get("runs")  # type: ignore
        if not runs:
            raise Exception(f"Session with ID {session_id} has no runs")

        # Find the specific run
        target_run = None
        for run in runs:
            if run.get("run_id") == run_id:
                target_run = run
                break

        if not target_run:
            raise Exception(f"Run with ID {run_id} not found in session {session_id}")

        # Return the appropriate schema based on run type
        if target_run.get("workflow_id") is not None:
            return WorkflowRunSchema.from_dict(target_run).model_dump()
        elif target_run.get("team_id") is not None:
            return TeamRunSchema.from_dict(target_run).model_dump()
        else:
            return RunSchema.from_dict(target_run).model_dump()

    @mcp.tool(
        name="delete_session",
        description="Delete a specific session and all its runs",
        tags={"session"},
    )  # type: ignore
    async def delete_session(
        session_id: str,
        db_id: str,
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_session(session_id=session_id)
        else:
            db.delete_session(session_id=session_id)

        return {"message": f"Session {session_id} deleted successfully"}

    @mcp.tool(
        name="delete_sessions",
        description="Delete multiple sessions by their IDs",
        tags={"session"},
    )  # type: ignore
    async def delete_sessions(
        session_ids: List[str],
        db_id: str,
        session_types: Optional[List[str]] = None,
    ) -> dict:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            # Default to all session types if not specified
            types = (
                [SessionType(t) for t in session_types]
                if session_types
                else [SessionType.AGENT, SessionType.TEAM, SessionType.WORKFLOW]
            )
            await db.delete_sessions(session_ids=session_ids, session_types=types)
            return {"message": f"Deleted {len(session_ids)} sessions"}

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_sessions(session_ids=session_ids)
        else:
            db.delete_sessions(session_ids=session_ids)

        return {"message": f"Deleted {len(session_ids)} sessions"}

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
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        st = SessionType(session_type)

        # Handle RemoteDb
        if isinstance(db, RemoteDb):
            remote_session = await db.rename_session(session_id=session_id, session_name=session_name, session_type=st)
            return remote_session.model_dump()

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            local_session = await db.rename_session(session_id=session_id, session_type=st, session_name=session_name)
        else:
            local_session = db.rename_session(session_id=session_id, session_type=st, session_name=session_name)  # type: ignore

        if not local_session:
            raise Exception(f"Session with id '{session_id}' not found")

        if st == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(local_session).model_dump()  # type: ignore
        elif st == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(local_session).model_dump()  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(local_session).model_dump()  # type: ignore

    @mcp.tool(
        name="update_session",
        description="Update session properties like name, state, metadata, or summary",
        tags={"session"},
    )  # type: ignore
    async def update_session(
        session_id: str,
        db_id: str,
        session_type: str = "agent",
        user_id: Optional[str] = None,
        session_name: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        summary: Optional[Dict[str, Any]] = None,
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        st = SessionType(session_type)

        if isinstance(db, RemoteDb):
            session = await db.update_session(
                session_id=session_id,
                session_type=st,
                user_id=user_id,
                session_name=session_name,
                session_state=session_state,
                metadata=metadata,
                summary=summary,
            )
            return session.model_dump()

        # Get the existing session
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            existing_session = await db.get_session(
                session_id=session_id, session_type=st, user_id=user_id, deserialize=True
            )  # type: ignore
        else:
            existing_session = db.get_session(session_id=session_id, session_type=st, user_id=user_id, deserialize=True)  # type: ignore

        if not existing_session:
            raise Exception(f"Session with id '{session_id}' not found")

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
            db = cast(AsyncBaseDb, db)
            updated_session = await db.upsert_session(existing_session, deserialize=True)  # type: ignore
        else:
            updated_session = db.upsert_session(existing_session, deserialize=True)  # type: ignore

        if not updated_session:
            raise Exception("Failed to update session")

        if st == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(updated_session).model_dump()  # type: ignore
        elif st == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(updated_session).model_dump()  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(updated_session).model_dump()  # type: ignore

    # Keep the legacy convenience tools for backward compatibility
    @mcp.tool(
        name="get_sessions_for_agent",
        description="Get list of sessions for an agent",
        tags={"session"},
    )  # type: ignore
    async def get_sessions_for_agent(
        agent_id: str,
        db_id: str,
        user_id: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            result = await db.get_sessions(
                session_type=SessionType.AGENT,
                component_id=agent_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            return {"data": [s.model_dump() for s in result.data]}

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            sessions, _ = await db.get_sessions(
                session_type=SessionType.AGENT,
                component_id=agent_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            sessions, _ = db.get_sessions(  # type: ignore
                session_type=SessionType.AGENT,
                component_id=agent_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )

        return {
            "data": [SessionSchema.from_dict(session).model_dump() for session in sessions],  # type: ignore
        }

    @mcp.tool(
        name="get_sessions_for_team",
        description="Get list of sessions for a team",
        tags={"session"},
    )  # type: ignore
    async def get_sessions_for_team(
        team_id: str,
        db_id: str,
        user_id: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            result = await db.get_sessions(
                session_type=SessionType.TEAM,
                component_id=team_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            return {"data": [s.model_dump() for s in result.data]}

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            sessions, _ = await db.get_sessions(
                session_type=SessionType.TEAM,
                component_id=team_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            sessions, _ = db.get_sessions(  # type: ignore
                session_type=SessionType.TEAM,
                component_id=team_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )

        return {
            "data": [SessionSchema.from_dict(session).model_dump() for session in sessions],  # type: ignore
        }

    @mcp.tool(
        name="get_sessions_for_workflow",
        description="Get list of sessions for a workflow",
        tags={"session"},
    )  # type: ignore
    async def get_sessions_for_workflow(
        workflow_id: str,
        db_id: str,
        user_id: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            result = await db.get_sessions(
                session_type=SessionType.WORKFLOW,
                component_id=workflow_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            return {"data": [s.model_dump() for s in result.data]}

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            sessions, _ = await db.get_sessions(
                session_type=SessionType.WORKFLOW,
                component_id=workflow_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            sessions, _ = db.get_sessions(  # type: ignore
                session_type=SessionType.WORKFLOW,
                component_id=workflow_id,
                user_id=user_id,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )

        return {
            "data": [SessionSchema.from_dict(session).model_dump() for session in sessions],  # type: ignore
        }
