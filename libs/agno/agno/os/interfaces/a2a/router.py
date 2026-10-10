"""Async router handling exposing an Agno Agent or Team in an A2A compatible format."""

import hashlib
import json
from typing import Any, Callable, Dict, Optional, Sequence, Union

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRouter
from starlette.routing import BaseRoute, Route
from typing_extensions import List

try:
    from a2a.server.request_handlers.response_helpers import agent_card_to_dict
    from a2a.server.routes import create_jsonrpc_routes
    from a2a.types import AgentCard, AgentProvider, SecurityScheme
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e


from agno.agent import Agent, RemoteAgent
from agno.agent.protocol import AgentProtocol
from agno.os.interfaces.a2a.agent_card import build_agent_card
from agno.os.interfaces.a2a.auth import authorize_a2a_access, authorize_a2a_request
from agno.os.interfaces.a2a.context import A2ACallContextBuilder, A2ARequestContextBuilder, A2ARequestHandler
from agno.os.interfaces.a2a.executor import A2AExecutor
from agno.os.interfaces.a2a.task_store import A2ATaskStore
from agno.os.utils import get_agent_by_id, get_team_by_id, get_workflow_by_id
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


def _get_card_url(request: Request, router: APIRouter, base_url: Optional[str], path: str) -> str:
    """Get the public URL of an entity's A2A endpoint: the configured base URL, else the one the request came in on."""
    resolved_base_url = (base_url or str(request.base_url)).rstrip("/")
    return f"{resolved_base_url}{router.prefix}{path}"


def _get_card_response(request: Request, agent_card: AgentCard) -> Response:
    """Get the response for an Agent Card, with an ETag and a 304 when the client already holds this card."""
    card_data = agent_card_to_dict(agent_card)
    etag = f'"{hashlib.sha256(json.dumps(card_data, sort_keys=True).encode()).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(content=card_data, headers={"ETag": etag})


def _build_a2a_endpoint(endpoint: Callable, resource_type: str, entity: Any) -> Callable:
    """Build the route handler of an entity's A2A endpoint: authorize the request, then hand it to the A2A server."""

    async def a2a_endpoint(request: Request):
        await authorize_a2a_request(request, resource_type, entity)
        return await endpoint(request)

    return a2a_endpoint


def _attach_a2a_endpoint(
    router: APIRouter,
    routes: Sequence[BaseRoute],
    operation_id: str,
    resource_type: str,
    entity: Any,
) -> None:
    """Attach the A2A server routes to the router as API routes, so they are served and documented with it."""
    for route in routes:
        if isinstance(route, Route) and route.methods:
            router.add_api_route(
                route.path,
                _build_a2a_endpoint(route.endpoint, resource_type, entity),
                methods=sorted(method for method in route.methods if method != "HEAD"),
                operation_id=operation_id,
                name=operation_id,
                description="Send an A2A request to an Agno Agent, Team or Workflow. The A2A method is carried in the JSON-RPC body. "
                "Optional: Pass user ID via X-User-ID header (recommended) or 'userId' in params.message.metadata.",
                responses={
                    403: {"description": "Access denied"},
                    404: {"description": "Session not found"},
                },
            )
        else:
            router.routes.append(route)


