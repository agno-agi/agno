"""
Shared test utilities and helpers for AgentOS system tests.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import jwt

# Must match the secret key in gateway_server.py and remote_server.py
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "test-secret-key-for-system-tests-do-not-use-in-production")
JWT_ALGORITHM = "HS256"

# Test timeout settings
REQUEST_TIMEOUT = 60.0  # seconds

# Expected agents, teams, and workflows
EXPECTED_LOCAL_AGENTS = ["gateway-agent"]
EXPECTED_REMOTE_AGENTS = ["assistant-agent", "researcher-agent", "facts_agent"]
EXPECTED_A2A_AGENTS = ["assistant-agent-2", "researcher-agent-2"]
EXPECTED_ALL_AGENTS = EXPECTED_LOCAL_AGENTS + EXPECTED_REMOTE_AGENTS + EXPECTED_A2A_AGENTS

EXPECTED_LOCAL_TEAMS = ["gateway-team"]
EXPECTED_REMOTE_TEAMS = ["research-team"]
EXPECTED_A2A_TEAMS = ["research-team-2"]
EXPECTED_ALL_TEAMS = EXPECTED_LOCAL_TEAMS + EXPECTED_REMOTE_TEAMS + EXPECTED_A2A_TEAMS

EXPECTED_LOCAL_WORKFLOWS = ["gateway-workflow"]
EXPECTED_REMOTE_WORKFLOWS = ["qa-workflow"]
EXPECTED_A2A_WORKFLOWS = ["qa-workflow-2"]
EXPECTED_ALL_WORKFLOWS = EXPECTED_LOCAL_WORKFLOWS + EXPECTED_REMOTE_WORKFLOWS + EXPECTED_A2A_WORKFLOWS

# Agents to test for session/memory operations (both local and remote)
TEST_AGENTS = ["gateway-agent", "assistant-agent"]


def generate_jwt_token(
    audience: str = "gateway-os",
    user_id: Optional[str] = None,
    scopes: Optional[list] = None,
    expires_in_hours: int = 1,
) -> str:
    """Generate a JWT token for testing.

    Args:
        user_id: The user ID to include in the token
        audience: The audience (AgentOS ID) the token is valid for
        scopes: List of scopes to include in the token
        expires_in_hours: Token expiration time in hours

    Returns:
        str: The generated JWT token
    """
    now = datetime.now(timezone.utc)
    payload = {
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(hours=expires_in_hours),
        "scopes": scopes or ["agent_os:admin"],  # Admin scope by default for tests
    }
    if user_id:
        payload["sub"] = user_id
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def parse_sse_events(content: str) -> List[Dict[str, Any]]:
    """Parse SSE event stream content into a list of event dictionaries.

    Args:
        content: Raw SSE content string

    Returns:
        List of parsed event dictionaries
    """
    events = []
    current_event = {}

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            if current_event:
                events.append(current_event)
                current_event = {}
            continue

        if line.startswith("event:"):
            current_event["event"] = line[6:].strip()
        elif line.startswith("data:"):
            data_str = line[5:].strip()
            try:
                current_event["data"] = json.loads(data_str)
            except json.JSONDecodeError:
                current_event["data"] = data_str

    # Add last event if exists
    if current_event:
        events.append(current_event)

    return events


def validate_agent_stream_events(events: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Validate agent streaming events follow the expected pattern.

    Args:
        events: List of parsed SSE events

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not events:
        return False, "No events received"

    # Find first event with data
    first_event = None
    for event in events:
        if "data" in event and isinstance(event["data"], dict):
            first_event = event
            break

    if not first_event:
        return False, "No valid data events found"

    # Check first event is RunStartedEvent
    first_data = first_event["data"]
    if first_data.get("event") != "RunStarted":
        return False, f"First event should be RunStarted, got {first_data.get('event')}"

    # Find last event with data
    last_event = None
    for event in reversed(events):
        if "data" in event and isinstance(event["data"], dict):
            last_event = event
            break

    if not last_event:
        return False, "No valid last event found"

    # Check last event is RunCompleted
    last_data = last_event["data"]
    if last_data.get("event") != "RunCompleted":
        return False, f"Last event should be RunCompleted, got {last_data.get('event')}"

    # Verify RunCompletedEvent has content
    if "content" not in last_data:
        return False, "RunCompleted missing content field"

    return True, ""


def validate_team_stream_events(events: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Validate team streaming events follow the expected pattern.

    Args:
        events: List of parsed SSE events

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not events:
        return False, "No events received"

    # Find first event with data
    first_event = None
    for event in events:
        if "data" in event and isinstance(event["data"], dict):
            first_event = event
            break

    if not first_event:
        return False, "No valid data events found"

    # Check first event is TeamRunStartedEvent
    first_data = first_event["data"]
    if first_data.get("event") != "TeamRunStarted":
        return False, f"First event should be TeamRunStarted, got {first_data.get('event')}"

    # Find last event with data
    last_event = None
    for event in reversed(events):
        if "data" in event and isinstance(event["data"], dict):
            last_event = event
            break

    if not last_event:
        return False, "No valid last event found"

    # Check last event is TeamRunCompletedEvent
    last_data = last_event["data"]
    if last_data.get("event") != "TeamRunCompleted":
        return False, f"Last event should be TeamRunCompleted, got {last_data.get('event')}"

    # Verify TeamRunCompletedEvent has content
    if "content" not in last_data:
        return False, "TeamRunCompleted missing content field"

    return True, ""


def validate_workflow_stream_events(events: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Validate workflow streaming events follow the expected pattern.

    Args:
        events: List of parsed SSE events

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not events:
        return False, "No events received"

    # Find first event with data
    first_event = None
    for event in events:
        if "data" in event and isinstance(event["data"], dict):
            first_event = event
            break

    if not first_event:
        return False, "No valid data events found"

    # Check first event is WorkflowStartedEvent
    first_data = first_event["data"]
    if first_data.get("event") != "WorkflowStarted":
        return False, f"First event should be WorkflowStarted, got {first_data.get('event')}"

    # Find last event with data
    last_event = None
    for event in reversed(events):
        if "data" in event and isinstance(event["data"], dict):
            last_event = event
            break

    if not last_event:
        return False, "No valid last event found"

    # Check last event is WorkflowCompletedEvent
    last_data = last_event["data"]
    if last_data.get("event") != "WorkflowCompleted":
        return False, f"Last event should be WorkflowCompleted, got {last_data.get('event')}"

    # Verify WorkflowRunCompletedEvent has content
    if "content" not in last_data:
        return False, "WorkflowRunCompleted missing content field"

    return True, ""
