import asyncio
from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.teams.helpers import (
    TeamsConfig,
    extract_conversation_ref,
    send_teams_message_async,
)
from agno.os.interfaces.teams.router import _SESSION_DISPATCH, attach_routes
from agno.team import RemoteTeam, Team
from agno.utils.log import log_warning
from agno.workflow import RemoteWorkflow, Workflow


class MicrosoftTeams(BaseInterface):
    """Microsoft Teams interface for agents, teams, and workflows.

    Exposes two HTTP endpoints under ``prefix`` (default ``/msteams``):
      - ``GET  /status``   — readiness probe
      - ``POST /messages`` — Bot Framework webhook for inbound activities

    Also provides ``send_alert(user_id, text)`` for pushing proactive
    messages to any user who has previously chatted with the bot
    (their conversation reference is stored in ``session.session_data``
    after the first inbound message).
    """

    type = "teams"

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
        app_type: Optional[str] = None,
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
        self.app_type = app_type
        self.request_timeout = request_timeout

        if not (self.agent or self.team or self.workflow):
            raise ValueError("MicrosoftTeams requires an agent, team, or workflow")

    def get_router(self) -> APIRouter:
        """Build and return the FastAPI router mounting the Teams endpoints.

        Called once by AgentOS during interface registration. The returned
        router is later mounted at ``self.prefix``.
        """
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(
            router=self.router,
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            show_reasoning=self.show_reasoning,
            send_user_id_to_context=self.send_user_id_to_context,
            app_id=self.app_id,
            app_password=self.app_password,
            tenant_id=self.tenant_id,
            app_type=self.app_type,
            request_timeout=self.request_timeout,
        )

        return self.router

    # ------------------------------------------------------------------
    # Proactive alerts
    # ------------------------------------------------------------------

    async def send_alert(self, user_id: str, text: str) -> bool:
        """Send a proactive message to a user who previously chatted with the bot.

        Requires:
          - The bound entity (agent/team/workflow) must have a `db` configured.
          - The target `user_id` must have exchanged at least one message with
            the bot (so a conversation reference exists in that user's latest
            session).

        Returns True on success, False when no conversation reference is found
        (silent — callers can log or retry). Raises on transport errors after
        the reference is found.

        Safe to call from anywhere: scheduled jobs, background tasks, other
        request handlers. The bot's HTTP server does NOT need to be serving
        traffic — this only speaks to the Bot Connector API outbound.
        """
        entity, entity_type = self._resolve_entity()
        db = getattr(entity, "db", None)
        if not isinstance(db, (BaseDb, AsyncBaseDb)):
            log_warning("MicrosoftTeams.send_alert: entity has no DB configured; cannot resolve user's conversation")
            return False

        entity_id = getattr(entity, "id", None) or getattr(entity, "name", None) or entity_type

        session_filter = dict(
            session_type=_SESSION_DISPATCH[entity_type][0],
            user_id=user_id,
            component_id=entity_id,
            limit=1,
            sort_by="updated_at",
            sort_order="desc",
        )
        try:
            if isinstance(db, AsyncBaseDb):
                sessions = await db.get_sessions(**session_filter)  # type: ignore[assignment]
            else:
                sessions = db.get_sessions(**session_filter)  # type: ignore[assignment]
        except Exception as e:
            log_warning(f"MicrosoftTeams.send_alert: session lookup failed: {e}")
            return False

        if not sessions:
            return False

        ref = extract_conversation_ref(sessions[0].session_data)  # type: ignore[union-attr]
        if not ref:
            return False

        config = TeamsConfig.init(
            app_id=self.app_id,
            app_password=self.app_password,
            tenant_id=self.tenant_id,
            app_type=self.app_type,
            request_timeout=self.request_timeout,
        )

        await send_teams_message_async(
            service_url=ref["service_url"],
            conversation_id=ref["conversation_id"],
            message=text,
            config=config,
            bot_identity=ref.get("bot_identity"),
        )
        return True

    def send_alert_sync(self, user_id: str, text: str) -> bool:
        """Blocking variant of :meth:`send_alert`. Prefer the async version
        inside coroutines; this exists for scripts and simple schedulers."""
        return asyncio.run(self.send_alert(user_id, text))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_entity(self):
        if self.agent is not None:
            return self.agent, "agent"
        if self.team is not None:
            return self.team, "team"
        return self.workflow, "workflow"
