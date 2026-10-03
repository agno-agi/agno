from typing import TYPE_CHECKING, Dict, List
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.routing import Match

from agno.os.routers.voice.auth import VoiceAccessError, authenticate, origin_allowed
from agno.os.routers.voice.schema import VoicePipeResponse
from agno.os.settings import AgnoAPISettings
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.os.app import AgentOS
    from agno.voice.pipe import VoicePipe


def pipe_path(pipe_id: str) -> str:
    return f"/voice/{pipe_id}/ws"


def get_voice_router(os: "AgentOS", settings: AgnoAPISettings) -> APIRouter:
    """Expose each live socket at its canonical WebSocket route, /voice/{id}/ws."""
    router = APIRouter(tags=["Voice"])
    pipes: Dict[str, "VoicePipe"] = {pipe.id: pipe for pipe in os.live_sockets}
    _reject_conflicting_routes(os, pipes)

    @router.get(
        "/voice",
        response_model=List[VoicePipeResponse],
        summary="List Voice Pipes",
        description=(
            "List the voice pipes registered in `live_sockets`, with the agent each one speaks for.\n\n"
            "Each pipe is a WebSocket at `path` (`/voice/{id}/ws`). Clients stream PCM16, mono, 24 kHz "
            "microphone audio and receive transcripts, reply text, and PCM16 speech. WebSocket routes are "
            "not part of OpenAPI, so the pipe itself does not appear in these docs."
        ),
    )
    async def list_voice_pipes(request: Request) -> List[VoicePipeResponse]:
        return [
            VoicePipeResponse(id=pipe.id, agent_id=pipe.agent.id, agent_name=pipe.agent.name, path=pipe_path(pipe.id))
            for pipe in _visible_pipes(request, list(pipes.values()))
        ]

    @router.websocket("/voice/{pipe_id}/ws", name="voice_pipe")
    async def voice_socket(websocket: WebSocket, pipe_id: str):
        pipe = pipes.get(pipe_id)
        if pipe is None or not origin_allowed(websocket, os.cors_allowed_origins):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            user_id = await authenticate(websocket, pipe, settings)
            # Each connection owns a fresh session. Client-controlled IDs must not
            # reopen someone else's agent history or change run attribution.
            await pipe._serve(websocket, user_id=user_id, session_id=str(uuid4()))
        except VoiceAccessError as exc:
            await websocket.send_json({"event": "auth_error", "error": str(exc)})
            await websocket.close(code=1008)
        except WebSocketDisconnect:
            pass
        except Exception:
            log_error("Voice connection failed", exc_info=True)
            try:
                await websocket.send_json({"event": "error", "error": "Voice connection failed"})
                await websocket.close(code=1011)
            except (RuntimeError, WebSocketDisconnect):
                pass

    return router


def _reject_conflicting_routes(os: "AgentOS", pipes: Dict[str, "VoicePipe"]) -> None:
    """A pre-existing base-app route must never shadow the authenticated socket."""
    if os.base_app is None:
        return
    for pipe_id in pipes:
        path = pipe_path(pipe_id)
        scope = {"type": "websocket", "path": path, "root_path": "", "app": os.base_app}
        if any(route.matches(scope)[0] == Match.FULL for route in os.base_app.routes):
            raise ValueError(f"Voice route conflicts with an existing base-app route: {path}")


def _visible_pipes(request: Request, pipes: List["VoicePipe"]) -> List["VoicePipe"]:
    """Match GET /agents: only list pipes whose agent the caller may access."""
    if not getattr(request.state, "authorization_enabled", False):
        return pipes
    from agno.os.auth import build_insufficient_permissions_detail, filter_resources_by_access, get_accessible_resources

    if not get_accessible_resources(request, "agents"):
        raise HTTPException(
            status_code=403,
            detail=build_insufficient_permissions_detail(getattr(request.state, "required_scopes", None)),
        )
    allowed = filter_resources_by_access(request, [pipe.agent for pipe in pipes], "agents")
    return [pipe for pipe in pipes if any(agent is pipe.agent for agent in allowed)]
