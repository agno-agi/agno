import asyncio
import json
from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.msteams.helpers import (
    MSTeamsConfig,
    extract_conversation_ref,
    send_teams_message_async,
)
from agno.os.interfaces.msteams.router import _SESSION_DISPATCH, attach_routes
from agno.team import RemoteTeam, Team
from agno.utils.log import log_warning
from agno.workflow import RemoteWorkflow, Workflow


class MSTeams(BaseInterface):
    """Microsoft Teams interface for agents, teams, and workflows.

    Serves ``GET /status`` and the Bot Framework webhook ``POST /messages``
    under ``prefix``. ``send_alert`` / ``asend_alert`` push a message to a user
    who has chatted with the bot before, using the conversation reference their
    inbound messages stored.
    """

    type = "msteams"

    # JWT validation happens inside the webhook — the base AgentOS auth
    # layer must NOT re-validate the request.
    authenticates_own_requests = True

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/msteams",
        tags: Optional[List[str]] = None,
        show_reasoning: bool = False,
        send_user_id_to_context: bool = False,
        app_id: Optional[str] = None,
        app_password: Optional[str] = None,
        tenant_id: Optional[str] = None,
        request_timeout: int = 30,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Microsoft Teams"]
        self.show_reasoning = show_reasoning
        self.send_user_id_to_context = send_user_id_to_context
        self.app_id = app_id
        self.app_password = app_password
        self.tenant_id = tenant_id
        self.request_timeout = request_timeout
        # Built once and shared with the router: the cached bot access token
        # lives on it, so a per-call config would re-authenticate every time.
        self._config: Optional[MSTeamsConfig] = None

        if not (self.agent or self.team or self.workflow):
            raise ValueError("MSTeams requires an agent, team, or workflow")

    def _get_config(self) -> MSTeamsConfig:
        if self._config is None:
            self._config = MSTeamsConfig.init(
                app_id=self.app_id,
                app_password=self.app_password,
                tenant_id=self.tenant_id,
                request_timeout=self.request_timeout,
            )
        return self._config

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(
            router=self.router,
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            show_reasoning=self.show_reasoning,
            send_user_id_to_context=self.send_user_id_to_context,
            config=self._get_config(),
        )

        return self.router

    async def asend_alert(self, user_id: str, text: str) -> bool:
        """Send to the user's saved personal chat; return False when none can be resolved."""
        entity, entity_type = self._resolve_entity()
        db = getattr(entity, "db", None)
        if not isinstance(db, (BaseDb, AsyncBaseDb)):
            log_warning("MSTeams.asend_alert: entity has no DB configured; cannot resolve user's conversation")
            return False

        entity_id = getattr(entity, "id", None) or getattr(entity, "name", None) or entity_type

        session_filter = dict(
            session_type=_SESSION_DISPATCH[entity_type][0],
            user_id=user_id,
            component_id=entity_id,
            limit=50,
            deserialize=False,
            # created_at, not updated_at: upsert rewrites updated_at on every save,
            # which lets a write to an older session float it above the current one.
            sort_by="created_at",
            sort_order="desc",
        )
        ref = None
        page = 1
        try:
            while not ref:
                if isinstance(db, AsyncBaseDb):
                    result = await db.get_sessions(**session_filter, page=page)  # type: ignore[arg-type]
                else:
                    result = db.get_sessions(**session_filter, page=page)  # type: ignore[arg-type]
                sessions, total = result if isinstance(result, tuple) else (result, len(result))
                for session in sessions:
                    data = session.get("session_data")
                    if isinstance(data, str):
                        data = json.loads(data)
                    ref = extract_conversation_ref(data)
                    if ref:
                        break
                if not sessions or page * 50 >= total:
                    break
                page += 1
        except Exception as e:
            log_warning(f"MSTeams.asend_alert: session lookup failed: {str(e)}")
            return False
        if not ref:
            return False

        config = self._get_config()

        await send_teams_message_async(
            service_url=ref["service_url"],
            conversation_id=ref["conversation_id"],
            message=text,
            config=config,
            bot_identity=ref.get("bot_identity"),
        )
        return True

    def send_alert(self, user_id: str, text: str) -> bool:
        """Blocking twin of :meth:`asend_alert`, for scripts and schedulers."""
        return asyncio.run(self.asend_alert(user_id, text))

    def _resolve_entity(self):
        if self.agent is not None:
            return self.agent, "agent"
        if self.team is not None:
            return self.team, "team"
        return self.workflow, "workflow"
