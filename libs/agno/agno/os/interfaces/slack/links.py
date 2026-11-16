"""Slack accounts linked to AgentOS principals.

A person links their own account in two steps, and each step proves one side:

1. Signed in to AgentOS (any frontend, or curl with their token), they ask
   ``POST /identity-links/slack/codes`` for a one-time code. The token proves the principal.
2. They send ``link <code>`` to the bot in a direct message. Slack's signed event proves the
   member and workspace.

The code is the only thing that crosses between the two, so it is short-lived, works once, and
only in a direct message: a code posted anywhere else is voided. Nothing is matched by email,
so this works with any identity provider.
"""

import hashlib
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from agno.agents._hitl import db_call

PROVIDER = "slack"
CODE_TTL_SECONDS = 10 * 60
# No 0/O or 1/I, so a code read off a screen is typed right
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 10
# Voiding a code redeems it at a time every code has expired by
_VOID_AT = 2**62
_COMMAND = re.compile(r"^\s*(link|unlink)\b\s*([A-Za-z0-9-]*)\s*$", re.IGNORECASE)


def _hash(code: str) -> str:
    # Dashes and case are cosmetic: "abcd-efgh-jk" is the same code as "ABCDEFGHJK"
    normalized = code.replace("-", "").strip().upper()
    return hashlib.sha256(normalized.encode()).hexdigest()


def parse_command(text: str) -> Optional[Tuple[str, str]]:
    """("link", code) or ("unlink", "") for a link command, else None."""
    match = _COMMAND.match(text or "")
    if match is None:
        return None
    return match.group(1).lower(), match.group(2)


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

    async def issue_code(self, principal_id: str) -> Tuple[str, int]:
        """A new one-time code for principal_id and when it expires; it voids the principal's earlier code."""
        code = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
        expires_at = int(time.time()) + CODE_TTL_SECONDS
        await db_call(self.db, "create_identity_link_code", PROVIDER, principal_id, _hash(code), expires_at)
        return f"{code[:5]}-{code[5:]}", expires_at

    async def redeem(self, code: str, team_id: str, user_id: str) -> Optional[str]:
        """Link the Slack member to the code's principal; the principal, or None for an unknown or expired code."""
        return await db_call(
            self.db, "redeem_identity_link_code", PROVIDER, _hash(code), team_id, user_id, int(time.time())
        )

    async def void(self, code: str) -> None:
        """Spend a code without linking anyone, e.g. one posted where others could read it."""
        await db_call(self.db, "redeem_identity_link_code", PROVIDER, _hash(code), "", "", _VOID_AT)

    async def principal(self, team_id: Optional[str], user_id: str) -> Optional[str]:
        """The principal a Slack member is linked to.

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
        links = await self.links(principal_id)
        matches = [link["external_id"] for link in links if not team_id or link["tenant"] == team_id]
        return matches[0] if len(matches) == 1 else None

    async def links(self, principal_id: str) -> List[Dict[str, Any]]:
        return await db_call(self.db, "list_identity_links", PROVIDER, principal_id=principal_id)

    async def unlink(
        self, principal_id: Optional[str] = None, team_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> int:
        return await db_call(
            self.db, "delete_identity_links", PROVIDER, principal_id=principal_id, tenant=team_id, external_id=user_id
        )
