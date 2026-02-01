"""
Clawdbot Clone Configuration

Environment variables and settings for the clawdbot clone.
"""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class ClawdbotConfig(BaseSettings):
    """Configuration for the Clawdbot clone."""

    # Bot identity
    bot_name: str = Field(default="Jarvis", description="Name of your AI assistant")
    bot_personality: str = Field(
        default="helpful, witty, and proactive",
        description="Personality traits for the assistant",
    )

    # Model configuration
    model_provider: str = Field(default="anthropic", description="Model provider: anthropic, openai, google, ollama")
    model_id: str = Field(default="claude-sonnet-4-20250514", description="Model ID to use")

    # For local/private mode with Ollama
    ollama_host: Optional[str] = Field(default=None, description="Ollama host URL for local models")

    # Database configuration
    database_url: str = Field(
        default="postgresql+psycopg://ai:ai@localhost:5532/ai",
        description="PostgreSQL database URL for memory persistence",
    )
    use_sqlite: bool = Field(default=False, description="Use SQLite instead of PostgreSQL (dev only)")
    sqlite_path: str = Field(default="tmp/clawdbot.db", description="SQLite database path")

    # Memory settings
    enable_memory: bool = Field(default=True, description="Enable persistent memory")
    enable_agentic_memory: bool = Field(default=True, description="Let the agent decide what to remember")
    num_history_runs: int = Field(default=5, description="Number of past conversations to include")

    # Tool permissions - what the bot can do
    enable_shell: bool = Field(default=True, description="Allow shell command execution")
    enable_file_access: bool = Field(default=True, description="Allow file read/write")
    enable_python: bool = Field(default=True, description="Allow Python code execution")
    enable_web_search: bool = Field(default=True, description="Allow web searching")
    enable_web_browser: bool = Field(default=True, description="Allow opening browser pages")

    # Safety settings
    require_confirmation_for_shell: bool = Field(
        default=True, description="Require human confirmation for shell commands"
    )
    require_confirmation_for_file_write: bool = Field(
        default=True, description="Require human confirmation for file writes"
    )
    allowed_shell_commands: Optional[list[str]] = Field(
        default=None, description="Whitelist of allowed shell commands (None = all allowed)"
    )
    base_directory: str = Field(default=".", description="Base directory for file operations")

    # Platform tokens (set via environment variables)
    discord_bot_token: Optional[str] = Field(default=None, description="Discord bot token")
    telegram_bot_token: Optional[str] = Field(default=None, description="Telegram bot token")
    slack_bot_token: Optional[str] = Field(default=None, description="Slack bot token")

    # Proactive features
    enable_proactive: bool = Field(default=False, description="Enable proactive messaging (reminders, briefings)")
    morning_briefing_time: str = Field(default="08:00", description="Time for morning briefing (HH:MM)")
    timezone: str = Field(default="UTC", description="Timezone for scheduled tasks")

    class Config:
        env_prefix = "CLAWDBOT_"
        env_file = ".env"
        extra = "ignore"


def get_config() -> ClawdbotConfig:
    """Get the configuration, loading from environment variables."""
    return ClawdbotConfig()


def get_base_path() -> Path:
    """Get the base path for file operations."""
    config = get_config()
    return Path(config.base_directory).resolve()
