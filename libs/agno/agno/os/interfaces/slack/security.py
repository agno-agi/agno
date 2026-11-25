from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agno.os.interfaces.slack.helpers import confirmed_email, is_outsider, post_ephemeral
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.os.interfaces.slack.context import EventContext, SlackContext

# Private replies to a sender who is not run, under authorize_senders
_PLATFORM_ACCESS_MESSAGE = (
    "You don't have platform access on this AgentOS, so I can't run this. Ask your admin for platform access."
)
_NO_ACCESS_MESSAGE = "You don't have access to {name} on this AgentOS. Ask your admin for access."
_DISABLED_MESSAGE = "Your account on this AgentOS is disabled. Ask your admin to enable it."
_OUTSIDER_MESSAGE = (
    "Guests and people from other organizations need an admin to turn on their access to this AgentOS. Ask your admin."
)
_SLACK_UNAVAILABLE_MESSAGE = "Slack could not be reached to check your account. Please try again."
_DIRECTORY_UNAVAILABLE_MESSAGE = "The user directory is unavailable. Please try again later."
# To someone other than the run's owner, e.g. an approver, refused because of the owner's access
_OWNER_NO_ACCESS_MESSAGE = "The person who started this run no longer has access to it on this AgentOS."


class UserDisabledError(PermissionError):
    """The principal is disabled in the user directory."""


class UserDirectoryUnavailableError(PermissionError):
    """The user directory could not be read and is configured to fail closed."""


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
            if fail_closed:
                raise UserDirectoryUnavailableError("User directory unavailable")
            disabled = False
        if disabled:
            raise UserDisabledError("User is disabled")
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


async def _sender_row(
    ctx: "SlackContext", principal: str, member: Dict[str, Any], outsider: bool, name: Optional[str]
) -> Optional[Dict[str, Any]]:
    """A sender's row in the user directory, created on their first message; None when there is none."""
    from agno.os.auth import aprovision_user_with_default_role

    state = getattr(ctx.app, "state", None)
    user_store = getattr(state, "user_store", None)
    if user_store is None:
        return None
    if not getattr(state, "user_auto_provision", False):
        return await user_store.aget(principal)
    # The confirmed email labels the user in the directory; it is their id only under resolve_user_identity
    email = confirmed_email(member)
    if outsider:
        existing = await user_store.aget(principal)
        if existing is not None:
            return existing
        # Someone outside the workspace gets no role by default: their user starts disabled, for an admin to enable
        await user_store.aset_disabled(principal, True, actor="system:jit")
        return await user_store.aupsert(principal, email=email, name=name, actor="system:jit")
    # The same helper as a first sign-in with a token, so the default role is granted the same way
    return await aprovision_user_with_default_role(
        user_store, getattr(state, "role_store", None), principal, {"email": email, "name": name}
    )


async def authorize_sender(ctx: "SlackContext", event_context: "EventContext", client: Any) -> bool:
    """Run a message as its sender's own user in the user directory; a sender who is not run is told why."""
    from agno.os.middleware.jwt import is_reserved_principal

    user = event_context.event.get("user") or ""
    thread_ts = event_context.thread_ts
    member = await ctx.lookup_cache.member(client, user) if user else None
    # Another app is not a person in the directory; one that should run is mapped in users=
    if not user or (member is not None and member.get("is_bot")):
        log_debug("Slack event skipped: another app is not a user in the user directory")
        return False
    if member is None:
        # Without Slack's record a guest cannot be told from a member, so nothing is run
        await post_ephemeral(client, event_context.channel, user, _SLACK_UNAVAILABLE_MESSAGE, thread_ts)
        return False
    # The user id of a first sign-in on the web: the confirmed email, so one person is one user
    principal = (confirmed_email(member) if ctx.resolve_user_identity else None) or user
    if is_reserved_principal(principal):
        log_debug("Slack event skipped: the sender's id is reserved for the system")
        return False
    # The run is this user's from here on
    event_context.user_id = principal
    outsider = is_outsider(member, event_context.team_id)
    try:
        row = await _sender_row(ctx, principal, member, outsider, event_context.display_name)
    except Exception as e:
        # Directory unreachable: honour the configured policy, as for a request with a token
        fail_closed = bool(getattr(getattr(ctx.app, "state", None), "user_directory_fail_closed", False))
        log_warning(
            f"user directory check failed for {principal!r}: {e} (failing {'closed' if fail_closed else 'open'})"
        )
        if fail_closed or outsider:
            await post_ephemeral(client, event_context.channel, user, _DIRECTORY_UNAVAILABLE_MESSAGE, thread_ts)
            return False
        row = None
    # A guest, or a member of another organization, is run only as an enabled user of the directory
    if outsider and (row is None or row.get("disabled")):
        await post_ephemeral(client, event_context.channel, user, _OUTSIDER_MESSAGE, thread_ts)
        return False
    return await authorize_sender_again(ctx, event_context, client, user, thread_ts)


async def authorize_sender_again(
    ctx: "SlackContext", event_context: "EventContext", client: Any, user: str, thread_ts: Optional[str] = None
) -> bool:
    """Check the run's user as they are now: their disabled switch and the role they hold at this moment."""
    return await authorize_run(ctx, event_context, event_context.user_id, client, user, thread_ts)


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
    """Set the run's platform authority for a principal; a refused principal is told why in an ephemeral."""
    try:
        if ctx.company is not None:
            event_context.authority = await ctx.company.authorize(ctx.app, principal, ctx.entity_id, roles)
        else:
            event_context.authority = await resolve_principal_authorization(
                ctx.app, principal, ctx.resource, ctx.entity_id, roles
            )
    except PermissionError as e:
        await post_ephemeral(
            client, event_context.channel, user, _refusal(ctx, e, user == event_context.owner), thread_ts
        )
        return False
    return True


def _refusal(ctx: "SlackContext", error: PermissionError, to_owner: bool) -> str:
    """What a refused user is told. Under authorize_senders it says who to ask, not which scope is missing."""
    if not ctx.authorize_senders:
        return f"Not run: {error}"
    if isinstance(error, UserDirectoryUnavailableError):
        return _DIRECTORY_UNAVAILABLE_MESSAGE
    if not to_owner:
        return _OWNER_NO_ACCESS_MESSAGE
    if isinstance(error, UserDisabledError):
        return _DISABLED_MESSAGE
    # Super Agent is reached with platform access
    if ctx.company is not None:
        return _PLATFORM_ACCESS_MESSAGE
    return _NO_ACCESS_MESSAGE.format(name=ctx.entity_name)
