from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Literal, Union

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

ApprovalPolicy = Union[
    Literal["requester_only", "channel_members", "any_authenticated"],
    Callable[[str, Dict[str, Any]], Awaitable[bool]],
]


async def check_approval_authorization(
    policy: ApprovalPolicy,
    clicker_user_id: str,
    approval: Dict[str, Any],
    slack_client: "AsyncWebClient",
) -> bool:
    if callable(policy):
        return await policy(clicker_user_id, approval)

    if policy == "any_authenticated":
        return True

    if policy == "requester_only":
        slack_meta = get_slack_meta(approval)
        return clicker_user_id == slack_meta.get("requester_slack_user_id")

    if policy == "channel_members":
        slack_meta = get_slack_meta(approval)
        channel = slack_meta.get("channel_id")
        if not channel:
            return False
        return await _is_channel_member(slack_client, channel, clicker_user_id)

    return False


def get_slack_meta(approval: Dict[str, Any]) -> Dict[str, Any]:
    return (approval.get("resolution_data") or {}).get("interface", {}).get("slack", {})


# Mirrors the closure-scoped _db_call in libs/agno/agno/os/routers/approvals/router.py:37.
async def call_db(db: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    fn = getattr(db, method_name, None)
    if fn is None:
        return None
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return fn(*args, **kwargs)


def assert_hitl_backend(db: Any) -> None:
    # v0: simple null check. Deferred for later: MRO-walk base-stub detection
    # so MongoDb/MySQL/Redis adapters (which inherit NotImplementedError stubs
    # for update_approval) fail at startup rather than at first CAS call.
    if db is None:
        raise ValueError("hitl_enabled=True requires the agent/team to have a db configured (SqliteDb or PostgresDb)")


async def _is_channel_member(client: "AsyncWebClient", channel: str, user: str) -> bool:
    # conversations.members paginates; walk until we find the user or exhaust.
    # For very large channels, a caller-supplied callback policy is the escape hatch.
    from agno.utils.log import log_error, log_warning

    cursor = None
    try:
        while True:
            resp = await client.conversations_members(channel=channel, limit=200, cursor=cursor)
            if user in (resp.get("members") or []):
                return True
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return False
    except Exception as exc:
        # Distinguish rate limits from genuine "not a member". 429 should log
        # loudly — fail-closed would otherwise silently deny legitimate approvers.
        slack_error = getattr(getattr(exc, "response", None), "data", None) or {}
        err_code = slack_error.get("error") if isinstance(slack_error, dict) else None
        if err_code == "ratelimited":
            log_error(
                f"channel_members check rate-limited for channel={channel}; user={user} denied. "
                "Consider a callback policy for high-volume channels."
            )
        else:
            log_warning(f"channel_members check failed for channel={channel} user={user}: {err_code or exc}")
        return False
