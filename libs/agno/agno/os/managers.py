"""
Managers for AgentOS.

This module provides various manager classes for AgentOS:
- WebSocketManager: WebSocket connection management for real-time streaming
- EventsBuffer: Event buffering for agent/team/workflow reconnection support
- WebSocketHandler: Handler for sending events over WebSocket connections
- SSESubscriberManager: Subscriber management for SSE-based reconnection

These managers are used by agents, teams, and workflows for background WebSocket execution.
"""

import asyncio
import json
from dataclasses import dataclass
from time import time
from typing import Any, Dict, List, Optional, Tuple, Union

from starlette.websockets import WebSocket

from agno.run.agent import RunOutputEvent
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import WorkflowRunOutputEvent
from agno.utils.log import log_debug, log_warning, logger
from agno.utils.serialize import json_serializer


@dataclass
class WebSocketHandler:
    """Generic WebSocket handler for real-time agent/team/workflow events"""

    websocket: Optional[WebSocket] = None

    def format_sse_event(self, json_data: str) -> str:
        """Parse JSON data into SSE-compliant format.

        Args:
            json_data: JSON string containing the event data

        Returns:
            SSE-formatted response with event type and data
        """
        try:
            # Parse the JSON to extract the event type
            data = json.loads(json_data)
            event_type = data.get("event", "message")

            # Format as SSE: event: <event_type>\ndata: <json_data>\n\n
            return f"event: {event_type}\ndata: {json_data}\n\n"
        except (json.JSONDecodeError, KeyError):
            # Fallback to generic message event if parsing fails
            return f"event: message\ndata: {json_data}\n\n"

    async def handle_event(
        self,
        event: Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent],
        event_index: Optional[int] = None,
        run_id: Optional[str] = None,
    ) -> None:
        """Handle an event object - serializes and sends via WebSocket with event_index for reconnection support"""
        if not self.websocket:
            return

        try:
            if hasattr(event, "to_dict"):
                data = event.to_dict()
            elif hasattr(event, "__dict__"):
                data = event.__dict__
            elif isinstance(event, dict):
                data = event
            else:
                data = {"type": "message", "content": str(event)}

            # Add event_index for reconnection support (if provided)
            if event_index is not None:
                data["event_index"] = event_index
            # Only set run_id if not already present in the event data
            # This preserves the agent's own run_id for agent events
            if run_id and "run_id" not in data:
                data["run_id"] = run_id

            await self.websocket.send_text(self.format_sse_event(json.dumps(data, default=json_serializer)))

        except RuntimeError as e:
            if "websocket.close" in str(e).lower() or "already completed" in str(e).lower():
                log_debug("WebSocket closed, event not sent (expected during disconnection)")
            else:
                log_warning(f"Failed to handle WebSocket event: {str(e)}")
        except Exception as e:
            log_warning(f"Failed to handle WebSocket event: {str(e)}")


class WebSocketManager:
    """
    Manages WebSocket connections for agent, team, and workflow runs.

    Handles connection lifecycle, authentication, and message broadcasting
    for real-time event streaming across all execution types.
    """

    active_connections: Dict[str, WebSocket]  # {run_id: websocket}
    authenticated_connections: Dict[WebSocket, bool]  # {websocket: is_authenticated}

    def __init__(
        self,
        active_connections: Optional[Dict[str, WebSocket]] = None,
    ):
        # Store active connections: {run_id: websocket}
        self.active_connections = active_connections or {}
        # Track authentication state for each websocket
        self.authenticated_connections = {}

    async def connect(self, websocket: WebSocket, requires_auth: bool = True):
        """Accept WebSocket connection"""
        await websocket.accept()
        logger.debug("WebSocket connected")

        # Send connection confirmation with auth requirement info
        await websocket.send_text(
            json.dumps(
                {
                    "event": "connected",
                    "message": (
                        "Connected to AgentOS. Please authenticate to continue."
                        if requires_auth
                        else "Connected to AgentOS."
                    ),
                    "requires_auth": requires_auth,
                }
            )
        )

    async def authenticate_websocket(self, websocket: WebSocket):
        """Mark a WebSocket connection as authenticated"""
        self.authenticated_connections[websocket] = True
        logger.debug("WebSocket authenticated")

        # Send authentication confirmation
        await websocket.send_text(
            json.dumps(
                {
                    "event": "authenticated",
                    "message": "Authentication successful. You can now send commands.",
                }
            )
        )

    def is_authenticated(self, websocket: WebSocket) -> bool:
        """Check if a WebSocket connection is authenticated"""
        return self.authenticated_connections.get(websocket, False)

    async def register_websocket(self, run_id: str, websocket: WebSocket):
        """Register a run (agent/team/workflow) with its WebSocket connection"""
        self.active_connections[run_id] = websocket
        logger.debug(f"Registered WebSocket for run_id: {run_id}")

    async def broadcast_to_run(self, run_id: str, message: str):
        """Broadcast a message to the websocket registered for this run (agent/team/workflow)"""
        if run_id in self.active_connections:
            websocket = self.active_connections[run_id]
            try:
                await websocket.send_text(message)
            except Exception as e:
                log_warning(f"Failed to broadcast to run {run_id}: {str(e)}")
                # Remove dead connection
                await self.disconnect_by_run_id(run_id)

    async def disconnect_by_run_id(self, run_id: str):
        """Remove WebSocket connection by run_id"""
        if run_id in self.active_connections:
            websocket = self.active_connections[run_id]
            del self.active_connections[run_id]
            # Clean up authentication state
            if websocket in self.authenticated_connections:
                del self.authenticated_connections[websocket]
            logger.debug(f"WebSocket disconnected for run_id: {run_id}")

    async def disconnect_websocket(self, websocket: WebSocket):
        """Remove WebSocket connection and clean up all associated state"""
        # Remove from authenticated connections
        if websocket in self.authenticated_connections:
            del self.authenticated_connections[websocket]

        # Remove from active connections
        runs_to_remove = [run_id for run_id, ws in self.active_connections.items() if ws == websocket]
        for run_id in runs_to_remove:
            del self.active_connections[run_id]

        logger.debug("WebSocket disconnected and cleaned up")

    async def get_websocket_for_run(self, run_id: str) -> Optional[WebSocket]:
        """Get WebSocket connection for a run (agent/team/workflow)"""
        return self.active_connections.get(run_id)


