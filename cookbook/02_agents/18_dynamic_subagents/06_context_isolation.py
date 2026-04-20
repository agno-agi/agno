"""
Dynamic Subagents — Context Isolation in Action
=================================================

Demonstrates the core value proposition: the orchestrator's context window
stays clean while subagents do the heavy lifting with large tool outputs.

The scenario:
An orchestrator handles a customer support request. It needs to:
1. Query a mock database (returns a large JSON blob)
2. Search a knowledge base (returns a long policy article)
3. Compose a final response from the two summaries

Without subagents: both large outputs land in the orchestrator's context,
inflating every subsequent model call.

With subagents: each heavy task is delegated. The orchestrator's context
only ever sees two short summary strings instead of thousands of tokens.

Prompts to try:
- "Customer CUS-4821: I want to return an item. Check my orders and explain the policy."
- "Customer CUS-0001: What are my recent orders and how do I request a refund?"
"""

import json

from agno.agent import Agent, SubAgentConfig
from agno.models.openai import OpenAIResponses
from agno.tools import Toolkit


# ---------------------------------------------------------------------------
# Mock Tools (simulate large-payload external systems)
# ---------------------------------------------------------------------------
class CustomerDataTools(Toolkit):
    """Simulates a DB call returning a large JSON blob."""

    def __init__(self) -> None:
        super().__init__(name="customer_data")
        self.register(self.get_customer_orders)

    def get_customer_orders(self, customer_id: str) -> str:
        """Fetch all orders for a customer from the database.

        Returns large JSON — typically thousands of tokens in production.
        Always delegate to a subagent via spawn_agent.

        Args:
            customer_id: The customer identifier.

        Returns:
            JSON string of all customer orders.
        """
        orders = [
            {
                "order_id": f"ORD-{1000 + i}",
                "date": f"2024-0{(i % 9) + 1}-{(i % 28) + 1:02d}",
                "items": [f"Product {chr(65 + i % 26)}", f"Product {chr(66 + i % 25)}"],
                "total_usd": round(10.0 + i * 7.3, 2),
                "status": ["delivered", "shipped", "processing"][i % 3],
            }
            for i in range(50)
        ]
        return json.dumps({"customer_id": customer_id, "orders": orders}, indent=2)


class KnowledgeBaseTools(Toolkit):
    """Simulates a knowledge base search returning a long article."""

    def __init__(self) -> None:
        super().__init__(name="knowledge_base")
        self.register(self.search_policy)

    def search_policy(self, query: str) -> str:
        """Search the customer support knowledge base.

        Returns full article text — often thousands of tokens.
        Always delegate to a subagent via spawn_agent.

        Args:
            query: The search query.

        Returns:
            Matching policy article text.
        """
        return (
            "RETURN AND REFUND POLICY (v4.2, effective 2024-01-01)\n\n"
            + "Section 1: Eligibility\n"
            + "Customers may return items within 30 days of delivery. " * 10
            + "\n\nSection 2: Process\n"
            + "To initiate a return, contact support@example.com with your order ID. " * 8
            + "\n\nSection 3: Refund timeline\n"
            + "Refunds are processed within 5-7 business days after the returned item is received. " * 6
            + "\n\nSection 4: Exceptions\n"
            + "Digital goods, perishables, and custom orders are non-refundable. " * 5
        )


# ---------------------------------------------------------------------------
# Create Subagent Template
# ---------------------------------------------------------------------------
subagent_template = Agent(
    model=OpenAIResponses(id="gpt-5.4-mini"),
    tools=[CustomerDataTools(), KnowledgeBaseTools()],
    instructions=(
        "You are a data-processing specialist. Use your tools, extract the "
        "essential facts, and return a concise summary. Be brief — the caller "
        "only needs the key points, not the raw data."
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
orchestrator = Agent(
    name="support_orchestrator",
    model=OpenAIResponses(id="gpt-5.4"),
    enable_dynamic_subagents=True,
    subagent_template=subagent_template,
    subagent_config=SubAgentConfig(
        context_heavy_tools=["get_customer_orders", "search_policy"],
        max_concurrent=2,
    ),
    instructions=(
        "You are a customer support orchestrator. Handle customer requests by:\n"
        "1. Delegating heavy data-fetching via spawn_agent (keeps your context clean)\n"
        "2. Composing a helpful final response from the returned summaries\n\n"
        "Never call get_customer_orders or search_policy directly — always "
        "use spawn_agent so those large payloads stay out of your context."
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    orchestrator.print_response(
        "Customer ID CUS-4821 is asking: 'I placed several orders last month "
        "and want to return one item. Can you check my recent orders and tell me "
        "the return policy?'",
        stream=True,
    )
