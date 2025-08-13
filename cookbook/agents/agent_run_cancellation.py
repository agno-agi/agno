"""🛑 Agent Run Cancellation - Stopping Long-Running Tasks

This example shows how to cancel agent runs mid-execution.
Perfect for scenarios where users want to stop long-running tasks like:
- Complex research or analysis 
- Large document processing
- Time-consuming calculations

Run `pip install openai agno` to install dependencies.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Create a research agent that might take a while
research_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Research specialist who performs in-depth analysis",
    instructions=[
        "Provide comprehensive, detailed analysis",
        "Include multiple perspectives and examples",
        "Take your time to be thorough"
    ],
    markdown=True,
)

async def demonstrate_cancellation():
    """Show how to cancel a long-running agent task"""
    
    print("🚀 Starting a comprehensive research task...")
    
    # Start a potentially long-running task
    task = asyncio.create_task(
        research_agent.arun(
            "Write a comprehensive 10,000 word analysis of the entire history "
            "of artificial intelligence, including detailed timelines, key figures, "
            "major breakthroughs, technological evolution, and future predictions."
        )
    )
    
    await asyncio.sleep(0.1)
    
    print("⏹️ Deciding to cancel the task...")
    cancelled = research_agent.cancel_run(reason="User decided to stop")
    print(f"Cancellation requested: {cancelled}")
    
    try:
        result = await task
        print("Task completed:", result.content[:100] + "...")
        print("Note: Task completed before cancellation could take effect")
        print("      (This is normal for fast-completing tasks)")
    except Exception as e:
        from agno.exceptions import RunCancelledException
        if isinstance(e, RunCancelledException):
            print("✅ Task was successfully cancelled!")
        else:
            print(f"Unexpected error: {e}")
    
    print("\n🔬 Demonstrating cancellation mechanism:")
    research_agent._cancel_requested = True
    research_agent._cancel_reason = "Manual test of cancellation"
    
    try:
        research_agent._check_if_cancelled()
        print("❌ Cancellation check failed")
    except Exception as e:
        from agno.exceptions import RunCancelledException
        if isinstance(e, RunCancelledException):
            print("✅ Cancellation mechanism working correctly!")
        else:
            print(f"Unexpected error: {e}")

if __name__ == "__main__":
    asyncio.run(demonstrate_cancellation())