class EventsBuffer:
    """
    In-memory buffer for events to support WebSocket reconnection.

    Stores recent events for active runs (agents, teams, workflows), allowing clients
    to catch up on missed events when reconnecting after disconnection or page refresh.

    Buffers all event types: RunOutputEvent (agents), TeamRunOutputEvent (teams),
    and WorkflowRunOutputEvent (workflows).
    """

    def __init__(self, max_events_per_run: int = 1000, cleanup_interval: int = 3600):
        """
        Initialize the event buffer.

        Args:
            max_events_per_run: Maximum number of events to store per run (prevents memory bloat)
            cleanup_interval: How long (in seconds) to keep completed runs in buffer
        """
        # Store all event types (WorkflowRunOutputEvent, RunOutputEvent, TeamRunOutputEvent)
        self.events: Dict[str, List[Union[WorkflowRunOutputEvent, RunOutputEvent, TeamRunOutputEvent]]] = {}
        self._next_index: Dict[str, int] = {}  # monotonic event index counter per run
        self.run_metadata: Dict[str, Dict[str, Any]] = {}  # {run_id: {status, last_updated, etc}}
        self.max_events_per_run = max_events_per_run
        self.cleanup_interval = cleanup_interval

    def add_event(self, run_id: str, event: Union[WorkflowRunOutputEvent, RunOutputEvent, TeamRunOutputEvent]) -> int:
        """Add event to buffer for a specific run and return the event index (handles workflow, agent, and team events)"""
        current_time = time()

        if run_id not in self.events:
            self.events[run_id] = []
            self._next_index[run_id] = 0
            self.run_metadata[run_id] = {
                "status": RunStatus.running,
                "created_at": current_time,
                "last_updated": current_time,
            }

        self.events[run_id].append(event)
        self.run_metadata[run_id]["last_updated"] = current_time

        # Monotonic counter — to survive buffer trims
        event_index = self._next_index[run_id]
        self._next_index[run_id] += 1

        # Keep buffer size under control - trim oldest events if exceeded
        if len(self.events[run_id]) > self.max_events_per_run:
            self.events[run_id] = self.events[run_id][-self.max_events_per_run :]
            log_debug(f"Trimmed event buffer for run {run_id} to {self.max_events_per_run} events")

        return event_index

    def get_events(
        self, run_id: str, last_event_index: Optional[int] = None
    ) -> List[Tuple[int, Union[WorkflowRunOutputEvent, RunOutputEvent, TeamRunOutputEvent]]]:
        """
        Get events since the last received event index.

        Args:
            run_id: The run ID (agent/team/workflow)
            last_event_index: Monotonic index of last event received by client (0-based)

        Returns:
            List of (monotonic_index, event) tuples since last_event_index, or all if None
        """
        events = self.events.get(run_id, [])
        if not events:
            return []

        # The buffer may have been trimmed, so list positions don't match event indices.
        # first_index is the monotonic index of the oldest event still in the buffer.
        next_idx = self._next_index.get(run_id, len(events))
        first_index = next_idx - len(events)

        if last_event_index is None:
            # Client has no events, send all with their real indices
            return [(first_index + i, e) for i, e in enumerate(events)]

        # Client wants events after last_event_index
        start_index = last_event_index + 1

        if start_index >= next_idx:
            # Client is caught up
            return []

        if start_index <= first_index:
            # Client is behind the buffer — return everything we have
            return [(first_index + i, e) for i, e in enumerate(events)]

        # Convert monotonic index to list position
        list_offset = start_index - first_index
        return [(start_index + i, e) for i, e in enumerate(events[list_offset:])]

    def get_event_count(self, run_id: str) -> int:
        """Get the current number of events for a run"""
        return len(self.events.get(run_id, []))

    def get_last_index(self, run_id: str) -> int:
        """Get the monotonic index of the last event added for a run.

        Returns -1 if no events have been added for this run.
        Unlike get_event_count(), this survives buffer trims.
        """
        next_idx = self._next_index.get(run_id)
        if next_idx is None or next_idx == 0:
            return -1
        return next_idx - 1

    def set_run_completed(self, run_id: str, status: RunStatus) -> None:
        """Mark a run as completed/cancelled/error for future cleanup"""
        if run_id in self.run_metadata:
            self.run_metadata[run_id]["status"] = status
            self.run_metadata[run_id]["completed_at"] = time()
            log_debug(f"Marked run {run_id} as {status}")

        # Trigger cleanup of old completed runs
        self.cleanup_runs()

    def cleanup_run(self, run_id: str) -> None:
        """Remove buffer for a completed run (called after retention period)"""
        if run_id in self.events:
            del self.events[run_id]
        self._next_index.pop(run_id, None)
        if run_id in self.run_metadata:
            del self.run_metadata[run_id]
        log_debug(f"Cleaned up event buffer for run {run_id}")

    def cleanup_runs(self) -> None:
        """Clean up runs that have been completed for longer than cleanup_interval"""
        current_time = time()
        runs_to_cleanup = []

        for run_id, metadata in self.run_metadata.items():
            # Only cleanup completed runs
            if metadata["status"] in [RunStatus.completed, RunStatus.error, RunStatus.cancelled]:
                completed_at = metadata.get("completed_at", metadata["last_updated"])
                if current_time - completed_at > self.cleanup_interval:
                    runs_to_cleanup.append(run_id)

        for run_id in runs_to_cleanup:
            self.cleanup_run(run_id)

        if runs_to_cleanup:
            log_debug(f"Cleaned up {len(runs_to_cleanup)} old run buffers")

    def get_run_status(self, run_id: str) -> Optional[RunStatus]:
        """Get the status of a run from metadata"""
        metadata = self.run_metadata.get(run_id)
        return metadata["status"] if metadata else None


