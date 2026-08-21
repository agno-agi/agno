from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agno.os.routers.traces.traces import get_traces_router

__all__ = ["get_traces_router"]


def __getattr__(name: str) -> Any:
    # Lazy so the pure-pydantic schema modules in this package stay importable
    # without the `os` extra (fastapi); the router is only pulled in when used.
    if name == "get_traces_router":
        from agno.os.routers.traces.traces import get_traces_router

        globals()[name] = get_traces_router
        return get_traces_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
