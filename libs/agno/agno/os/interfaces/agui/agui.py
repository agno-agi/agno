"""Main class for the AG-UI app, used to expose an Agno Agent or Team in an AG-UI compatible format."""

from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.os.interfaces.agui.handlers import validate_subagent_visibility
from agno.os.interfaces.agui.router import attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import Team
from agno.team.remote import RemoteTeam


class AGUI(BaseInterface):
    type = "agui"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        prefix: str = "",
        tags: Optional[List[str]] = None,
        subagent_visibility: Optional[str] = None,
    ):
        """
        Initialize the AGUI interface.

        Args:
            agent: The agent to expose via AG-UI
            team: The team to expose via AG-UI
            prefix: Custom prefix for the router (e.g., "/agui/v1", "/chat/public")
            tags: Custom tags for the router (e.g., ["AGUI", "Chat"], defaults to ["AGUI"])
            subagent_visibility: How a Team's members appear on the wire.
                "inline" (the default) streams their work as the team's own, exactly as
                before this option existed. "attributed" adds SUBAGENT_STARTED /
                SUBAGENT_FINISHED / SUBAGENT_ERROR and tags the messages, tool calls
                and reasoning a member produced with its subagent run id, so a client
                can tell them apart per member; state events stay unattributed,
                because a team's session state is one shared document. "hidden"
                withholds the member lifecycle events and the per-event member
                stamps, and streams nothing a member produced as its own work;
                what the client receives is the team's own work, which includes
                the delegation tool call, whose arguments name the member and
                carry the task it was given exactly as the default sends them,
                that call's result, and the team's own reply. Two things a member
                produced also reach the client, a change one of its tools made to
                the session state and a pending tool call it paused on, because
                the first is that shared document and the run cannot continue
                without the second; neither is attributed to the member. A
                member's failure withholds that same identity: the lineage
                events and the per-event stamps stay off the wire and nothing on
                it names the member that failed, while the reason the run
                stopped still reaches the client, because a member's terminal
                can be the run's only account of how it ended and is then read
                as the run's own.
                A single Agent that runs no agent of its own has one lane, and its
                stream is the same under all three settings, a pause included. That
                covers a pending call the pause reports more than once, by carrying
                it on two of its lists at once: every setting prompts such a call
                once per listing, duplicate tool call id and all, because that is
                what the default sends. An agent a context provider runs inside the
                outer run does report that run as its parent, and that inner run is
                the one thing the setting changes here: under "attributed" it
                becomes a lane of its own, under "hidden" its internals are
                withheld, and both read a pending tool call it paused on off the
                outer run's requirements, which the default leaves unread and so
                does not prompt.
        """
        self.agent = agent
        self.team = team
        self.prefix = prefix
        self.tags = tags or ["AGUI"]

        # The missing entity is checked first: it is the more fundamental error,
        # so it is the one reported when both are wrong. Presence, never
        # truthiness, exactly as the routes and the scope mapping decide it.
        if self.agent is None and self.team is None:
            raise ValueError("AGUI requires an agent or a team")

        self.subagent_visibility = validate_subagent_visibility(subagent_visibility)

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(
            router=self.router,
            agent=self.agent,
            team=self.team,
            subagent_visibility=self.subagent_visibility,
        )

        return self.router

    def get_scope_mappings(self) -> dict:
        # An agent takes precedence over a team, on presence, which is how the
        # routes pick the entity a request runs: a scope naming the other family
        # would authorize something the route never dispatches to.
        family = "agents" if self.agent is not None else "teams"
        return {f"POST {self.prefix}/agui": [f"{family}:run"]}
