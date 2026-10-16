"""Sandbox status and durable workspace downloads under agent/session authorization."""

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from agno.os.auth import require_resource_access
from agno.os.middleware.user_scope import assert_session_matches_component, get_scoped_user_id
from agno.sandbox.base import SandboxError
from agno.sandbox.checkpoint import CheckpointObjectNotFound, _name


def add_sandbox_artifact_routes(router: APIRouter, os: Any) -> None:
    async def resolve(request: Request, agent_id: str, session_id: str) -> Any:
        from agno.agents.base import BaseExternalAgent

        agent = next(
            (
                value
                for value in os.agents or []
                if isinstance(value, BaseExternalAgent) and value.sandbox is not None and value.get_id() == agent_id
            ),
            None,
        )
        if agent is None:
            raise HTTPException(404, "Sandbox agent not found")
        from agno.sandbox import _harness
        from agno.sandbox.artifacts import SandboxArtifacts

        session = await agent.aget_session(session_id, user_id=get_scoped_user_id(request))
        if session is None:
            raise HTTPException(404, "Sandbox session not found")
        assert_session_matches_component(session, "agents", agent_id)
        # The coordinator a turn would execute with, so a read resolves the same effective
        # checkpoint store that wrote the archive. Building one allocates no compute.
        try:
            coordinator = _harness.coordinator(agent)
        except ValueError as error:
            # The harness refuses a host-local default store while a queue worker runs, so this
            # session has no storage a replica could read: the same unavailable storage reported
            # below. Its other ValueError, a non-Postgres db, is already refused at OS startup.
            raise HTTPException(503, "Checkpoint storage is unavailable") from error
        return SandboxArtifacts(coordinator.store, coordinator.transfer.store), session.user_id

    async def call(operation: Any) -> Any:
        from agno.sandbox.artifacts import SandboxArtifactNotFound, SandboxSessionNotFound

        try:
            return await operation
        except (SandboxSessionNotFound, SandboxArtifactNotFound):
            raise HTTPException(404, "Sandbox session or artifact not found")
        # Before the SandboxError clause below, which it is a subclass of: an object the
        # store no longer holds is storage being unavailable, not a servable conflict.
        except (CheckpointObjectNotFound, FileNotFoundError):
            raise HTTPException(503, "Checkpoint storage is unavailable")
        except SandboxError:
            raise HTTPException(409, "Checkpoint or artifact cannot be served")

    dependencies = [Depends(require_resource_access("agents", "run", "agent_id"))]

    @router.get("/agents/{agent_id}/sessions/{session_id}/sandbox", tags=["Agents"], dependencies=dependencies)
    async def sandbox_status(request: Request, agent_id: str, session_id: str) -> Any:
        artifacts, user_id = await resolve(request, agent_id, session_id)
        return await call(artifacts.astatus(agent_id=agent_id, session_id=session_id, user_id=user_id))

    @router.get(
        "/agents/{agent_id}/sessions/{session_id}/sandbox/artifacts", tags=["Agents"], dependencies=dependencies
    )
    async def sandbox_artifacts(
        request: Request,
        agent_id: str,
        session_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ) -> Any:
        artifacts, user_id = await resolve(request, agent_id, session_id)
        return await call(
            artifacts.alist(agent_id=agent_id, session_id=session_id, user_id=user_id, offset=offset, limit=limit)
        )

    @router.get(
        "/agents/{agent_id}/sessions/{session_id}/sandbox/artifact",
        tags=["Agents"],
        dependencies=dependencies,
        # Response carries no media type of its own, so FastAPI emits no default
        # JSON entry and the declaration below is the only advertised 200 content.
        response_class=Response,
        responses={
            200: {
                "description": "Workspace file bytes from the last completed checkpoint",
                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def sandbox_artifact(
        request: Request, agent_id: str, session_id: str, path: str = Query(..., max_length=4096)
    ) -> Response:
        artifacts, user_id = await resolve(request, agent_id, session_id)
        try:
            # The archive grammar the service already enforces, applied here only so a
            # malformed request is answered as one instead of as a checkpoint conflict.
            # Order matters: resolution and its authorization run first.
            _name("workspace/" + path)
        except SandboxError as error:
            raise HTTPException(400, str(error)) from error
        artifact = await call(artifacts.aread(path, agent_id=agent_id, session_id=session_id, user_id=user_id))
        filename = quote(path.rsplit("/", 1)[-1], safe="")
        return Response(
            artifact.content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''" + filename,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
                "X-Agno-Checkpoint": artifact.checkpoint,
                "X-Agno-Run-ID": quote(artifact.run_id, safe=""),
            },
        )
