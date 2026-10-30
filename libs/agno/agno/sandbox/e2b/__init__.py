"""E2B sandboxes and their checkpoint transport.

Checkpoint jobs inside the sandbox run ``python -m agno.sandbox.e2b._archive``,
which imports this package first. The classes load on first use, so those jobs
never import the E2B SDK.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agno.sandbox.e2b.sandbox import E2BSandbox
    from agno.sandbox.e2b.transfer import E2BCheckpointTransfer

__all__ = ["E2BCheckpointTransfer", "E2BSandbox"]


def __getattr__(name: str) -> Any:
    if name == "E2BSandbox":
        from agno.sandbox.e2b.sandbox import E2BSandbox

        return E2BSandbox
    if name == "E2BCheckpointTransfer":
        from agno.sandbox.e2b.transfer import E2BCheckpointTransfer

        return E2BCheckpointTransfer
    raise AttributeError(name)