class SSESubscriberManager:
    """
    Manages asyncio.Queue subscribers for SSE-based reconnection.

    When a client reconnects to a still-running agent/team via the /resume SSE endpoint,
    it registers a Queue here. The response streamer pushes SSE-formatted events to all
    registered queues. A None sentinel signals run completion.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[asyncio.Queue[Optional[tuple[int, str]]]]] = {}

    def subscribe(self, run_id: str) -> "asyncio.Queue[Optional[tuple[int, str]]]":
        """Register a new subscriber queue for a run. Returns the queue."""
        if run_id not in self._subscribers:
            self._subscribers[run_id] = []
        queue: asyncio.Queue[Optional[tuple[int, str]]] = asyncio.Queue()
        self._subscribers[run_id].append(queue)
        log_debug(f"SSE subscriber registered for run {run_id}")
        return queue

    def unsubscribe(self, run_id: str, queue: "asyncio.Queue[Optional[tuple[int, str]]]") -> None:
        """Remove a subscriber queue."""
        if run_id in self._subscribers:
            try:
                self._subscribers[run_id].remove(queue)
            except ValueError:
                pass
            if not self._subscribers[run_id]:
                del self._subscribers[run_id]

    async def publish(self, run_id: str, event_index: int, sse_data: str) -> None:
        """Push an (event_index, sse_data) tuple to all subscriber queues for a run."""
        subscribers = list(self._subscribers.get(run_id, []))
        for queue in subscribers:
            try:
                await queue.put((event_index, sse_data))
            except Exception:
                pass

    async def complete(self, run_id: str) -> None:
        """Signal all subscribers that the run is done by pushing None sentinel."""
        subscribers = list(self._subscribers.get(run_id, []))
        for queue in subscribers:
            try:
                await queue.put(None)
            except Exception:
                pass


# Global manager instances
websocket_manager = WebSocketManager(
    active_connections={},
)

event_buffer = EventsBuffer(
    max_events_per_run=10000,  # Keep last 10000 events per run
    cleanup_interval=1800,  # Clean up completed runs after 30 minutes
)

sse_subscriber_manager = SSESubscriberManager()
