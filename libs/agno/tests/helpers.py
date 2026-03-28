"""Shared test helpers used across unit, integration, and system test suites."""

import json
from typing import Any, Dict, List


def parse_sse_events(content: str) -> List[Dict[str, Any]]:
    """Parse SSE event stream content into a list of event dictionaries.

    Args:
        content: Raw SSE content string

    Returns:
        List of parsed event dictionaries
    """
    events = []
    current_event: Dict[str, Any] = {}

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
