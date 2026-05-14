"""Main class for the Anthropic interface.

Exposes an Agno Agent or Team behind an Anthropic Messages API compatible HTTP surface
(`/v1/messages`, `/v1/messages/count_tokens`, `/v1/models`). The Anthropic Python SDK
and tools like Claude Code (configured via `ANTHROPIC_BASE_URL`) can call the Agno
agent as if it were the Anthropic API.
"""

from __future__ import annotations

from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.anthropic.router import attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import RemoteTeam, Team


class AnthropicInterface(BaseInterface):
    type = "anthropic"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        prefix: str = "",
        tags: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        advertised_model_ids: Optional[List[str]] = None,
    ) -> None:
        """Initialize the Anthropic interface.

        Args:
            agent: The agent to expose behind the Anthropic Messages API.
            team: The team to expose behind the Anthropic Messages API.
            prefix: URL prefix for the router (e.g. "" to mount endpoints at /v1/messages,
                or "/anthropic" to mount them at /anthropic/v1/messages).
            tags: OpenAPI tags for the router (defaults to ["Anthropic"]).
            api_key: Static API key clients must present in the `x-api-key` or
                `Authorization: Bearer <key>` header. Falls back to the
                `AGNO_ANTHROPIC_INTERFACE_API_KEY` env var. If neither is set, auth is
                disabled (development mode).
            default_model: Model id returned in responses when the client omits one.
                Defaults to the agent/team's configured model id.
            advertised_model_ids: Model ids returned by `GET /v1/models`. Each id should
                start with `claude` or `anthropic` so Claude Code's gateway discovery
                accepts it. Defaults to `["claude-agno-<agent_id>"]`.
        """
        self.agent = agent
        self.team = team
        self.prefix = prefix
        self.tags = tags or ["Anthropic"]
        self.api_key = api_key
        self.default_model = default_model
        self.advertised_model_ids = advertised_model_ids

        if not (self.agent or self.team):
            raise ValueError("AnthropicInterface requires an agent or a team")

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore[arg-type]
        self.router = attach_routes(
            router=self.router,
            agent=self.agent,
            team=self.team,
            api_key=self.api_key,
            default_model=self.default_model,
            advertised_model_ids=self.advertised_model_ids,
        )
        return self.router
