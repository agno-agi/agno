from typing import Any, List, Optional

from agno.playground.settings import PlaygroundSettings


class Playground:
    """Compatibility wrapper for the legacy Playground import path.

    Playground was replaced by AgentOS. Importing this wrapper stays lightweight
    for fresh installs, and constructing it delegates to AgentOS with the common
    legacy constructor shape.
    """

    def __new__(
        cls,
        agents: Optional[List[Any]] = None,
        teams: Optional[List[Any]] = None,
        workflows: Optional[List[Any]] = None,
        settings: Optional[PlaygroundSettings] = None,
        api_app: Optional[Any] = None,
        router: Optional[Any] = None,
        **kwargs,
    ):
        from agno.os import AgentOS

        settings = settings or PlaygroundSettings()
        kwargs.setdefault("name", settings.title)

        agent_os = AgentOS(
            agents=agents,
            teams=teams,
            workflows=workflows,
            settings=settings,
            base_app=api_app,
            **kwargs,
        )
        setattr(agent_os, "router", router)
        setattr(agent_os, "api_app", agent_os.base_app)
        return agent_os


__all__ = ["Playground", "PlaygroundSettings"]
