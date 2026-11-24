from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agno.os.interfaces.slack.helpers import (
    confirmed_email,
    is_guest,
    post_ephemeral,
    send_slack_message_async,
)
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.os.interfaces.slack.context import EventContext, SlackContext

_NOT_A_MEMBER_MESSAGE = "Sorry, only members of this workspace can use this agent."
_APP_NOT_ALLOWED_MESSAGE = "Sorry, this app isn't allowed to use this agent."
_SLACK_UNAVAILABLE_MESSAGE = "Sorry, Slack could not be reached to check your account. Please try again later."
_DIRECTORY_UNAVAILABLE_MESSAGE = "Sorry, the user directory is unavailable. Please try again later."
_DISABLED_MESSAGE = "Sorry, your account on this AgentOS is disabled."
_PERMISSION_MESSAGE = "Sorry, you don't have permission to run this. Required scope(s): `{scope}`"
_NO_ORG_ACCESS_MESSAGE = (
    "Sorry, you don't have access to this AgentOS yet. Ask your admin to add you, or if you're in its "
    "organization on os.agno.com, open this AgentOS there once to connect your account."
)


_ACCESS_CHANGED_HINT = (
    " Ask your admin for access on os.agno.com. If they just gave it to you, open this AgentOS there once "
    "so Slack picks it up."
)


class NoOrgAccessError(PermissionError):
    """A refusal of a user with no current os.agno.com access saved, whose own sign-in may be all they need."""


class OrgPermissionError(PermissionError):
    """A refusal of an org user by their saved os.agno.com access, which only their next visit there refreshes."""


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
    if ctx.senders_authorized:
        # Only the run's own user continues it, as over HTTP, so approvers= does not apply
        if not event_context.user_id:
            return False
        try:
            principal = await member_principal(ctx, client or ctx.web(), user, event_context.team_id)
        except LookupError:
            return False
        return principal is not None and principal == event_context.user_id
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


async def can_stop(ctx: "SlackContext", user: str, event_context: "EventContext", client: Any = None) -> bool:
    """Whether a Slack user may stop a run: as can_act, or under authorize_senders as a cancel over HTTP."""
    if not ctx.senders_authorized:
        return await can_act(ctx, user, event_context, client)
    if not user:
        return False
    # An authorized run already carries its owner's user, so their Stop needs no Slack lookup
    if user == event_context.owner and event_context.authority is not None:
        principal: Optional[str] = event_context.user_id
    else:
        try:
            principal = await member_principal(ctx, client or ctx.web(), user, event_context.team_id)
        except LookupError:
            # Slack cannot be asked: only the owner may still stop the run, as its user
            if user != event_context.owner:
                return False
            principal = event_context.user_id
    if principal is None:
        return False
    # Under user isolation only the run's own user may stop it, as a cancel over HTTP
    isolated = getattr(getattr(ctx.app, "state", None), "user_isolation_enabled", False)
    if isolated and principal != event_context.user_id and user != event_context.owner:
        return False
    # The stopper's own permission to run the entity decides, and a disabled user stops nothing
    try:
        await resolve_principal_authorization(ctx.app, principal, ctx.resource, ctx.entity_id)
    except PermissionError:
        return False
    except Exception as e:
        log_warning(f"authorization provider raised during route authorization; denying: {e}")
        return False
    return True


def refusal(error: PermissionError, principal: Optional[str] = None) -> str:
    """A refused run's Slack reply: the account is disabled, no os.agno.com access yet, or the permission it needs."""
    reason = str(error)
    # Only a member named by their email can be an org user; a slack: user never signs in on os.agno.com
    if isinstance(error, NoOrgAccessError) and principal and not principal.startswith("slack:"):
        return _NO_ORG_ACCESS_MESSAGE
    if reason == "User is disabled":
        return _DISABLED_MESSAGE
    if reason.startswith("Permission required: "):
        message = _PERMISSION_MESSAGE.format(scope=reason.removeprefix("Permission required: "))
        # Slack reads an org user's access as of their last visit, so a change since then needs one more
        return message + _ACCESS_CHANGED_HINT if isinstance(error, OrgPermissionError) else message
    return f"Sorry, this was not run: {reason}"


def principal_authorization(
    app: Any, principal_id: str, roles: Optional[List[str]] = None, scopes: Optional[List[str]] = None
) -> Any:
    """An authority that checks principal_id's roles, or the given roles when set, and scopes as a token's would be.

    ``scopes`` are an org user's saved os.agno.com scopes. They count exactly as the same user's token scopes count
    over HTTP: alone without managed roles, next to the user's roles under ``trust_token_scopes``, not at all otherwise.
    """
    from agno.os.auth import resolve_authorization_provider
    from agno.os.authz.provider import AuthorizationContext
    from agno.run.authorization import RunAuthorization

    return RunAuthorization(
        resolve_authorization_provider(app),
        AuthorizationContext(
            principal_id=principal_id, scopes=list(scopes or []), claims={"sub": principal_id}, roles=roles
        ),
        enforce_tools=False,
    )


