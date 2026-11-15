from os import getenv
from typing import TYPE_CHECKING, Any, List, Optional, Set

from agno.os.interfaces.slack.helpers import post_ephemeral, slack_error_code
from agno.os.middleware.jwt import is_reserved_principal
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.os.interfaces.slack.context import EventContext, SlackContext

# Directory users read per search page when resolving a Slack sender
_DIRECTORY_PAGE_SIZE = 1000


def resolve_token(token: Optional[str] = None) -> str:
    """The bot token: the argument when given, even empty, else SLACK_TOKEN."""
    resolved = token if token is not None else getenv("SLACK_TOKEN")
    if not resolved:
        raise ValueError("Slack requires a bot token: pass token or set SLACK_TOKEN")
    return resolved


def resolve_signing_secret(signing_secret: Optional[str] = None) -> str:
    """The signing secret: the argument when given, even empty, else SLACK_SIGNING_SECRET."""
    resolved = signing_secret if signing_secret is not None else getenv("SLACK_SIGNING_SECRET")
    if not resolved:
        raise ValueError("Slack requires a signing secret: pass signing_secret or set SLACK_SIGNING_SECRET")
    return resolved


def principal_required(ctx: "SlackContext", app: Any = None) -> bool:
    """Whether a Slack user's runs need a principal: users=, or Super Agent or directory roles under authorization."""
    from agno.os.auth import _authorization_enforced

    app = app if app is not None else ctx.app
    state = getattr(app, "state", None)
    # A sender is resolved from the user directory by Slack email; a Slack request carries no token,
    # so only managed roles can grant that sender a run
    directory_roles = (
        ctx.resolve_user_identity
        and getattr(state, "user_store", None) is not None
        and getattr(state, "role_store", None) is not None
    )
    # The middleware may be added after get_app(), so it is checked on each request
    return ctx.users is not None or ((ctx.company is not None or directory_roles) and _authorization_enforced(app))


def resolves_from_directory(ctx: "SlackContext", app: Any = None) -> bool:
    """Whether principals come from the AgentOS user directory by Slack email rather than from users=."""
    return ctx.users is None and ctx.resolve_user_identity and principal_required(ctx, app)


async def directory_principal(
    ctx: "SlackContext",
    client: Any,
    user: str,
    team_id: Optional[str],
    app: Any = None,
    errors: Optional[Set[str]] = None,
) -> Optional[str]:
    """The one directory user a Slack member is, by id then email; None for no single match or a failed lookup."""
    key = f"principal:{team_id or ''}:{user}"
    cached = ctx.lookup_cache.get(key)
    if cached is not None:
        return cached
    state = getattr(app if app is not None else ctx.app, "state", None)
    user_store = getattr(state, "user_store", None)
    if user_store is None or not user:
        return None
    try:
        response = await client.users_info(user=user)
    except Exception as e:
        log_warning(f"Failed to resolve Slack user {user}: {str(e)}")
        # The Slack error code ("" for a network error), so a caller can retry rather than refuse
        if errors is not None:
            errors.add(slack_error_code(e) or "")
        return None
    member = response.get("user") or {}
    # A deleted account, a bot or a stranger is not this workspace's person
    if member.get("deleted") or member.get("is_bot") or member.get("is_stranger"):
        return None
    # A Slack Connect member from another organization belongs to another workspace; an Enterprise Grid
    # member also belongs to each workspace listed on their enterprise_user
    teams = (member.get("enterprise_user") or {}).get("teams")
    if team_id and member.get("team_id") != team_id and not (isinstance(teams, list) and team_id in teams):
        return None
    email = (member.get("profile") or {}).get("email")
    # Case folding maps some non-ASCII letters onto ASCII ones, so only an ASCII email is compared
    if not email or not email.isascii():
        return None
    try:
        # A user whose id is the email (os.agno.com tokens carry the email as sub) is read directly, with no search
        row = await user_store.aget(email)
        if row is None and email.lower() != email:
            row = await user_store.aget(email.lower())
        # A reserved server principal (sa:, __oauth__:, the scheduler) is never a Slack member
        if row is not None and not is_reserved_principal(row["id"]):
            ctx.lookup_cache.set(key, row["id"])
            return row["id"]
        # Every row the search finds: under one page, rows that only contain the email could push this user's out
        rows: List[dict] = []
        while True:
            page = await user_store.alist(search=email, limit=_DIRECTORY_PAGE_SIZE, offset=len(rows))
            rows.extend(page)
            if len(page) < _DIRECTORY_PAGE_SIZE:
                break
    except Exception as e:
        # Directory unreachable: no principal, so the sender is refused rather than run unchecked
        log_warning(f"user directory lookup failed for Slack user {user}: {type(e).__name__}")
        if errors is not None:
            errors.add("")
        return None
    # A user whose id is the email (os.agno.com tokens carry the email as sub) is that person: the identity
    # provider issued that id, while an email field can come from any token's claims
    rows = [row for row in rows if not is_reserved_principal(str(row.get("id") or ""))]
    matches = [row for row in rows if str(row.get("id") or "").lower() == email.lower()]
    if not matches:
        matches = [row for row in rows if str(row.get("email") or "").lower() == email.lower()]
    if len(matches) != 1:
        if matches:
            log_warning(f"Slack user {user} matches {len(matches)} directory users by email; none is used")
        return None
    principal = matches[0]["id"]
    ctx.lookup_cache.set(key, principal)
    return principal


