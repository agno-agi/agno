"""
Advanced: Async Patterns
========================
Using LearningMachine asynchronously.

All LearningMachine operations have async variants:
- build_context() → abuild_context()
- get_tools() → aget_tools()
- process() → aprocess()
- recall() → arecall()

Use async when:
- Building async web applications (FastAPI, etc.)
- Running multiple learning operations concurrently
- Optimizing for high throughput

Run:
    python cookbook/15_learning/advanced/05_async_patterns.py
"""

import asyncio
from typing import List

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with Learning
# ============================================================================
agent = Agent(
    name="Async Learning Agent",
    model=model,
    db=db,
    instructions="You are a helpful assistant with memory.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Basic Async Usage
# ============================================================================
async def demo_basic_async():
    """Basic async agent interaction."""
    print("=" * 60)
    print("Demo: Basic Async Usage")
    print("=" * 60)

    user = "async_demo@example.com"

    # Async response
    print("\n--- Async response ---\n")
    response = await agent.arun(
        "I'm Alex, I work in data engineering. Remember this.",
        user_id=user,
        session_id="async_session",
    )
    print(response.content)


# ============================================================================
# Demo: Concurrent Operations
# ============================================================================
async def demo_concurrent():
    """Run multiple learning operations concurrently."""
    print("\n" + "=" * 60)
    print("Demo: Concurrent Operations")
    print("=" * 60)

    users = [
        "user_a@example.com",
        "user_b@example.com",
        "user_c@example.com",
    ]

    messages = [
        "I'm User A, I prefer Python.",
        "I'm User B, I prefer TypeScript.",
        "I'm User C, I prefer Rust.",
    ]

    # Run all concurrently
    print("\n--- Running 3 requests concurrently ---\n")

    async def process_user(user_id: str, message: str):
        response = await agent.arun(
            message,
            user_id=user_id,
            session_id=f"concurrent_{user_id}",
        )
        return f"{user_id}: Done"

    results = await asyncio.gather(
        *[process_user(user, msg) for user, msg in zip(users, messages)]
    )

    for result in results:
        print(result)


# ============================================================================
# Demo: FastAPI Integration Pattern
# ============================================================================
def demo_fastapi_pattern():
    """Show FastAPI integration pattern."""
    print("\n" + "=" * 60)
    print("Demo: FastAPI Integration Pattern")
    print("=" * 60)
    print("""
from fastapi import FastAPI, Request
from agno.agent import Agent
from agno.learn import LearningMachine

app = FastAPI()

agent = Agent(
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=True,
    ),
)

@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    
    # Use async agent methods
    response = await agent.arun(
        body["message"],
        user_id=body["user_id"],
        session_id=body["session_id"],
        stream=False,
    )
    
    return {"response": response.content}

@app.post("/chat/stream")
async def chat_stream(request: Request):
    body = await request.json()
    
    async def generate():
        async for chunk in agent.arun(
            body["message"],
            user_id=body["user_id"],
            session_id=body["session_id"],
            stream=True,
        ):
            yield chunk.content
    
    return StreamingResponse(generate())
""")


# ============================================================================
# Demo: Async Learning Machine Methods
# ============================================================================
async def demo_learning_machine_async():
    """Direct async LearningMachine methods."""
    print("\n" + "=" * 60)
    print("Demo: Direct LearningMachine Async Methods")
    print("=" * 60)

    learning = agent.learning
    user_id = "direct_async@example.com"
    session_id = "direct_session"

    # Async recall
    print("\n--- Async recall ---")
    profile = await learning.arecall(
        user_id=user_id,
        session_id=session_id,
    )
    print(f"Profile: {profile}")

    # Async build_context
    print("\n--- Async build_context ---")
    context = await learning.abuild_context(
        user_id=user_id,
        session_id=session_id,
        message="Hello",
    )
    print(f"Context length: {len(context)} chars")

    # Async get_tools
    print("\n--- Async get_tools ---")
    tools = await learning.aget_tools(
        user_id=user_id,
        session_id=session_id,
    )
    print(f"Tools available: {len(tools)}")


# ============================================================================
# Best Practices
# ============================================================================
def best_practices():
    """Print async best practices."""
    print("\n" + "=" * 60)
    print("Async Best Practices")
    print("=" * 60)
    print("""
1. USE ASYNC CONSISTENTLY
   - If your app is async, use async throughout
   - Mixing sync/async can cause issues

2. CONCURRENT OPERATIONS
   - Use asyncio.gather() for parallel operations
   - Be mindful of rate limits

3. CONNECTION POOLING
   - Async DB connections need proper pooling
   - Configure pool size appropriately

4. ERROR HANDLING
   - Use try/except in async functions
   - Consider asyncio.TaskGroup for better error handling

5. STREAMING RESPONSES
   - Async is ideal for streaming
   - Use async generators for real-time output

Example:
```python
async def process_batch(users: List[str]):
    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(agent.arun(msg, user_id=user))
            for user in users
        ]
    return [t.result() for t in tasks]
```
""")


# ============================================================================
# Main
# ============================================================================
async def main():
    """Run all async demos."""
    await demo_basic_async()
    await demo_concurrent()
    demo_fastapi_pattern()
    await demo_learning_machine_async()
    best_practices()

    print("\n" + "=" * 60)
    print("✅ All LearningMachine methods have async variants")
    print("   Use for web apps and concurrent operations")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
