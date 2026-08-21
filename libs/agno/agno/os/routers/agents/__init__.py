from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agno.os.routers.agents.router import get_agent_router

__all__ = ["get_agent_router"]


def __getattr__(name: str) -> Any:
    # Lazy so the pure-pydantic schema modules in this package stay importable
    # without the `os` extra (fastapi); the router is only pulled in when used.
    if name == "get_agent_router":
        from agno.os.routers.agents.router import get_agent_router

        globals()[name] = get_agent_router
        return get_agent_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
