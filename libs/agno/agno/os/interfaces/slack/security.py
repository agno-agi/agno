from os import getenv
from typing import TYPE_CHECKING, Any, List, Optional

from agno.os.interfaces.slack.helpers import post_ephemeral
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.os.interfaces.slack.context import EventContext, SlackContext


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


async def can_act(ctx: "SlackContext", user: str, event_context: "EventContext", client: Any = None) -> bool:
    """Whether a Slack user may stop or decide on a run: its owner, an approver, or the same agno user."""
    if not user:
        return False
    if user == event_context.owner:
        return True
    if ctx.approvers is not None and user in ctx.approvers:
        return True
    if ctx.users is not None:
        principal = ctx.users.get(user)
        return principal is not None and principal == event_context.user_id
    if ctx.resolve_user_identity and event_context.user_id:
        # Same derivation as the event context's user, so the owner can act after a restart
        resolved_user_id, _ = await ctx.lookup_cache.user_identity(client or ctx.web(), user)
        return resolved_user_id == event_context.user_id
    return False


def principal_authorization(app: Any, principal_id: str, roles: Optional[List[str]] = None) -> Any:
    """An authority that checks principal_id's roles, or the given roles when set."""
    from agno.os.auth import resolve_authorization_provider
    from agno.os.authz.provider import AuthorizationContext
    from agno.run.authorization import RunAuthorization

    return RunAuthorization(
        resolve_authorization_provider(app),
        AuthorizationContext(principal_id=principal_id, claims={"sub": principal_id}, roles=roles),
        enforce_tools=False,
    )


async def resolve_principal_authorization(
    app: Any, principal_id: str, resource: str, resource_id: str, roles: Optional[List[str]] = None
) -> Any:
    """A principal's authority, with roles when given; None with authorization off. Raises if disabled or denied."""
    from agno.os.auth import _authorization_enforced

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
    authority = principal_authorization(app, principal_id, roles)
    await authority.arequire(resource, "run", resource_id)
    return authority


def no_roles_authorization(app: Any, owner: str) -> Any:
    """An authority with no roles for a Slack user not in users=, None with authorization off."""
    from agno.os.auth import _authorization_enforced

    if not _authorization_enforced(app):
        return None
    return principal_authorization(app, f"slack:{owner}")


async def authorize_unmapped(
    ctx: "SlackContext",
    event_context: "EventContext",
    client: Any,
    user: str,
    thread_ts: Optional[str] = None,
) -> bool:
    """Authority of a run whose owner is not in users=: the default role's; else no roles on Super Agent, else none."""
    # The member acts and is recorded as themselves; the default role only supplies the permissions
    if ctx.default_role is not None:
        return await authorize_run(
            ctx, event_context, event_context.user_id, client, user, thread_ts, roles=[ctx.default_role]
        )
    # Without a default role only Super Agent (ctx.company is set) is checked, with no roles; others run unchecked
    if ctx.company is None:
        return True
    event_context.authority = no_roles_authorization(ctx.app, event_context.owner)
    return True


async def authorize_run(
    ctx: "SlackContext",
    event_context: "EventContext",
    principal: str,
    client: Any,
    user: str,
    thread_ts: Optional[str] = None,
    roles: Optional[List[str]] = None,
) -> bool:
    """Set the run's platform authority for a principal; a refused principal gets the "Not run" ephemeral."""
    try:
        if ctx.company is not None:
            event_context.authority = await ctx.company.authorize(ctx.app, principal, ctx.entity_id, roles)
        else:
            event_context.authority = await resolve_principal_authorization(
                ctx.app, principal, ctx.resource, ctx.entity_id, roles
            )
    except PermissionError as e:
        await post_ephemeral(client, event_context.channel, user, f"Not run: {e}", thread_ts)
        return False
    return True
