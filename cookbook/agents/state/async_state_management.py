"""
This example demonstrates how to manage state effectively in async operations with Agno agents.
It showcases a real-world scenario where multiple agents work concurrently while maintaining
consistent state across operations.
"""

import asyncio
from typing import Dict, List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools


async def process_task(agent: Agent, query: str, shared_state: Dict[str, List[str]]) -> None:
    """
    Process a task asynchronously while managing state.
    
    Args:
        agent: The Agno agent instance
        query: The query to process
        shared_state: A dictionary to maintain state across async operations
    """
    # Run the query and get response
    response = await agent.arun(query)
    
    # Update shared state
    if "responses" not in shared_state:
        shared_state["responses"] = []
    shared_state["responses"].append(response)


async def main():
    # Initialize shared state
    shared_state: Dict[str, List[str]] = {}
    
    # Create agent with state persistence
    agent = Agent(
        model=Claude(id="claude-3-7-sonnet-latest"),
        db=SqliteDb(session_table="async_state", db_file="tmp/agents.db"),
        tools=[DuckDuckGoTools()],
        add_history_to_context=True,
        num_history_runs=3,
        markdown=True,
    )
    
    # Example queries to process concurrently
    queries = [
        "What are the latest developments in AI?",
        "What are the current trends in renewable energy?",
        "What are the major economic news today?"
    ]
    
    # Create tasks for concurrent processing
    tasks = [process_task(agent, query, shared_state) for query in queries]
    
    # Run tasks concurrently
    await asyncio.gather(*tasks)
    
    # Process final state
    print("\nProcessed Responses:")
    for i, response in enumerate(shared_state["responses"], 1):
        print(f"\nResponse {i}:")
        print("-" * 50)
        print(response)


if __name__ == "__main__":
    # Run the async example
    asyncio.run(main())