def attach_routes(
    router: APIRouter,
    agents: Optional[List[Union[Agent, RemoteAgent, AgentProtocol]]] = None,
    teams: Optional[List[Union[Team, RemoteTeam]]] = None,
    workflows: Optional[List[Union[Workflow, RemoteWorkflow]]] = None,
    base_url: Optional[str] = None,
    security_schemes: Optional[Dict[str, SecurityScheme]] = None,
    enable_v0_3_compat: bool = True,
    request_handlers: Optional[Dict[str, Any]] = None,
    provider: Optional[AgentProvider] = None,
    documentation_url: Optional[str] = None,
    icon_url: Optional[str] = None,
) -> APIRouter:
    if agents is None and teams is None and workflows is None:
        raise ValueError("Agents, Teams, or Workflows are required to setup the A2A interface.")

    context_builder = A2ACallContextBuilder()
    # Request handlers are kept by endpoint, so routes built again reuse the handler that holds the running tasks
    request_handlers = request_handlers if request_handlers is not None else {}

    # ============= AGENTS =============
    @router.get("/agents/{id}/.well-known/agent-card.json")
    async def get_agent_card(request: Request, id: str):
        await authorize_a2a_access(request, "agents", id, "read")
        agent = get_agent_by_id(id, agents, create_fresh=True)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        agent_card = build_agent_card(
            agent,
            url=_get_card_url(request, router, base_url, f"/agents/{agent.id}"),
            security_schemes=security_schemes,
            enable_v0_3_compat=enable_v0_3_compat,
            provider=provider,
            documentation_url=documentation_url,
            icon_url=icon_url,
        )
        return _get_card_response(request, agent_card)

    for agent in agents or []:
        # An entity passed only to the interface has no id yet
        if getattr(agent, "id", None) is None and hasattr(agent, "set_id"):
            agent.set_id()
        agent_id = getattr(agent, "id", None)
        if not agent_id:
            continue
        agent_handler = request_handlers.get(f"agents/{agent_id}")
        if agent_handler is None:
            agent_task_store = A2ATaskStore(entity_type="agent", entity=agent)
            agent_handler = A2ARequestHandler(
                agent_executor=A2AExecutor(
                    entity_type="agent", entity_id=agent_id, agents=agents, task_store=agent_task_store
                ),
                task_store=agent_task_store,
                agent_card=build_agent_card(agent, url=f"{router.prefix}/agents/{agent_id}"),
                request_context_builder=A2ARequestContextBuilder(task_store=agent_task_store),
            )
            request_handlers[f"agents/{agent_id}"] = agent_handler
        _attach_a2a_endpoint(
            router,
            create_jsonrpc_routes(
                agent_handler,
                rpc_url=f"/agents/{agent_id}",
                context_builder=context_builder,
                enable_v0_3_compat=enable_v0_3_compat,
            ),
            operation_id=f"a2a_agent_{agent_id}",
            resource_type="agents",
            entity=agent,
        )

    # ============= TEAMS =============
    @router.get("/teams/{id}/.well-known/agent-card.json")
    async def get_team_card(request: Request, id: str):
        await authorize_a2a_access(request, "teams", id, "read")
        team = get_team_by_id(id, teams, create_fresh=True)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        agent_card = build_agent_card(
            team,
            url=_get_card_url(request, router, base_url, f"/teams/{team.id}"),
            security_schemes=security_schemes,
            enable_v0_3_compat=enable_v0_3_compat,
            provider=provider,
            documentation_url=documentation_url,
            icon_url=icon_url,
        )
        return _get_card_response(request, agent_card)

    for team in teams or []:
        # An entity passed only to the interface has no id yet
        if getattr(team, "id", None) is None and hasattr(team, "set_id"):
            team.set_id()
        team_id = getattr(team, "id", None)
        if not team_id:
            continue
        team_handler = request_handlers.get(f"teams/{team_id}")
        if team_handler is None:
            team_task_store = A2ATaskStore(entity_type="team", entity=team)
            team_handler = A2ARequestHandler(
                agent_executor=A2AExecutor(
                    entity_type="team", entity_id=team_id, teams=teams, task_store=team_task_store
                ),
                task_store=team_task_store,
                agent_card=build_agent_card(team, url=f"{router.prefix}/teams/{team_id}"),
                request_context_builder=A2ARequestContextBuilder(task_store=team_task_store),
            )
            request_handlers[f"teams/{team_id}"] = team_handler
        _attach_a2a_endpoint(
            router,
            create_jsonrpc_routes(
                team_handler,
                rpc_url=f"/teams/{team_id}",
                context_builder=context_builder,
                enable_v0_3_compat=enable_v0_3_compat,
            ),
            operation_id=f"a2a_team_{team_id}",
            resource_type="teams",
            entity=team,
        )

    # ============= WORKFLOWS =============
    @router.get("/workflows/{id}/.well-known/agent-card.json")
    async def get_workflow_card(request: Request, id: str):
        await authorize_a2a_access(request, "workflows", id, "read")
        workflow = get_workflow_by_id(id, workflows, create_fresh=True)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        agent_card = build_agent_card(
            workflow,
            url=_get_card_url(request, router, base_url, f"/workflows/{workflow.id}"),
            security_schemes=security_schemes,
            enable_v0_3_compat=enable_v0_3_compat,
            provider=provider,
            documentation_url=documentation_url,
            icon_url=icon_url,
        )
        return _get_card_response(request, agent_card)

    for workflow in workflows or []:
        # An entity passed only to the interface has no id yet
        if getattr(workflow, "id", None) is None and hasattr(workflow, "set_id"):
            workflow.set_id()
        workflow_id = getattr(workflow, "id", None)
        if not workflow_id:
            continue
        workflow_handler = request_handlers.get(f"workflows/{workflow_id}")
        if workflow_handler is None:
            workflow_task_store = A2ATaskStore(entity_type="workflow", entity=workflow)
            workflow_handler = A2ARequestHandler(
                agent_executor=A2AExecutor(
                    entity_type="workflow", entity_id=workflow_id, workflows=workflows, task_store=workflow_task_store
                ),
                task_store=workflow_task_store,
                agent_card=build_agent_card(workflow, url=f"{router.prefix}/workflows/{workflow_id}"),
                request_context_builder=A2ARequestContextBuilder(task_store=workflow_task_store),
            )
            request_handlers[f"workflows/{workflow_id}"] = workflow_handler
        _attach_a2a_endpoint(
            router,
            create_jsonrpc_routes(
                workflow_handler,
                rpc_url=f"/workflows/{workflow_id}",
                context_builder=context_builder,
                enable_v0_3_compat=enable_v0_3_compat,
            ),
            operation_id=f"a2a_workflow_{workflow_id}",
            resource_type="workflows",
            entity=workflow,
        )

    return router
