"""Vercel sandboxes.

The sandbox runs ``python -I -m agno.sandbox.vercel.guard``, which imports this package first. The
provider and the checkpoint transfer load on first use, so the guest's root guard never loads them or the
Vercel SDK.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agno.sandbox.vercel.sandbox import VercelSandbox
    from agno.sandbox.vercel.transfer import VercelCheckpointTransfer

__all__ = ["VercelCheckpointTransfer", "VercelSandbox"]


def __getattr__(name: str) -> Any:
    if name == "VercelSandbox":
        from agno.sandbox.vercel.sandbox import VercelSandbox

        return VercelSandbox
    if name == "VercelCheckpointTransfer":
        from agno.sandbox.vercel.transfer import VercelCheckpointTransfer

        return VercelCheckpointTransfer
    raise AttributeError(name)
