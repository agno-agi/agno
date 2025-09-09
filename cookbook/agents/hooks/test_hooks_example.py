#!/usr/bin/env python3
"""
Example demonstrating how to use pre_hook and post_hook with Agno Agent.

This example shows how to:
1. Create sync and async hook functions
2. Set them on an agent
3. See them execute at the right moments in the agent workflow
"""

import asyncio
from typing import Any, Optional, Sequence
from agno.agent import Agent
from agno.media import Audio, Image, Video, File
from agno.models.openai import OpenAIChat
from agno.session import AgentSession
from agno.run.agent import RunOutput


def sync_pre_hook(
    input: Any,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    **kwargs: Any,
) -> None:
    """Synchronous pre-hook function."""
    print("🔄 PRE-HOOK (sync): Called after session is loaded")
    print(f"  Input: {input}")
    print(f"  Session ID: {kwargs.get('session', {}).session_id if kwargs.get('session') else 'None'}")
    print(f"  User ID: {kwargs.get('user_id', 'None')}")
    print(f"  Run ID: {kwargs.get('run_id', 'None')}")
    if images:
        print(f"  Images: {len(images)} image(s)")
    if audio:
        print(f"  Audio: {len(audio)} audio file(s)")
    if videos:
        print(f"  Videos: {len(videos)} video(s)")
    if files:
        print(f"  Files: {len(files)} file(s)")
    print()


async def async_post_hook(
    input: Any,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    **kwargs: Any,
) -> None:
    """Asynchronous post-hook function."""
    print("✅ POST-HOOK (async): Called after output is generated")
    print(f"  Original Input: {input}")
    
    run_response: Optional[RunOutput] = kwargs.get('run_response')
    if run_response:
        print(f"  Response Content: {run_response.content}")
        print(f"  Response Status: {run_response.status}")
        print(f"  Run ID: {run_response.run_id}")
        if run_response.metrics:
            print(f"  Response Time: {run_response.metrics.response_time}s")
    
    session: Optional[AgentSession] = kwargs.get('session')
    if session:
        print(f"  Session ID: {session.session_id}")
    
    user_id = kwargs.get('user_id', 'None')
    print(f"  User ID: {user_id}")
    
    # Simulate some async processing
    await asyncio.sleep(0.1)
    print("  Async processing completed")
    print()


def main():
    """Demonstrate the hooks functionality."""
    print("🚀 Agent Hooks Example")
    print("=" * 50)
    
    # Create an agent with hooks
    agent = Agent(
        name="Hook Demo Agent",
        model=OpenAIChat(id="gpt-4o-mini"),  # You may need to configure your OpenAI API key
        pre_hook=sync_pre_hook,
        post_hook=async_post_hook,
        description="An agent that demonstrates pre and post hooks",
    )
    
    try:
        print("Running agent with hooks...")
        response = agent.run(
            input="Hello! Can you tell me a short joke?",
        )
        
        print("🎉 Agent run completed!")
        print(f"Final Response: {response.content}")
        
    except Exception as e:
        print(f"❌ Error running agent: {e}")
        print("This might be due to missing API keys or other configuration issues.")
        print("The hooks functionality is still working as demonstrated by any hook output above.")


if __name__ == "__main__":
    main()
