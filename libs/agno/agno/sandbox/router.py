"""Control-plane sandbox inspection and lifecycle routes."""

from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from agno.agents.sandbox import SandboxAgent
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id


def get_sandbox_router(agent_os: Any) -> APIRouter:
    router = APIRouter(tags=["Sandboxes"], dependencies=[Depends(get_authentication_dependency(agent_os.settings))])
    agents = [entry for entry in agent_os.agents or [] if isinstance(entry, SandboxAgent)]

    def public(row: Dict[str, Any]) -> Dict[str, Any]:
        # Never expose runtime URLs, tokens, provider configuration or credentials.
        keys = (
            "sandbox_id",
            "session_id",
            "agent_id",
            "user_id",
            "provider",
            "status",
            "generation",
            "active_run_id",
            "created_at",
            "updated_at",
            "last_active_at",
        )
        result = {key: row.get(key) for key in keys}
        result["workspace_checkpoint"] = row["metadata"].get("checkpoint")
        result["error"] = row["metadata"].get("error") or row["metadata"].get("checkpoint_error")
        return result

    async def locate(request: Request, *, sandbox_id: Optional[str] = None, session_id: Optional[str] = None) -> Any:
        owner = get_scoped_user_id(request)
        for agent in agents:
            row = await agent._registry.get(sandbox_id=sandbox_id, session_id=session_id)
            if row and row["agent_id"] == agent.id and (owner is None or row.get("user_id") == owner):
                return agent, row
        raise HTTPException(404, "Sandbox not found")

    @router.get("/sandboxes")
    async def list_sandboxes(
        request: Request, agent_id: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        owner = get_scoped_user_id(request)
        rows = []
        for agent in agents:
            if agent_id is not None and agent.id != agent_id:
                continue
            for row in await agent._registry.list(agent.get_id()):
                if (owner is None or row.get("user_id") == owner) and (status is None or row["status"] == status):
                    rows.append(public(row))
        return rows

    @router.get("/sessions/{session_id}/sandbox")
    async def get_binding(request: Request, session_id: str) -> Dict[str, Any]:
        _, row = await locate(request, session_id=session_id)
        return public(row)

    @router.delete("/sandboxes/{sandbox_id}")
    async def destroy(request: Request, sandbox_id: str) -> Dict[str, bool]:
        agent, row = await locate(request, sandbox_id=sandbox_id)
        try:
            destroyed = await agent.adestroy_sandbox(sandbox_id, expected_revision=row["revision"])
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if not destroyed:
            raise HTTPException(409, "Sandbox changed; retry after checking its status")
        return {"destroyed": True}

    @router.post("/sessions/{session_id}/sandbox:pause")
    async def pause(request: Request, session_id: str) -> None:
        await locate(request, session_id=session_id)
        raise HTTPException(501, "Pause is not supported by the Docker sandbox provider")

    return router


async def destroy_session_sandboxes(request: Request, db: Any, session_ids: List[str], user_id: Optional[str]) -> None:
    bindings = []
    for agent in getattr(request.app.state, "sandbox_agents", []):
        if agent.db.id != db.id:
            continue
        for session_id in session_ids:
            row = await agent._registry.get(session_id=session_id)
            if row is None:
                session = await agent.aget_session(session_id, user_id=user_id)
                if session is not None and session.agent_id == agent.id:
                    # Reserve the absent binding before deleting a queued session.
                    await agent._registry.insert(
                        dict(
                            sandbox_id=str(uuid4()),
                            session_id=session_id,
                            agent_id=agent.id,
                            user_id=session.user_id,
                            provider=agent.provider.name,
                            status="destroyed",
                            generation=1,
                            metadata={"session_deleted": True},
                        )
                    )
                    row = await agent._registry.get(session_id=session_id)
            if row and row["agent_id"] == agent.id and (user_id is None or row.get("user_id") == user_id):
                if row.get("active_run_id"):
                    raise HTTPException(409, "Cancel the active sandbox run before deleting its session")
                bindings.append((agent, row))
    for agent, row in bindings:
        if not await agent.adestroy_sandbox(row["sandbox_id"], expected_revision=row["revision"], delete_session=True):
            raise HTTPException(409, "Sandbox changed during session deletion; retry")
