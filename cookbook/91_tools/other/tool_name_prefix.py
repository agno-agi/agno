"""
Tool Name Prefix
=============================

Mounts two instances of the same toolkit on one agent. Without a prefix both
register `lookup_order`, so the agent keeps the first and drops the second.
`tool_name_prefix` registers them as `eu_lookup_order` and `us_lookup_order`.
"""

import json

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import Toolkit

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


class OrderTools(Toolkit):
    def __init__(self, region: str, orders: dict, **kwargs):
        self.region = region
        self.orders = orders
        super().__init__(name="orders", tools=[self.lookup_order], **kwargs)

    def lookup_order(self, order_id: str) -> str:
        """
        Looks up an order in this region's store.

        Args:
            order_id: The ID of the order to look up.

        Returns:
            A JSON string with the order status, or an error if it is not found.
        """
        order = self.orders.get(order_id)
        if order is None:
            return json.dumps({"error": f"Order {order_id} not found in {self.region}"})
        return json.dumps({"region": self.region, "order_id": order_id, **order})


eu_orders = OrderTools(
    region="EU", orders={"A100": {"status": "shipped"}}, tool_name_prefix="eu"
)
us_orders = OrderTools(
    region="US", orders={"B200": {"status": "processing"}}, tool_name_prefix="us"
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[eu_orders, us_orders],
    instructions="EU order ids start with A, US order ids start with B.",
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(list(eu_orders.functions), list(us_orders.functions))
    agent.print_response(
        "What is the status of orders A100 and B200?",
        markdown=True,
    )
