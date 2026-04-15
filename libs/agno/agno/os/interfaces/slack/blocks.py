"""Block Kit message builders for interactive Slack components.

Builds structured Block Kit payloads for approval cards, user input forms,
and status updates. These complement the streaming task-card UX with
interactive elements (buttons, modals).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agno.models.response import ToolExecution


def approval_blocks(
    tools: List[ToolExecution],
    approval_id: str,
    agent_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build Block Kit blocks for a tool approval request.

    Shows what the agent wants to do and presents Approve/Reject buttons.
    """
    header = f"*{agent_name}* needs your approval" if agent_name else "Approval needed"

    blocks: List[Dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Action Approval Required"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "divider"},
    ]

    for tool in tools:
        if not tool.is_paused:
            continue

        tool_name = tool.tool_name or "unknown tool"
        args_str = ""
        if tool.tool_args:
            # Truncate long args for readability
            formatted = json.dumps(tool.tool_args, indent=2)
            if len(formatted) > 500:
                formatted = formatted[:500] + "\n..."
            args_str = f"\n```{formatted}```"

        pause_label = "Confirmation"
        if tool.requires_user_input:
            pause_label = "User Input"
        elif tool.external_execution_required:
            pause_label = "External Execution"

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{pause_label}:* `{tool_name}`{args_str}",
                },
            }
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "actions",
            "block_id": f"approval_{approval_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "hitl_approve",
                    "value": approval_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "action_id": "hitl_reject",
                    "value": approval_id,
                },
            ],
        }
    )

    return blocks


def approved_blocks(
    original_blocks: List[Dict[str, Any]],
    user_id: str,
    approved: bool,
) -> List[Dict[str, Any]]:
    """Update approval blocks after user clicks Approve/Reject.

    Replaces the action buttons with a resolved status message.
    """
    updated: List[Dict[str, Any]] = []
    for block in original_blocks:
        # Replace the actions block with a status context
        if block.get("type") == "actions" and block.get("block_id", "").startswith("approval_"):
            updated.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"{'*Approved*' if approved else '*Rejected*'} by <@{user_id}>",
                        }
                    ],
                }
            )
        else:
            updated.append(block)
    return updated


def status_blocks(text: str, status: str = "info") -> List[Dict[str, Any]]:
    """Simple status message block."""
    emoji = {"info": "information_source", "success": "white_check_mark", "error": "x"}.get(
        status, "information_source"
    )
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":{emoji}: {text}"},
        }
    ]
