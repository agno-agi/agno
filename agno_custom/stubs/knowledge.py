"""Re-export Knowledge from V2 location and create AgentKnowledge alias."""

from agno.knowledge import Knowledge

# Create alias for V1 AgentKnowledge (renamed to Knowledge in V2)
AgentKnowledge = Knowledge

__all__ = ["Knowledge", "AgentKnowledge"]
