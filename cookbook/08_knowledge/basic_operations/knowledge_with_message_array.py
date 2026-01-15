"""
Demonstrates using Knowledge with List[Message] input.

When passing a conversation as List[Message] to agent.run(), the knowledge base
is searched using the last user message, and relevant context is automatically
added to the conversation.

Use Cases:
- Multi-turn conversations with knowledge context
- Passing conversation history with system prompts
- API integrations receiving structured message arrays

1. Run: `pip install openai agno lancedb tantivy` to install dependencies
2. Export your OPENAI_API_KEY
3. Run: `python cookbook/08_knowledge/basic_operations/knowledge_with_message_array.py`
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
        table_name="message_array_demo",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Add sample content about a fictional company's policies
knowledge.insert(
    text="""
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
    name="company_policies",
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

    # Example 2: Multi-turn conversation with system prompt
    print("=== Example 2: Multi-turn with System Prompt ===\n")
    messages = [
        Message(role="system", content="You are a helpful customer service agent. Be concise."),
        Message(role="user", content="Hi, I bought something 45 days ago."),
        Message(role="assistant", content="I can help you with that. What would you like to know?"),
        Message(role="user", content="Can I get a refund?"),
    ]
    response = agent.run(messages)
    print(response.content)
    print()

    # Example 3: Using dict format (also supported)
    print("=== Example 3: Dict Format Messages ===\n")
    messages = [
        {"role": "user", "content": "How long does express shipping take?"},
    ]
    response = agent.run(messages)
    print(response.content)
