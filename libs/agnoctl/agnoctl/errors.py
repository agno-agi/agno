"""Error types shared across CLI commands."""

from typing import Optional


class CLIError(Exception):
    """A user-facing failure. Commands catch this, print the message, and exit with exit_code."""

    def __init__(self, message: str, exit_code: int = 1, hint: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.hint = hint

    @property
    def full_message(self) -> str:
        """Message and hint as one line, for per-client result rows in reports."""
        return self.message + ((" " + self.hint) if self.hint else "")


class APIError(CLIError):
    """An AgentOS API call failed."""

    def __init__(self, message: str, status_code: Optional[int] = None, hint: Optional[str] = None):
        super().__init__(message, exit_code=1, hint=hint)
        self.status_code = status_code


class ConflictError(APIError):
    """The AgentOS reported a conflict (e.g. a service account with this name already exists)."""

    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message, status_code=409, hint=hint)
