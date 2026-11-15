"""
CodeMode - Tools as awaitable calls
===================================

Toolkits passed to `CodeMode(tools=[...])` are bound into the kernel as
handles instead of being listed in the model's tool schema. The handle name is
the toolkit's name with a trailing `_tools` stripped, so `ArcadeTools(name=
"arcade_tools")` becomes `arcade`.

Once a tool call is an `await` expression the model can bind it to a variable,
loop it, filter it, and feed it to the next call without a round trip through
the transcript. The model keeps exactly one tool: `execute`.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import Toolkit
from agno.tools.code import CodeMode


# ---------------------------------------------------------------------------
# A toolkit to bind into the kernel
# ---------------------------------------------------------------------------
class InventoryTools(Toolkit):
    """A stand-in for a real client-backed toolkit."""

    _STOCK = {
        "widget": 42,
        "gasket": 7,
        "flange": 0,
        "bracket": 130,
        "coupling": 18,
    }

    def __init__(self, **kwargs):
        super().__init__(
            name="inventory_tools", tools=[self.stock_level, self.list_parts], **kwargs
        )

    def stock_level(self, part: str) -> int:
        """Return the number of units in stock for one part.

        Args:
            part: The part name, e.g. "widget".
        """
        return self._STOCK.get(part, 0)

    def list_parts(self) -> list:
        """Return every part name we carry."""
        return sorted(self._STOCK)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
code = CodeMode(tools=[InventoryTools()])

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[code],
    instructions="Use the code environment. Loop over tool calls in code rather than one at a time.",
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        agent.print_response(
            "For every part we carry, look up its stock level in one cell, then tell "
            "me which parts are out of stock and what the total inventory is.",
            session_id="code-mode-tools",
        )
    finally:
        code.shutdown()
