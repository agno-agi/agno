from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.models.runcrate import Runcrate

__all__ = [
    "Runcrate",
]


def __getattr__(name: str):
    if name == "Runcrate":
        from agno.models.runcrate import Runcrate

        return Runcrate
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
