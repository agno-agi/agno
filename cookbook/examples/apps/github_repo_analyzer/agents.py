"""
GitHub Repository Analyzer Agents
"""

import logging
from typing import Optional

import streamlit as st  # Import streamlit for st.error
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.github import GithubTools

# Import prompts - change from relative to direct import
# from .prompts import AGENT_DESCRIPTION, AGENT_INSTRUCTIONS
from prompts import AGENT_DESCRIPTION, AGENT_INSTRUCTIONS


# --- Updated Function for Chat Agent ---
def get_github_chat_agent(repo_name: str, debug_mode: bool = True) -> Optional[Agent]:
    """
    Initialize and return a GitHub chat agent focused on a specific repository,
    with enhanced capabilities for detailed PR code review.

    Args:
        repo_name: The repository name in "owner/repo" format.
        debug_mode: Whether to enable debug mode for tool calls.

    Returns:
        Initialized Agent for chat, or None if initialization fails.
    """
    if not repo_name:
        logging.error("Cannot initialize chat agent without a repository name.")
        return None

    logging.info(f"Initializing chat agent for repository: {repo_name}")
    try:
        # Format the repository name into the description and instructions
        formatted_description = AGENT_DESCRIPTION.format(repo_name=repo_name)
        formatted_instructions = [
            instruction.format(repo_name=repo_name)
            for instruction in AGENT_INSTRUCTIONS
        ]

        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),  # Or your preferred model
            description=formatted_description,
            instructions=formatted_instructions,
            tools=[GithubTools()],  # Ensure GITHUB_TOKEN is set in env
            debug_mode=debug_mode,
            markdown=True,
        )
        logging.info(f"Chat agent for {repo_name} initialized successfully.")
        return agent
    except Exception as e:
        logging.error(
            f"Failed to initialize chat agent for {repo_name}: {e}", exc_info=True
        )
        # Display error in Streamlit UI as well
        st.error(f"Error initializing agent: {e}")
        return None


# --- End Updated Function ---
