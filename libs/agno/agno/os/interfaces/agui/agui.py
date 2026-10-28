"""Main class for the AG-UI app, used to expose an Agno Agent or Team in an AG-UI compatible format."""

from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.os.interfaces.agui.handlers import validate_subagent_visibility
from agno.os.interfaces.agui.interrupts import subagent_suspension_available, validate_interrupt_outcome
from agno.os.interfaces.agui.router import attach_routes
from agno.os.interfaces.agui.state import SUBAGENT_VISIBILITY_ATTRIBUTED
from agno.os.interfaces.base import BaseInterface
from agno.team import Team
from agno.team.remote import RemoteTeam
from agno.utils.log import log_warning


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
        emit_interrupt_outcome: bool = False,
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
            emit_interrupt_outcome: Whether a paused run's terminal says the run
                is waiting. Off by default, which is the stream this interface
                sent before the interrupt-aware lifecycle existed: the pause
                reaches the client as the pending tool calls this interface can
                show it, and the run terminal carries no outcome, so a pause and
                a completion look the same on it. Two pauses reach it with no
                call to act on, and both are logged rather than passed off
                silently: one whose every pending call carries no tool call id
                or no tool name, none of which can be rendered, and, under the
                default ``subagent_visibility="inline"``, one reported by an
                Agent whose only pending call arrives through the run's active
                requirements, which is not read at all. On, that terminal carries
                ``outcome: {"type": "interrupt", ...}``, one interrupt per
                requirement the run still needs answered, each naming the tool
                call it is bound to where that call had an id of its own, and
                the shape of the answer it wants. Every open requirement is
                carried whichever visibility is set, including one the prompt
                above leaves unread: a client that answered only what it was
                shown would leave the run unresumable. On is also what turns a
                pause no answer could resolve into a failed run rather than a
                prompt, and what closes the lane of a member the run paused
                inside as suspended.
                It is off by default because a client released before that
                lifecycle stops sending its own resume directive the moment it
                sees the structured outcome, which strands the run: turn it on
                for a client that resumes through ``RunAgentInput.resume``.
                Accepting that resume array does not depend on this setting; the
                interface reads it either way.
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
        self.emit_interrupt_outcome = validate_interrupt_outcome(emit_interrupt_outcome)

        # A member the run paused inside is closed as suspended, so a client
        # renders it as waiting rather than done. That outcome came to the
        # protocol later than the interrupt one, so an install with the interrupt
        # types but not this one attributes the interrupt to the member and
        # closes its lane plainly, and says so rather than doing it silently.
        if (
            self.emit_interrupt_outcome
            and self.subagent_visibility == SUBAGENT_VISIBILITY_ATTRIBUTED
            and not subagent_suspension_available()
        ):
            log_warning(
                "AG-UI cannot close a subagent the run paused inside as suspended: the installed "
                "ag_ui.core omits the suspended subagent outcome, so such a member finishes like one "
                "whose work completed. Please upgrade with `pip install -U ag-ui-protocol`."
            )

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(
            router=self.router,
            agent=self.agent,
            team=self.team,
            subagent_visibility=self.subagent_visibility,
            emit_interrupt_outcome=self.emit_interrupt_outcome,
        )

        return self.router

    def get_scope_mappings(self) -> dict:
        # An agent takes precedence over a team, on presence, which is how the
        # routes pick the entity a request runs: a scope naming the other family
        # would authorize something the route never dispatches to.
        family = "agents" if self.agent is not None else "teams"
        return {f"POST {self.prefix}/agui": [f"{family}:run"]}
