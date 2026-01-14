from agno.agent import Agent
from agno.knowledge import Knowledge
from agno.models.google import Gemini
from agno.vectordb.moss import Moss

# 1. Initialize Moss VectorDB
# Ensure MOSS_PROJECT_ID and MOSS_PROJECT_KEY are set in your environment
vector_db = Moss(
    index_name="moss-cookbook",
    alpha=0.8,  # Optional: default is 0.6 though alpha = 1.0: pure semantic (embeddings) alpha = 0.0: pure keyword
)

# 2. Create Knowledge Base
knowledge = Knowledge(
    vector_db=vector_db,
)

# 3. Add content to Knowledge Base
knowledge.add_contents(
    [
        {
            "text_content": "How do I track my order? You can track your order by logging into your account.",
            "metadata": {"category": "shipping"},
        },
        {
            "text_content": "What is your return policy? We offer a 34-day return policy for most items.",
            "metadata": {"category": "returns"},
        },
        {
            "text_content": "How can I change my shipping address? Contact our customer service team.",
            "metadata": {"category": "support"},
        },
        {
            "text_content": "whats the shipping address? Its near St. Mark's Square.",
            "metadata": {"category": "support"},
        },
    ]
)

# 4. Create Agent with Knowledge
agent = Agent(
    model=Gemini(id="gemini-2.0-flash-001"),
    knowledge=knowledge,
    search_knowledge=True,
    description="You are a helpful customer support agent. You have access to a knowledge base with company information including shipping addresses and return policies.",
)

# 5. Verify Moss search directly
print("\n Direct Moss Search Test")


results = vector_db.search("What is the shipping address?", limit=1)
if results:
    print(f"Found: {results[0].content}")
else:
    print("No results found in Moss.")

# 6. Query Agent
print("\n--- Agent Query ---")
agent.print_response("What is the shipping address?", markdown=True)
