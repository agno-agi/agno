"""
Clawdbot Clone - Core Agent

The main AI agent with persistent memory and computer control capabilities.
"""

from pathlib import Path
from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.ollama import Ollama
from agno.models.openai import OpenAIChat
from agno.tools.file import FileTools
from agno.tools.python import PythonTools
from agno.tools.shell import ShellTools
from agno.tools.webbrowser import WebBrowserTools
from agno.tools.websearch import WebSearchTools

from .config import ClawdbotConfig, get_config


def get_model(config: ClawdbotConfig):
    """Get the appropriate model based on configuration."""
    provider = config.model_provider.lower()

    if provider == "anthropic":
        return Claude(id=config.model_id)
    elif provider == "openai":
        return OpenAIChat(id=config.model_id)
    elif provider == "google":
        return Gemini(id=config.model_id)
    elif provider == "ollama":
        return Ollama(id=config.model_id, host=config.ollama_host)
    else:
        raise ValueError(f"Unknown model provider: {provider}")


def get_database(config: ClawdbotConfig):
    """Get the appropriate database based on configuration."""
    if config.use_sqlite:
        # Create directory if needed
        sqlite_path = Path(config.sqlite_path)
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return SqliteDb(db_file=config.sqlite_path)
    else:
        return PostgresDb(db_url=config.database_url)


def get_tools(config: ClawdbotConfig) -> list:
    """Get the list of tools based on configuration."""
    tools = []
    base_path = Path(config.base_directory).resolve()

    if config.enable_shell:
        tools.append(
            ShellTools(
                base_dir=base_path,
                requires_confirmation=config.require_confirmation_for_shell,
            )
        )

    if config.enable_file_access:
        tools.append(
            FileTools(
                base_dir=base_path,
                enable_save_file=True,
                enable_read_file=True,
                enable_list_files=True,
                enable_search_files=True,
                enable_delete_file=True,  # Be careful with this
                requires_confirmation=config.require_confirmation_for_file_write,
            )
        )

    if config.enable_python:
        tools.append(
            PythonTools(
                base_dir=base_path,
                requires_confirmation=True,  # Always confirm Python execution
            )
        )

    if config.enable_web_search:
        tools.append(WebSearchTools())

    if config.enable_web_browser:
        tools.append(WebBrowserTools())

    return tools


def get_system_instructions(config: ClawdbotConfig) -> str:
    """Generate system instructions for the agent."""
    return dedent(f"""
        You are {config.bot_name}, a personal AI assistant that is {config.bot_personality}.

        ## Your Capabilities

        You have full access to the user's computer and can:
        - Execute shell commands to perform system tasks
        - Read, write, and manage files
        - Run Python code for complex computations
        - Search the web for current information
        - Open web pages in the browser

        ## Your Personality

        - Be helpful and proactive - anticipate what the user might need
        - Remember everything about the user - their preferences, past conversations, and interests
        - Be conversational and friendly, but also efficient
        - When you learn something new about the user, acknowledge it naturally
        - If you're unsure about something, ask clarifying questions

        ## Memory Guidelines

        You have persistent memory across sessions. Use it wisely:
        - Remember the user's name, preferences, and important details
        - Track ongoing projects and tasks
        - Note things the user mentions they want to do later
        - Remember past conversations and reference them when relevant

        ## Safety Guidelines

        - Always confirm before executing potentially destructive commands
        - Never access sensitive files without explicit permission
        - Be transparent about what you're doing
        - If a command could cause data loss, warn the user first

        ## Response Style

        - Keep responses concise but informative
        - Use markdown formatting when helpful
        - For code or command output, use code blocks
        - Be proactive in suggesting next steps when appropriate
    """)


def create_clawdbot(
    config: Optional[ClawdbotConfig] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Agent:
    """
    Create the main Clawdbot agent.

    Args:
        config: Configuration object. If None, loads from environment.
        user_id: Optional user ID for multi-user setups.
        session_id: Optional session ID for conversation tracking.

    Returns:
        Configured Agno Agent ready for use.
    """
    if config is None:
        config = get_config()

    model = get_model(config)
    db = get_database(config)
    tools = get_tools(config)
    instructions = get_system_instructions(config)

    agent = Agent(
        name=config.bot_name,
        model=model,
        instructions=instructions,
        tools=tools,
        db=db,
        # Memory settings
        add_history_to_context=True,
        num_history_runs=config.num_history_runs,
        update_memory_on_run=config.enable_memory,
        enable_agentic_memory=config.enable_agentic_memory,
        # Context enrichment
        add_datetime_to_context=True,
        markdown=True,
        # Debug mode (set to True for development)
        debug_mode=False,
    )

    return agent


# Convenience function for quick setup
def quick_start(
    name: str = "Jarvis",
    model: str = "claude-sonnet-4-20250514",
    use_sqlite: bool = True,
) -> Agent:
    """
    Quick start a Clawdbot with minimal configuration.

    Args:
        name: Name for your assistant
        model: Model ID to use
        use_sqlite: Use SQLite for easy local development

    Returns:
        Configured agent ready for use
    """
    config = ClawdbotConfig(
        bot_name=name,
        model_id=model,
        use_sqlite=use_sqlite,
        model_provider="anthropic" if "claude" in model.lower() else "openai",
    )
    return create_clawdbot(config)
