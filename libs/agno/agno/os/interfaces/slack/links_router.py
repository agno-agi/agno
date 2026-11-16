"""Routes a signed-in person uses to link their own Slack account.

Mounted by AgentOS outside the Slack interface's prefix: the Slack routes skip AgentOS
authentication (Slack signs them), and these must not, since the caller's token is what proves
the principal a Slack account is linked to.
"""

from typing import List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agno.os.interfaces.slack.links import SlackLinks


class SlackLinkCode(BaseModel):
    code: str = Field(..., description="One-time code; send `link <code>` to the Slack bot in a direct message")
    expires_at: int = Field(..., description="Unix time after which the code no longer works")
    instructions: str = Field(..., description="What to do with the code")


class SlackLink(BaseModel):
    team_id: str = Field(..., description="Slack workspace ID")
    slack_user_id: str = Field(..., description="Slack member ID")
    created_at: int = Field(..., description="Unix time the account was linked")


class SlackLinkList(BaseModel):
    links: List[SlackLink] = Field(..., description="The caller's linked Slack accounts")


class SlackUnlinked(BaseModel):
    unlinked: int = Field(..., description="Number of Slack accounts unlinked")


def _caller(request: Request) -> str:
    """The signed-in principal; server and scheduler identities cannot link a Slack account."""
    from agno.os.middleware.jwt import is_reserved_principal

    principal = getattr(request.state, "user_id", None)
    if not isinstance(principal, str) or not principal:
        raise HTTPException(401, "Sign in to AgentOS to link a Slack account")
    if is_reserved_principal(principal):
        raise HTTPException(403, "Only a person can link a Slack account")
    return principal


def get_slack_links_router(links: SlackLinks, prefix: str = "/identity-links/slack") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["Slack"])

    @router.post(
        "/codes",
        status_code=201,
        response_model=SlackLinkCode,
        operation_id="create_slack_link_code",
        summary="Create a Slack link code",
    )
    async def create_code(request: Request) -> SlackLinkCode:
        """A one-time code that links the Slack account it is sent from to the caller. It voids the caller's
        earlier code and expires after 10 minutes."""
        code, expires_at = await links.issue_code(_caller(request))
        return SlackLinkCode(
            code=code,
            expires_at=expires_at,
            instructions=f"Send `link {code}` to the Slack bot in a direct message within 10 minutes.",
        )

    @router.get("", response_model=SlackLinkList, operation_id="list_slack_links", summary="List linked Slack accounts")
    async def list_links(request: Request) -> SlackLinkList:
        rows = await links.links(_caller(request))
        return SlackLinkList(
            links=[
                SlackLink(team_id=row["tenant"], slack_user_id=row["external_id"], created_at=row["created_at"])
                for row in rows
            ]
        )

    @router.delete("", response_model=SlackUnlinked, operation_id="unlink_slack", summary="Unlink Slack accounts")
    async def unlink(request: Request) -> SlackUnlinked:
        """Unlink every Slack account linked to the caller; their next Slack message is refused until they link
        again."""
        return SlackUnlinked(unlinked=await links.unlink(principal_id=_caller(request)))

    return router
