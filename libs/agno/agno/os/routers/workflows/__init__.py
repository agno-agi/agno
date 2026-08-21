from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agno.os.routers.workflows.router import get_workflow_router

__all__ = ["get_workflow_router"]


def __getattr__(name: str) -> Any:
    # Lazy so the pure-pydantic schema modules in this package stay importable
    # without the `os` extra (fastapi); the router is only pulled in when used.
    if name == "get_workflow_router":
        from agno.os.routers.workflows.router import get_workflow_router

        globals()[name] = get_workflow_router
        return get_workflow_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