async def resolve_principal_authorization(
    app: Any,
    principal_id: str,
    resource: str,
    resource_id: str,
    roles: Optional[List[str]] = None,
    disabled: Optional[bool] = None,
    user: Optional[Dict[str, Any]] = None,
) -> Any:
    """A principal's authority, with roles when given; None with authorization off. Raises if disabled or denied.

    ``user`` is the principal's directory row when the caller already read it. An org user's saved os.agno.com
    scopes apply as their token's would over HTTP.
    """
    from agno.os.auth import _authorization_enforced
    from agno.os.authz.user_directory import ORG_USER, user_type_of

    state = getattr(app, "state", None)
    user_store = getattr(state, "user_store", None)
    # An org user's os.agno.com scopes are on their row, so the row is read instead of the disabled switch alone
    keeps_org_access = bool(getattr(user_store, "org_access_max_age", None))
    row = user
    if row is not None and disabled is None:
        disabled = bool(row.get("disabled"))
    # A disabled switch already read, as from the row provisioning returned, is not read again
    if user_store is not None and (disabled is None or (keeps_org_access and row is None)):
        try:
            if keeps_org_access:
                row = await user_store.aget(principal_id)
                if disabled is None:
                    disabled = bool(row and row.get("disabled"))
            else:
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
    # An org user's os.agno.com access lapses once they stop opening the OS, as it would for someone removed from
    # the organization, and with it every role they got from it: their OS roles do not lapse on their own
    if user_store is not None and keeps_org_access and user_type_of(row) == ORG_USER and not user_store.org_access(row):
        raise NoOrgAccessError("os.agno.com access expired")
    # Roles are resolved fresh on every check, so a revoked grant applies to the next message
    scopes = user_store.org_scopes(row) if user_store is not None and keeps_org_access and row else None
    authority = principal_authorization(app, principal_id, roles, scopes)
    try:
        await authority.arequire(resource, "run", resource_id)
    except PermissionError as e:
        # Someone with no os.agno.com access saved may only need to open the OS there once
        if keeps_org_access and scopes is None and not isinstance(e, NoOrgAccessError):
            raise NoOrgAccessError(str(e)) from e
        # An org user refused by their saved access may have been granted more since their last visit
        if scopes is not None and type(e) is PermissionError:
            raise OrgPermissionError(str(e)) from e
        raise
    return authority


def no_roles_authorization(app: Any, owner: str) -> Any:
    """An authority with no roles for a Slack user not in users=, None with authorization off."""
    from agno.os.auth import _authorization_enforced

    if not _authorization_enforced(app):
        return None
    return principal_authorization(app, f"slack:{owner}")


async def is_other_app(ctx: "SlackContext", client: Any, user: str, bot_id: str) -> bool:
    """Whether a message is another app's: a bot id with no user, or a user the cached users.info reports as a bot."""
    if not bot_id:
        return False
    if not user:
        return True
    # A user-token post carries a person's user id with the bot id
    await ctx.lookup_cache.user_identity(client, user)
    member = ctx.lookup_cache.member(user)
    if member is None:
        raise LookupError()
    return bool(member.get("is_bot"))


