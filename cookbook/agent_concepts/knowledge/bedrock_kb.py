"""
pip install boto3 agno
"""

from agno.agent import Agent
from agno.knowledge.bedrock import BedrockKnowledgeBase
from agno.models.aws.bedrock import AwsBedrock

# Create a knowledge base from AWS Bedrock Knowledge Base
knowledge_base = BedrockKnowledgeBase(
    knowledge_base_id="YOUR_KNOWLEDGE_BASE_ID",  # Replace with your KB ID
    region_name="us-west-2",  # Replace with your AWS region
    num_documents=5,  # Number of documents to retrieve per query
)

# Create an agent with the knowledge base
agent = Agent(
    model=AwsBedrock(id="anthropic.claude-3-5-sonnet-20241022-v2:0"),
    knowledge=knowledge_base,
    show_tool_calls=True,
    markdown=True,
)

# Use the agent to ask a question and print a response.
agent.print_response("What information do you have available?", markdown=True)
