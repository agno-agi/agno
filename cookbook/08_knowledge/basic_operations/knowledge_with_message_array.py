"""
Knowledge with List[Message] Input
===================================
Pass a conversation as List[Message] to agent.run() and the knowledge base
is searched using the last user message.

Useful for multi-turn conversations, API integrations, or passing
conversation history with system prompts.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.vectordb.lancedb import LanceDb, SearchType

# Create a knowledge base with some sample content
knowledge = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="policies",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

knowledge.insert(
    text_content="""
        Refund Policy:
        - Full refunds are available within 30 days of purchase
        - Partial refunds (50%) available between 30-60 days
        - No refunds after 60 days
        - Digital products are non-refundable once downloaded

        Shipping Policy:
        - Standard shipping: 5-7 business days
        - Express shipping: 2-3 business days
        - International shipping: 10-14 business days
    """,
    name="refund_policy",
)

# Create agent with knowledge and auto-context enabled
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge,
    add_knowledge_to_context=True,  # Automatically search and add knowledge context
    markdown=True,
)

if __name__ == "__main__":
    # Example 1: Simple message array
    print("=== Example 1: Simple Message Array ===\n")
    messages = [
        Message(role="user", content="What is your refund policy?"),
    ]
    response = agent.run(messages)
    print(response.content)
    print()

    # Example 2: Multi-turn conversation
    print("=== Example 2: Multi-turn conversation ===\n")
    messages = [
        Message(role="system", content="You are a helpful customer service agent. Be concise."),
        Message(role="user", content="Hi, I bought something 45 days ago."),
        Message(role="assistant", content="I can help you with that. What would you like to know?"),
        Message(role="user", content="Can I get a refund?"),
    ]
    response = agent.run(messages)
    print(response.content)
    print()

    # Example 3: Using dict as input
    print("=== Example 3: Dict Format Messages ===\n")
    messages = [
        {"role": "user", "content": "How long does express shipping take?"},
    ]
    response = agent.run(messages)
    print(response.content)
