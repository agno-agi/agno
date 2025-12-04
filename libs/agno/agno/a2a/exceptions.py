"""Exceptions for A2A client operations."""

from typing import Optional


class A2AError(Exception):
    """Base exception for A2A client errors."""

    pass


class A2AConnectionError(A2AError):
    """Failed to connect to A2A server."""

    pass


class A2AAgentNotFoundError(A2AError):
    """Agent not found on the A2A server."""

    def __init__(self, agent_id: str, message: Optional[str] = None):
        self.agent_id = agent_id
        super().__init__(message or f"Agent '{agent_id}' not found on server")


class A2ATaskFailedError(A2AError):
    """A2A task execution failed."""

    def __init__(self, task_id: str, reason: str):
        self.task_id = task_id
        self.reason = reason
        super().__init__(f"Task '{task_id}' failed: {reason}")


class A2ARequestError(A2AError):
    """Invalid A2A request."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"A2A request failed ({status_code}): {detail}")


class A2ATimeoutError(A2AError):
    """A2A request timed out."""

    pass

