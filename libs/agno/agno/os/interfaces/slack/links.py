"""Slack members linked to the AgentOS users they act as.

A Slack message carries no AgentOS token, so under authorization the Slack interface has to know which
AgentOS user a member is. With Slack(resolve_user_identity=True) and the AgentOS user directory, a member
is linked on their first message when their confirmed Slack email is the ID of exactly one active user
who has signed in to AgentOS, as an os.agno.com sign-in is. The link is stored, so later messages,
approvals, Stop and Task results read it without calling Slack, and the member is told which user they
now act as. users= still maps members by hand and, when set, is the only mapping.
"""

from typing import Any, Dict, List, Optional

from agno.agents._hitl import db_call
from agno.utils.log import log_debug, log_warning

PROVIDER = "slack"

_LINKED_MESSAGE = "Your messages here now run as `{principal}` on this AgentOS, the account that has your Slack email."


def supports_links(db: Any) -> bool:
    """Whether db stores identity links: the SQLAlchemy backends (PostgreSQL, SQLite, sync or async)."""
    from agno.db.base import AsyncBaseDb, BaseDb

    if isinstance(db, AsyncBaseDb):
        return type(db).get_identity_link is not AsyncBaseDb.get_identity_link
    return isinstance(db, BaseDb) and type(db).get_identity_link is not BaseDb.get_identity_link


class SlackLinks:
    """Reads and writes the Slack links of an AgentOS database (PostgreSQL or SQLite, sync or async)."""

    def __init__(self, db: Any):
        self.db = db

    async def principal(self, team_id: Optional[str], user_id: str) -> Optional[str]:
        """The user a Slack member is linked to, or None.

        Without the workspace (a run stored before it was recorded), a member linked in exactly one
        workspace is found; Slack member IDs are not reused across workspaces.
        """
        if not user_id:
            return None
        if team_id:
            return await db_call(self.db, "get_identity_link", PROVIDER, team_id, user_id)
        links = await db_call(self.db, "list_identity_links", PROVIDER, external_id=user_id)
        return links[0]["principal_id"] if len(links) == 1 else None

    async def slack_user(self, principal_id: str, team_id: Optional[str]) -> Optional[str]:
        """The Slack member linked to principal_id in the workspace, for a run restored after a restart."""
        links = await db_call(self.db, "list_identity_links", PROVIDER, principal_id=principal_id)
        matches = [link["external_id"] for link in links if not team_id or link["tenant"] == team_id]
        return matches[0] if len(matches) == 1 else None

    async def link(self, team_id: str, user_id: str, principal_id: str) -> None:
        await db_call(self.db, "set_identity_link", PROVIDER, team_id, user_id, principal_id)

    async def resolve(self, app: Any, client: Any, team_id: Optional[str], user_id: str) -> Optional[str]:
        """The user a Slack member acts as: their stored link, else a new link by email, else None."""
        principal = await self.principal(team_id, user_id)
        if principal is not None or client is None or not team_id:
            return principal
        principal = await match_member(app, client, team_id, user_id)
        if principal is None:
            return None
        await self.link(team_id, user_id, principal)
        # Told once, so a member matched to someone else's account notices
        try:
            await client.chat_postMessage(channel=user_id, text=_LINKED_MESSAGE.format(principal=principal))
        except Exception as e:
            log_warning(f"Failed to tell a Slack member which AgentOS user they act as: {str(e)}")
        return principal


async def match_member(app: Any, client: Any, team_id: str, user_id: str) -> Optional[str]:
    """The AgentOS user a Slack member is, by email, or None.

    The member must be an active, full member of the workspace the message came from, with an email Slack
    reports as confirmed, and that email must be the ID of exactly one active user in the AgentOS user
    directory: a person who has signed in, whose token named them by email. A guest, a bot, a deleted
    account, a member of another organization in a shared channel, or anyone without a match is not linked.
    """
    from agno.os.middleware.jwt import is_reserved_principal

    user_store = getattr(getattr(app, "state", None), "user_store", None)
    if user_store is None or not user_id:
        return None
    try:
        member = (await client.users_info(user=user_id)).get("user") or {}
    except Exception as e:
        log_debug(f"Slack member lookup failed for {user_id}: {str(e)}")
        return None
    if (
        member.get("deleted")
        or member.get("is_bot")
        or member.get("is_restricted")
        or member.get("is_ultra_restricted")
    ):
        return None
    # A member of another organization in a shared channel is not this workspace's to vouch for
    if member.get("team_id") and member["team_id"] != team_id:
        return None
    email = ((member.get("profile") or {}).get("email") or "").strip()
    if not email or member.get("is_email_confirmed") is not True:
        return None
    matches: List[str] = []
    for candidate in dict.fromkeys((email, email.lower())):
        row: Optional[Dict[str, Any]] = await user_store.aget(candidate)
        if row is not None and not row.get("disabled") and not is_reserved_principal(row["id"]):
            matches.append(row["id"])
    # Two users whose ids differ only in case are ambiguous: neither is chosen
    return matches[0] if len(matches) == 1 else None
