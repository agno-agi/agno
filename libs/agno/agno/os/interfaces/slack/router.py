from __future__ import annotations

from typing import Any, Optional, Union

from fastapi import APIRouter

from agno.agent import Agent, RemoteAgent

try:
    from agno.os.interfaces.slack.app import AuthorizeFn, mount_slack
    from agno.os.interfaces.slack.config import SlackConfig
except ImportError as e:
    raise ImportError("Slack dependencies not installed. Please install using `pip install 'agno[slack]'`") from e

from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    *,
    authorize: Optional[AuthorizeFn] = None,
    **options: Any,
) -> APIRouter:
    """Attach the Slack webhook routes for one entity to ``router``.

    ``options`` are the ``SlackConfig`` fields. ``authorize`` is forwarded to Bolt and
    replaces its ``auth.test`` bot-identity lookup.
    """
    config = SlackConfig(agent=agent, team=team, workflow=workflow, **options)
    return mount_slack(router, config, authorize=authorize).router
