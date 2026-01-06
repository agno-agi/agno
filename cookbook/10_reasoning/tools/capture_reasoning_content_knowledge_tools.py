"""
Cookbook: Capturing reasoning_content with KnowledgeTools

This example demonstrates how to access and print the reasoning_content
when using KnowledgeTools with URL knowledge, in both streaming and non-streaming modes.
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.tools.knowledge import KnowledgeTools
from agno.vectordb.lancedb import LanceDb, SearchType

# Create a knowledge containing information from a URL
print("Setting up URL knowledge...")
agno_docs = Knowledge(
    # Use LanceDB as the vector database
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="cookbook_knowledge_tools",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)
# Add content to the knowledge
asyncio.run(agno_docs.add_content_async(url="https://www.paulgraham.com/read.html"))
print("Knowledge ready.")


print("\n=== Example 1: Using KnowledgeTools in non-streaming mode ===\n")

# Create agent with KnowledgeTools
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        KnowledgeTools(
            knowledge=agno_docs,
            enable_think=True,
            enable_search=True,
            enable_analyze=True,
            add_instructions=True,
        )
    ],
    instructions=dedent("""\
        You are an expert problem-solving assistant with strong analytical skills! 🧠
        Use the knowledge tools to organize your thoughts, search for information,
        and analyze results step-by-step.
        \
    """),
    markdown=True,
)

# Run the agent (non-streaming) using agent.run() to get the response
print("Running with KnowledgeTools (non-streaming)...")
response = agent.run(
    "What does Paul Graham explain here with respect to need to read?", stream=False
)

# Check reasoning_content from the response
print("\n--- reasoning_content from response ---")
if hasattr(response, "reasoning_content") and response.reasoning_content:
    print("✅ reasoning_content FOUND in non-streaming response")
    print(f"   Length: {len(response.reasoning_content)} characters")
    print("\n=== reasoning_content preview (non-streaming) ===")
    preview = response.reasoning_content[:1000]
    if len(response.reasoning_content) > 1000:
        preview += "..."
    print(preview)
else:
    print("❌ reasoning_content NOT FOUND in non-streaming response")


print("\n\n=== Example 2: Using KnowledgeTools in streaming mode ===\n")

# Create a fresh agent for streaming
streaming_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        KnowledgeTools(
            knowledge=agno_docs,
            enable_think=True,
            enable_search=True,
            enable_analyze=True,
            add_instructions=True,
        )
    ],
    instructions=dedent("""\
        You are an expert problem-solving assistant with strong analytical skills! 🧠
        Use the knowledge tools to organize your thoughts, search for information,
        and analyze results step-by-step.
        \
    """),
    markdown=True,
)

# Process streaming responses and look for the final RunOutput
print("Running with KnowledgeTools (streaming)...")
final_response = None
for event in streaming_agent.run(
    "What does Paul Graham explain here with respect to need to read?",
    stream=True,
    stream_events=True,
):
    # Print content as it streams (optional)
    if hasattr(event, "content") and event.content:
        print(event.content, end="", flush=True)

    # The final event in the stream should be a RunOutput object
    if hasattr(event, "reasoning_content"):
        final_response = event

print("\n\n--- reasoning_content from final stream event ---")
if (
    final_response
    and hasattr(final_response, "reasoning_content")
    and final_response.reasoning_content
):
    print("✅ reasoning_content FOUND in final stream event")
    print(f"   Length: {len(final_response.reasoning_content)} characters")
    print("\n=== reasoning_content preview (streaming) ===")
    preview = final_response.reasoning_content[:1000]
    if len(final_response.reasoning_content) > 1000:
        preview += "..."
    print(preview)
else:
    print("❌ reasoning_content NOT FOUND in final stream event")
