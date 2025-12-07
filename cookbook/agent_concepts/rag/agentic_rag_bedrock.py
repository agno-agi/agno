"""
Example: Using AWS Bedrock Knowledge Base with Agno Agent

This example demonstrates how to integrate AWS Bedrock Knowledge Base
with an Agno agent for retrieval-augmented generation (RAG).

Prerequisites:
1. AWS credentials configured (via AWS CLI, environment variables, or IAM role)
2. A Bedrock Knowledge Base created and indexed in your AWS account
3. Required packages: pip install agno boto3
"""

from agno.agent import Agent
from agno.knowledge.bedrock import BedrockKnowledgeBase
from agno.models.aws.bedrock import AwsBedrock

# Initialize Bedrock Knowledge Base
knowledge_base = BedrockKnowledgeBase(
    knowledge_base_id="YOUR_KNOWLEDGE_BASE_ID",  # Replace with your KB ID
    region_name="us-west-2",  # Replace with your AWS region
    num_documents=5,  # Number of documents to retrieve per query
)

# Create an agent with Bedrock Knowledge Base
# Option 1: Agentic RAG (default) - model decides when to search
agent_agentic = Agent(
    model=AwsBedrock(id="anthropic.claude-3-5-sonnet-20241022-v2:0"),
    knowledge=knowledge_base,
    # search_knowledge=True is the default
    show_tool_calls=True,
    markdown=False,
    add_references=True,  # Show references used in the response
)

# Option 2: Traditional RAG - always add context to user prompt
agent_traditional = Agent(
    model=AwsBedrock(id="anthropic.claude-3-5-sonnet-20241022-v2:0"),
    knowledge=knowledge_base,
    # Enable RAG by adding context from the `knowledge` to the user prompt.
    add_references=True,
    # Set as False because Agents default to `search_knowledge=True`
    search_knowledge=False,
    markdown=False,
)

# Use the agentic version by default
agent = agent_agentic

# Example usage
if __name__ == "__main__":
    # Test the knowledge base connection
    if knowledge_base.exists():
        print("Successfully connected to Bedrock Knowledge Base")

        # Test direct search first
        print("\n--- Testing direct knowledge base search ---")
        docs = knowledge_base.search(
            "What information do you have available?", num_documents=3
        )
        print(f"Direct search returned {len(docs)} documents")
        for i, doc in enumerate(docs, 1):
            print(f"\nDocument {i}:")
            print(f"Content: {doc.content}")
            print(f"Score: {doc.meta_data.get('score', 'N/A')}")
            print(f"Location: {doc.meta_data.get('location', 'N/A')}")
        print("-" * 50)

        # Test traditional RAG approach first
        print("\n--- Testing Traditional RAG (add_references=True) ---")
        response_traditional = agent_traditional.run(
            "What information do you have available?"
        )
        print(f"Traditional RAG Response: {response_traditional.content}")
        print("-" * 50)

        # Ask a question that should be answered using the knowledge base
        print("\n--- Testing Agentic RAG (search_knowledge=True) ---")
        response = agent.run("What information do you have available?")
        print(f"Agentic RAG Response: {response.content}")
        if (
            hasattr(response, "extra_data")
            and response.extra_data
            and response.extra_data.references
        ):
            print(f"\nReferences used: {len(response.extra_data.references)} queries")

    else:
        print("Failed to connect to Bedrock Knowledge Base")
        print("Please check your knowledge_base_id and AWS credentials")
