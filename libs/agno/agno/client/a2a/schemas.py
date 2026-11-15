"""Agno-friendly schemas for A2A protocol responses.

These schemas provide a simplified, Pythonic interface for working with
A2A protocol responses, abstracting away the JSON-RPC complexity.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Artifact:
    """Artifact from an A2A task (files, images, etc.)."""

    artifact_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    mime_type: Optional[str] = None
    uri: Optional[str] = None
    content: Optional[bytes] = None


@dataclass
class TaskResult:
    """Result from a non-streaming A2A message.

    Attributes:
        task_id: Unique identifier for the task
        context_id: Session/context identifier for multi-turn conversations
        status: Task status ("completed", "failed", "canceled", "input-required", ...)
        content: Text content from the agent's response
        artifacts: List of artifacts (files, images, etc.)
        metadata: Additional metadata from the response
        data: Structured content from the agent's response, when it sent any
    """

    task_id: str
    context_id: str
    status: str
    content: str
    artifacts: List[Artifact] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    data: Optional[Any] = None

    @property
    def is_completed(self) -> bool:
        """Check if task completed successfully."""
        return self.status == "completed"

    @property
    def is_failed(self) -> bool:
        """Check if task failed."""
        return self.status == "failed"

    @property
    def is_canceled(self) -> bool:
        """Check if task was canceled."""
        return self.status == "canceled"

    @property
    def is_input_required(self) -> bool:
        """Check if task is paused, waiting for input."""
        return self.status == "input-required"


@dataclass
class StreamEvent:
    """Event from a streaming A2A message.

    Attributes:
        event_type: Type of event (e.g., "working", "content", "artifact", "tool_call_started", "completed", "failed")
        content: Text content (for content events)
        task_id: Task identifier
        context_id: Session/context identifier
        metadata: Additional event metadata
        is_final: Whether this is the final event in the stream
        data: Structured content, when the event carries any
        status: Task status the event reports ("working", "completed", "failed", ...), when it reports one
    """

    event_type: str
    content: Optional[str] = None
    task_id: Optional[str] = None
    context_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    is_final: bool = False
    data: Optional[Any] = None
    status: Optional[str] = None

    @property
    def is_content(self) -> bool:
        """Check if this is a content event with text."""
        return self.event_type == "content" and self.content is not None

    @property
    def is_started(self) -> bool:
        """Check if this is a task started event."""
        return self.event_type == "started"

    @property
    def is_completed(self) -> bool:
        """Check if this is a task completed event."""
        return self.event_type == "completed"

    @property
    def is_tool_call(self) -> bool:
        """Check if this is a tool call event."""
        return self.event_type in ("tool_call_started", "tool_call_completed")


@dataclass
class AgentCard:
    """Agent capability discovery card.

    Describes the capabilities and metadata of an A2A-compatible agent.

    Attributes:
        name: Name of the agent
        url: URL of the agent's preferred A2A interface
        description: Description of the agent
        version: Version of the agent
        capabilities: Capabilities of the agent (e.g., {"streaming": True})
        metadata: Additional metadata from the card
        interfaces: Interfaces the agent is served on (url, protocolBinding, protocolVersion)
        skills: Skills of the agent (id, name, description, tags)
        security_schemes: Security schemes a client can authenticate with, keyed by scheme name
    """

    name: str
    url: str
    description: Optional[str] = None
    version: Optional[str] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = None
    interfaces: List[Dict[str, Any]] = field(default_factory=list)
    skills: List[Dict[str, Any]] = field(default_factory=list)
    security_schemes: Dict[str, Any] = field(default_factory=dict)
