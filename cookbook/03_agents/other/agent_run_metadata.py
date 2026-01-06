from datetime import datetime

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions="You are a customer support agent. You help process customer inquiries efficiently.",
    markdown=True,
)

response = agent.run(
    "A customer is reporting that their premium subscription features are not working. They need urgent help as they have a presentation in 2 hours.",
    metadata={
        "ticket_id": "SUP-2024-001234",
        "priority": "high",
        "request_type": "customer_support",
        "sla_deadline": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "escalation_level": 2,
        "customer_tier": "enterprise",
        "department": "customer_success",
        "agent_id": "support_agent_v1",
        "business_impact": "revenue_critical",
        "estimated_resolution_time_minutes": 30,
    },
    debug_mode=True,
)
