"""
AG-UI Agent Definitions

Simple agent definitions that can be used with the AG-UI protocol bridge.
These agents are designed to work with frontend applications like Dojo.
"""
from typing import Dict, Any, Optional
from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import tool


def create_chat_agent() -> Agent:
    """Create an agent for basic chat functionality"""
    return Agent(
        name="chat_agent",
        model=OpenAIChat(id="gpt-4o"),
        instructions="""
        You are a helpful AI assistant that can have natural conversations.
        Respond in a friendly and informative manner.
        """,
        markdown=True,
        debug_mode=True,
    )


def create_generative_ui_agent() -> Agent:
    """Create an agent for generative UI functionality"""
    
    @tool
    def update_steps(steps: list[Dict[str, Any]]) -> str:
        """Update the task steps in the UI"""
        return f"Updated {len(steps)} steps in the plan"
    
    agent = Agent(
        name="generative_ui_agent",
        model=OpenAIChat(id="gpt-4o"),
        instructions="""
        You are an AI assistant that helps create step-by-step plans.
        When asked to help with a task, break it down into clear steps.
        Use the update_steps tool to show progress.
        """,
        tools=[update_steps],
        markdown=True,
        debug_mode=True,
    )
    
    return agent


def create_human_in_loop_agent() -> Agent:
    """Create an agent for human-in-the-loop functionality"""
    agent = Agent(
        name="human_in_loop_agent",
        model=OpenAIChat(id="gpt-4o"),
        instructions="""
        You are an AI assistant that works collaboratively with humans.
        For important actions, always ask for confirmation using frontend tools.
        Explain your reasoning clearly.
        """,
        markdown=True,
        debug_mode=True,
    )
    
    # Frontend tools like confirmAction will be provided by the frontend
    # The agent can call them and execution will be suspended until the user responds
    
    return agent


def create_predictive_state_agent() -> Agent:
    """Create an agent for predictive state updates"""
    
    @tool
    def update_document(content: str, is_preview: bool = True) -> str:
        """Update document content"""
        action = "Previewing" if is_preview else "Applying"
        return f"{action} changes to document"
    
    agent = Agent(
        name="predictive_state_agent",
        model=OpenAIChat(id="gpt-4o"),
        instructions="""
        You are an AI writing assistant that helps improve documents.
        Suggest edits and improvements to text.
        Be creative but maintain the original intent.
        """,
        tools=[update_document],
        markdown=True,
        debug_mode=True,
    )
    
    return agent


def create_shared_state_agent() -> Agent:
    """Create an agent for shared state functionality"""
    
    @tool
    def update_recipe(**kwargs) -> str:
        """Update recipe parameters"""
        updates = [f"{k}: {v}" for k, v in kwargs.items() if v is not None]
        return f"Updated recipe: {', '.join(updates)}" if updates else "No changes"
    
    agent = Agent(
        name="shared_state_agent",
        model=OpenAIChat(id="gpt-4o"),
        instructions="""
        You are a cooking assistant helping users create recipes.
        You can modify recipe parameters like skill level, cooking time,
        ingredients, and instructions. Be helpful and creative.
        """,
        tools=[update_recipe],
        markdown=True,
        debug_mode=True,
    )
    
    return agent


def create_tool_ui_agent() -> Agent:
    """Create an agent for tool-based UI functionality"""
    
    @tool
    def generate_haiku(topic: str) -> dict:
        """Generate a haiku about the topic"""
        # In a real implementation, this would generate actual haikus
        return {
            "topic": topic,
            "haiku": "Nature's gentle voice\nWhispers through the morning dew\nPeace in every breath"
        }
    
    agent = Agent(
        name="tool_ui_agent",
        model=OpenAIChat(id="gpt-4o"),
        instructions="""
        You are a creative haiku generator.
        Create thoughtful, relevant haikus based on user topics.
        Follow the 5-7-5 syllable pattern.
        """,
        tools=[generate_haiku],
        markdown=True,
        debug_mode=True,
    )
    
    return agent


# Export all agent creators
__all__ = [
    "create_chat_agent",
    "create_generative_ui_agent",
    "create_human_in_loop_agent",
    "create_predictive_state_agent",
    "create_shared_state_agent",
    "create_tool_ui_agent",
] 