async def directory_email(ctx: "SlackContext", principal: str) -> Optional[str]:
    """The email on a directory user's row; None without a directory, a row, or on a failed read."""
    state = getattr(ctx.app, "state", None)
    user_store = getattr(state, "user_store", None)
    if user_store is None:
        return None
    try:
        row = await user_store.aget(principal)
    except Exception as e:
        log_warning(f"user directory read failed: {type(e).__name__}")
        return None
    return (row or {}).get("email")


async def sender_principal(ctx: "SlackContext", client: Any, user: str, team_id: Optional[str] = None) -> Optional[str]:
    """A Slack user's principal from users= (an allowlist, never widened), else from the user directory."""
    if ctx.users is not None:
        return ctx.users.get(user)
    if resolves_from_directory(ctx):
        return await directory_principal(ctx, client, user, team_id)
    return None


async def can_act(ctx: "SlackContext", user: str, event_context: "EventContext", client: Any = None) -> bool:
    """Whether a Slack user may stop or decide on a run: its owner, an approver, or the same agno user."""
    if not user:
        return False
    if user == event_context.owner:
        return True
    if ctx.approvers is not None and user in ctx.approvers:
        return True
    if principal_required(ctx):
        principal = await sender_principal(ctx, client or ctx.web(), user, event_context.team_id)
        return principal is not None and principal == event_context.user_id
    if ctx.resolve_user_identity and event_context.user_id:
        # Same derivation as the event context's user, so the owner can act after a restart
        resolved_user_id, _ = await ctx.lookup_cache.user_identity(client or ctx.web(), user)
        return resolved_user_id == event_context.user_id
    return False


async def resolve_principal_authorization(app: Any, principal_id: str, resource: str, resource_id: str) -> Any:
    """A mapped Slack user's authority, None with authorization off. Raises PermissionError if disabled or denied."""
    from agno.os.auth import _authorization_enforced, resolve_authorization_provider
    from agno.os.authz.provider import AuthorizationContext
    from agno.run.authorization import RunAuthorization

    state = getattr(app, "state", None)
    user_store = getattr(state, "user_store", None)
    if user_store is not None:
        try:
            disabled = bool(await user_store.ais_disabled(principal_id))
        except Exception as e:
            # Directory unreachable: honour the configured policy
            fail_closed = bool(getattr(state, "user_directory_fail_closed", False))
            log_warning(
                f"user directory check failed for {principal_id!r}: {e} (failing {'closed' if fail_closed else 'open'})"
            )
            disabled = fail_closed
        if disabled:
            raise PermissionError("User is disabled")
    # The user directory applies on its own, as over HTTP; roles only under AgentOS authorization.
    # The middleware is checked here too: one added after get_app() is not in the flag
    if not _authorization_enforced(app):
        return None
    # Roles are resolved fresh on every check, so a revoked grant applies to the next message
    authority = RunAuthorization(
        resolve_authorization_provider(app),
        AuthorizationContext(principal_id=principal_id, claims={"sub": principal_id}),
        enforce_tools=False,
    )
    await authority.arequire(resource, "run", resource_id)
    return authority


async def authorize_run(
    ctx: "SlackContext",
    event_context: "EventContext",
    principal: str,
    client: Any,
    user: str,
    thread_ts: Optional[str] = None,
) -> bool:
    """Set the run's platform authority for a mapped principal; a refused principal gets the "Not run" ephemeral."""
    try:
        if ctx.company is not None:
            event_context.authority = await ctx.company.authorize(ctx.app, principal, ctx.entity_id)
        else:
            event_context.authority = await resolve_principal_authorization(
                ctx.app, principal, ctx.resource, ctx.entity_id
            )
    except PermissionError as e:
        await post_ephemeral(client, event_context.channel, user, f"Not run: {e}", thread_ts)
        return False
    return True