async def member_principal(
    ctx: "SlackContext", client: Any, user: str, team_id: Optional[str], member: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """A Slack member's user: their confirmed email under resolve_user_identity, else slack:{workspace}:{id}."""
    if member is None:
        await ctx.lookup_cache.user_identity(client, user)
        member = ctx.lookup_cache.member(user)
    if member is None:
        raise LookupError()
    workspace = member.get("team_id") or team_id
    # A Slack Connect member belongs to another workspace; an Enterprise Grid member also belongs to each
    # workspace listed on their enterprise_user
    teams = (member.get("enterprise_user") or {}).get("teams")
    external = bool(member.get("is_stranger")) or (
        bool(team_id) and workspace != team_id and not (isinstance(teams, list) and team_id in teams)
    )
    # A deactivated account or another organization's member is refused, as another issuer's token is over HTTP,
    # and a bot user is never a directory user
    if member.get("deleted") or member.get("is_bot") or external:
        return None
    # Only a full member's own confirmed email names their existing user; a guest's never does
    email = confirmed_email(member)
    if ctx.resolve_user_identity and email and not is_guest(member):
        return email
    return f"slack:{workspace}:{user}"


async def provision_sender(
    ctx: "SlackContext", principal: str, claims: Dict[str, Any], guest: bool = False
) -> Optional[Dict[str, Any]]:
    """Create a sender's directory user on their first message, with the default role; returns its row, or raises."""
    from agno.os.auth import aprovision_user_with_default_role
    from agno.os.middleware.jwt import is_reserved_principal

    state = getattr(ctx.app, "state", None)
    user_store = getattr(state, "user_store", None)
    if user_store is None or not getattr(state, "user_auto_provision", False) or is_reserved_principal(principal):
        return None
    if guest:
        # Every user holds the default role as a floor, so a guest's is written disabled until an admin enables it
        existing = await user_store.aget(principal)
        if existing is not None:
            return existing
        await user_store.aset_disabled(principal, True, actor="system:jit")
        return await user_store.aupsert(
            principal, email=claims.get("email"), name=claims.get("name"), actor="system:jit"
        )
    return await aprovision_user_with_default_role(user_store, getattr(state, "role_store", None), principal, claims)


async def refuse(
    ctx: "SlackContext",
    event_context: "EventContext",
    client: Any,
    user: Optional[str],
    text: str,
    thread_ts: Optional[str],
) -> None:
    """Tell a refused sender why: a person privately, another app in the thread, since it cannot see an ephemeral."""
    if user is not None:
        await post_ephemeral(client, event_context.channel, user, text, thread_ts)
        return
    log_debug(f"Slack event skipped: another app was refused ({text})")
    # Under reply_to_mentions_only=False an app's message that did not mention the bot is refused quietly
    if not event_context.addressed:
        return
    # An app that answers every message would otherwise trade refusals with this one, so a thread hears it once
    key = f"refused:{event_context.channel}:{thread_ts or event_context.message_ts}"
    if ctx.lookup_cache.get(key) is not None:
        return
    try:
        await send_slack_message_async(client, event_context.channel, thread_ts or event_context.message_ts, text)
    except Exception as e:
        log_warning(f"Failed to tell another app it was refused: {e}")
        return
    # Marked only once the thread was told, so a failed post is tried again on the app's next message
    ctx.lookup_cache.set(key, True)


async def refuse_unidentified(
    ctx: "SlackContext", event_context: "EventContext", client: Any, user: Optional[str]
) -> bool:
    """Refuse a message whose sender Slack cannot identify, as an unverifiable token is over HTTP; returns False."""
    await refuse(ctx, event_context, client, user, _SLACK_UNAVAILABLE_MESSAGE, event_context.thread_ts)
    return False


async def refuse_app(ctx: "SlackContext", event_context: "EventContext", client: Any) -> bool:
    """Refuse another app's message, since under authorize_senders only people run; returns False."""
    await refuse(ctx, event_context, client, None, _APP_NOT_ALLOWED_MESSAGE, event_context.thread_ts)
    return False


async def authorize_sender(ctx: "SlackContext", event_context: "EventContext", client: Any) -> bool:
    """Run a message as its sender's directory user, created on their first message; that user's roles decide."""
    thread_ts = event_context.thread_ts
    user = event_context.owner
    # Read once, so the record that names the user also decides whether they start disabled as a guest
    await ctx.lookup_cache.user_identity(client, user)
    member = ctx.lookup_cache.member(user)
    if member is None:
        return await refuse_unidentified(ctx, event_context, client, user)
    principal = await member_principal(ctx, client, user, event_context.team_id, member=member)
    if principal is None:
        await refuse(ctx, event_context, client, user, _NOT_A_MEMBER_MESSAGE, thread_ts)
        return False
    # The run is the sender's from here, so no later step can leave it under an id they only claim
    event_context.user_id = principal
    claims: Dict[str, Any] = {}
    # The confirmed email labels the user in /users; it names the user only under resolve_user_identity
    if confirmed_email(member):
        claims["email"] = confirmed_email(member)
    if event_context.display_name:
        claims["name"] = event_context.display_name
    # Provisioning reads the user's row, so its disabled switch is not read again, as over HTTP
    disabled: Optional[bool] = None
    provisioned: Optional[Dict[str, Any]] = None
    try:
        provisioned = await provision_sender(ctx, principal, claims, guest=is_guest(member))
        if provisioned is not None:
            disabled = bool(provisioned.get("disabled"))
    except Exception as e:
        fail_closed = bool(getattr(getattr(ctx.app, "state", None), "user_directory_fail_closed", False))
        log_warning(
            f"user directory check failed for {principal!r}: {e} (failing {'closed' if fail_closed else 'open'})"
        )
        if fail_closed:
            await refuse(ctx, event_context, client, user, _DIRECTORY_UNAVAILABLE_MESSAGE, thread_ts)
            return False
        # Failing open skips the disabled switch, as over HTTP; roles still decide
        disabled = False
    return await authorize_run(
        ctx, event_context, principal, client, user, thread_ts, disabled=disabled, user_row=provisioned
    )


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
    disabled: Optional[bool] = None,
    user_row: Optional[Dict[str, Any]] = None,
) -> bool:
    """Set the run's platform authority for a principal; a refused principal is told why in an ephemeral."""
    try:
        if ctx.company is not None:
            event_context.authority = await ctx.company.authorize(
                ctx.app, principal, ctx.entity_id, roles, disabled=disabled, user=user_row
            )
        else:
            event_context.authority = await resolve_principal_authorization(
                ctx.app, principal, ctx.resource, ctx.entity_id, roles, disabled=disabled, user=user_row
            )
    except PermissionError as e:
        # A sender checked as their own user is told why in plain words; users= and default_role= keep Not run
        message = refusal(e, principal) if ctx.senders_authorized else f"Not run: {e}"
        await post_ephemeral(client, event_context.channel, user, message, thread_ts)
        return False
    return True
