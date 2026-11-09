"""AgentCore Runtime sandboxes and their checkpoint transport.

The image runs ``python -m agno.sandbox.agentcore.server``, which imports this
package first. The classes load on first use, so the server never loads them, and
running it as a script does not import it a second time.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agno.sandbox.agentcore.sandbox import AgentCoreSandbox
    from agno.sandbox.agentcore.transfer import AGENTCORE_NATIVE_EXCLUSIONS, AgentCoreCheckpointTransfer

__all__ = ["AGENTCORE_NATIVE_EXCLUSIONS", "AgentCoreCheckpointTransfer", "AgentCoreSandbox"]


def __getattr__(name: str) -> Any:
    if name == "AgentCoreSandbox":
        from agno.sandbox.agentcore.sandbox import AgentCoreSandbox

        return AgentCoreSandbox
    if name in ("AgentCoreCheckpointTransfer", "AGENTCORE_NATIVE_EXCLUSIONS"):
        from agno.sandbox.agentcore import transfer

        return getattr(transfer, name)
    raise AttributeError(name)
