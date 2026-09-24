"""Main class for the Anthropic interface.

Exposes one or more Agno Agents/Teams behind an Anthropic Messages API compatible
HTTP surface (`/v1/messages`, `/v1/messages/count_tokens`, `/v1/models`). The
Anthropic Python SDK and tools like Claude Code (configured via
`ANTHROPIC_BASE_URL`) can call the registered agents/teams as if they were
distinct Anthropic models.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.anthropic.router import RunnerLike, attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import RemoteTeam, Team


def _normalize_model_id(value: str) -> str:
    """Make a model id Claude-Code-discovery-friendly.

    Claude Code's gateway discovery filters models whose id starts with
    `claude` or `anthropic`. We lower-case, replace whitespace with hyphens,
    and prefix with `claude-agno-` when the id does not already match.
    """
    slug = str(value).strip().lower().replace(" ", "-")
    if slug.startswith("claude") or slug.startswith("anthropic"):
        return slug
    return f"claude-agno-{slug}"


def _runner_id(runner: RunnerLike) -> str:
    """Pick a stable id for a runner — agent.id, team.id, or name."""
    return (
        getattr(runner, "id", None)
        or getattr(runner, "agent_id", None)
        or getattr(runner, "team_id", None)
        or getattr(runner, "name", None)
        or "runner"
    )


def _runner_name(runner: RunnerLike) -> str:
    return str(getattr(runner, "name", None) or _runner_id(runner))


class AnthropicInterface(BaseInterface):
    type = "anthropic"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        agents: Optional[List[Union[Agent, RemoteAgent]]] = None,
        teams: Optional[List[Union[Team, RemoteTeam]]] = None,
        prefix: str = "/anthropic",
        tags: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        advertised_model_ids: Optional[List[str]] = None,
    ) -> None:
        """Initialize the Anthropic interface.

        Args:
            agent: A single agent to expose. Convenience for `agents=[agent]`.
            team: A single team to expose. Convenience for `teams=[team]`.
            agents: List of agents to expose. Each is advertised as a distinct
                model id (`claude-agno-<agent.id>`). Requests are dispatched
                based on the `model` field of the Anthropic request.
            teams: List of teams to expose. Same semantics as `agents`.
            prefix: URL prefix for the router. Defaults to "/anthropic" so
                endpoints land at `/anthropic/v1/messages` etc. Use "" to
                mount at the root.
            tags: OpenAPI tags for the router (defaults to ["Anthropic"]).
            api_key: Static API key clients must present in the `x-api-key` or
                `Authorization: Bearer <key>` header. Falls back to the
                `AGNO_ANTHROPIC_INTERFACE_API_KEY` env var. If neither is set,
                auth is disabled (development mode).
            default_model: Model id returned in responses when the client
                omits `model` and the registry has more than one entry. Must
                match one of the registered model ids.
            advertised_model_ids: Only meaningful when a single agent or team
                is supplied. Overrides the auto-derived model id(s) used in
                `GET /v1/models` and for dispatch.
        """
        self.agent = agent
        self.team = team
        self.agents = agents
        self.teams = teams
        self.prefix = prefix
        self.tags = tags or ["Anthropic"]
        self.api_key = api_key
        self.default_model = default_model
        self.advertised_model_ids = advertised_model_ids

        if not (agent or team or agents or teams):
            raise ValueError("AnthropicInterface requires at least one agent or team")

        self.runners, self.display_names = self._build_registry()

    def _build_registry(self) -> tuple[Dict[str, RunnerLike], Dict[str, str]]:
        runners: Dict[str, RunnerLike] = {}
        names: Dict[str, str] = {}

        singleton_runners: List[RunnerLike] = []
        if self.agent is not None:
            singleton_runners.append(self.agent)
        if self.team is not None:
            singleton_runners.append(self.team)

        # For singletons, allow `advertised_model_ids` to override the
        # auto-derived id. When the user supplies multiple ids for a single
        # runner, every id maps to the same runner (model aliasing).
        if singleton_runners and self.advertised_model_ids:
            for runner in singleton_runners:
                for model_id in self.advertised_model_ids:
                    runners[model_id] = runner
                    names[model_id] = _runner_name(runner)
        else:
            for runner in singleton_runners:
                model_id = _normalize_model_id(_runner_id(runner))
                runners[model_id] = runner
                names[model_id] = _runner_name(runner)

        for runner in self.agents or []:
            model_id = _normalize_model_id(_runner_id(runner))
            runners[model_id] = runner
            names[model_id] = _runner_name(runner)

        for runner in self.teams or []:
            model_id = _normalize_model_id(_runner_id(runner))
            runners[model_id] = runner
            names[model_id] = _runner_name(runner)

        if self.default_model and self.default_model not in runners:
            raise ValueError(
                f"default_model={self.default_model!r} is not registered. "
                f"Available: {sorted(runners)}"
            )

        return runners, names

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore[arg-type]
        self.router = attach_routes(
            router=self.router,
            runners=self.runners,
            display_names=self.display_names,
            api_key=self.api_key,
            default_model=self.default_model,
        )
        return self.router
