"""
AgentBay Tools Input Schemas.

Pydantic schemas for validating inputs to AgentBay tools.
Ensures type safety and proper parameter validation.
"""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class RunCodeInput(BaseModel):
    """Input schema for code execution tools."""

    code: str = Field(..., description="Code content to execute")
    sandbox_id: str = Field(
        ..., description="Required. AgentBay session ID from create_sandbox(environment='code_latest')."
    )
    language: str = Field("python", description="Programming language (python or javascript)")
    environment: str = Field("code_latest", description="AgentBay environment image ID")
    timeout: int = Field(60, ge=1, le=300, description="Timeout in seconds (1-300)")

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        """Validate programming language."""
        lang = v.lower().strip()
        if lang not in {"python", "javascript"}:
            raise ValueError("Language must be 'python' or 'javascript'")
        return lang


class FileOperationInput(BaseModel):
    """Input schema for file operations."""

    file_path: str = Field(..., description="File path in cloud environment")
    content: Optional[str] = Field(None, description="File content for write operations")
    environment: str = Field("linux_latest", description="Target environment")


class CommandExecutionInput(BaseModel):
    """Input schema for command execution."""

    command: str = Field(..., description="Shell command to execute")
    sandbox_id: str = Field(
        ..., description="Required. AgentBay session ID from create_sandbox(environment='linux_latest')."
    )
    environment: str = Field("linux_latest", description="Target environment")
    timeout: int = Field(60, ge=1, le=300, description="Timeout in seconds (1-300)")


class DirectoryOperationInput(BaseModel):
    """Input schema for directory operations."""

    directory_path: str = Field(..., description="Directory path to operate on")
    environment: str = Field("linux_latest", description="Target environment")


class BrowserActionInput(BaseModel):
    """Input schema for browser automation."""

    url: Optional[str] = Field(None, description="Target URL for navigation")
    action: str = Field(..., description="Browser action to perform")
    wait_time: int = Field(3, ge=1, le=30, description="Wait time in seconds (1-30)")
    environment: str = Field("browser_latest", description="Browser environment")


class UIAutomationInput(BaseModel):
    """Input schema for UI automation."""

    coordinates: Optional[List[int]] = Field(None, description="Click coordinates [x, y]")
    text: Optional[str] = Field(None, description="Text to type")
    action: str = Field(..., description="UI action to perform")
    environment: str = Field("windows_latest", description="Desktop environment")

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        """Validate coordinates format."""
        if v is not None:
            if len(v) != 2:
                raise ValueError("Coordinates must be [x, y] format")
            if any(coord < 0 for coord in v):
                raise ValueError("Coordinates must be non-negative")
        return v


class SystemInfoInput(BaseModel):
    """Input schema for system information."""

    environment: str = Field("linux_latest", description="Target environment")
    info_type: str = Field("all", description="Type of system info to retrieve")

    @field_validator("info_type")
    @classmethod
    def validate_info_type(cls, v: str) -> str:
        """Validate system info type."""
        valid_types = {"all", "cpu", "memory", "disk", "network", "os"}
        if v.lower() not in valid_types:
            raise ValueError(f"Info type must be one of: {valid_types}")
        return v.lower()


class SessionManagementInput(BaseModel):
    """Input schema for session management."""

    session_action: str = Field(..., description="Session action to perform")
    environment: Optional[str] = Field(None, description="Environment filter")

    @field_validator("session_action")
    @classmethod
    def validate_session_action(cls, v: str) -> str:
        """Validate session action."""
        valid_actions = {"list", "cleanup", "cleanup_all"}
        if v.lower() not in valid_actions:
            raise ValueError(f"Session action must be one of: {valid_actions}")
        return v.lower()


class EnvironmentInput(BaseModel):
    """Input schema for environment selection."""

    environment: str = Field("linux_latest", description="Environment image ID")

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment ID format."""
        # Basic validation for common environment patterns
        valid_prefixes = {
            "linux",
            "ubuntu",
            "centos",
            "debian",
            "alpine",
            "windows",
            "code",
            "browser",
            "desktop",
            "mobile",
        }
        env_lower = v.lower()
        if not any(env_lower.startswith(prefix) for prefix in valid_prefixes):
            import logging

            logging.getLogger(__name__).warning("Using custom environment: %s", v)
        return v


class ContextFileUrlInput(BaseModel):
    """Input schema for context file upload/download URL tools."""

    context_id: str = Field(..., description="Context ID (provided by the application or user)")
    file_path: str = Field(..., description="Path to the file within the context (e.g. /images/figure.png)")


class UploadFileToContextAndGetUrlInput(BaseModel):
    """Input for uploading file from session to context and getting download URL.

    Requires same sandbox_id as run_code that created the file.
    """

    file_path_in_context: str = Field(
        ...,
        description="Path where the file will be stored in the context (e.g. /images/figure.png)",
    )
    session_file_path: str = Field(
        ...,
        description="Path of the file inside the session (e.g. /tmp/figure.png or /workspace/firework.gif)",
    )
    sandbox_id: str = Field(
        ...,
        description="Required. Same AgentBay session ID used in run_code that produced the file (from create_sandbox).",
    )
    environment: Optional[str] = Field(
        None,
        description="Optional. If omitted, toolkit default_environment is used (e.g. code_latest for Code agent).",
    )


class CreateSandboxInput(BaseModel):
    """Input schema for create_sandbox (stack-style sandbox lifecycle)."""

    environment: Optional[str] = Field(
        "linux_latest",
        description="Environment type (e.g. code_latest, linux_latest).",
    )


class ConnectSandboxInput(BaseModel):
    """Input schema for connect_sandbox (bind existing session to environment)."""

    sandbox_id: str = Field(..., description="Existing AgentBay session ID (e.g. s-xxxxx).")
    environment: Optional[str] = Field(
        "linux_latest",
        description="Environment to bind (e.g. code_latest).",
    )


class DeleteSandboxInput(BaseModel):
    """Input schema for delete_sandbox."""

    sandbox_id: str = Field(..., description="Session ID to delete (e.g. s-xxxxx).")


class AgentTaskInput(BaseModel):
    """Input schema for agent task execution."""

    task: str = Field(..., description="Task description in natural language")
    timeout: int = Field(300, ge=1, le=3600, description="Timeout in seconds (1-3600)")
    environment: Optional[str] = Field(None, description="Environment override (optional)")


class MobileAgentTaskInput(AgentTaskInput):
    """Input schema for mobile agent task execution."""

    max_steps: int = Field(50, ge=1, le=200, description="Maximum steps allowed (1-200)")
