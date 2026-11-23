from dataclasses import replace
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agno.db.schemas.service_accounts import SERVICE_ACCOUNT_PRINCIPAL_PREFIX
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
_SERVICE_ACCOUNT_MESSAGE = "Sorry, this app's service account is missing, revoked or expired."
_SLACK_UNAVAILABLE_MESSAGE = "Sorry, Slack could not be reached to check your account. Please try again later."
_DIRECTORY_UNAVAILABLE_MESSAGE = "Sorry, the user directory is unavailable. Please try again later."
_DISABLED_MESSAGE = "Sorry, your account on this AgentOS is disabled."
# Backticks keep Slack from reading :name: in a scope as an emoji code
_PERMISSION_MESSAGE = "Sorry, you don't have permission to run this. Required scope(s): `{scope}`"
_SERVICE_ACCOUNT_PERMISSION_MESSAGE = (
    "Sorry, this app's service account doesn't have permission to run this. Required scope(s): `{scope}`"
)
_PERMISSIONS_UNAVAILABLE_MESSAGE = "Sorry, your permissions could not be checked. Please try again later."
_BOT_SERVICE_ACCOUNT_MESSAGE = "Sorry, this bot's service account is missing, revoked or expired."
_BOT_PERMISSION_MESSAGE = "Sorry, this bot doesn't have permission to run this. Required scope(s): `{scope}`"


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
        await arecord_slack_decision(
            ctx, principal, allowed=False, action="cancel", run_id=event_context.run_id, reason="resource_access_denied"
        )
        return False
    # The stopper's own permission to run the entity decides, and a disabled user stops nothing
    try:
        await resolve_principal_authorization(ctx.app, principal, ctx.resource, ctx.entity_id)
    except PermissionError as e:
        _, reason = refusal(e)
        await arecord_slack_decision(
            ctx, principal, allowed=False, action="cancel", run_id=event_context.run_id, reason=reason
        )
        return False
    except Exception as e:
        log_warning(f"authorization provider raised during route authorization; denying: {e}")
        await arecord_slack_decision(
            ctx, principal, allowed=False, action="cancel", run_id=event_context.run_id, reason="provider_error"
        )
        return False
    await arecord_slack_decision(ctx, principal, allowed=True, action="cancel", run_id=event_context.run_id)
    return True


async def started_by_app(ctx: "SlackContext", event_context: "EventContext", client: Any = None) -> bool:
    """Whether another app started the run: it runs as an app's service account, or its owner is a bot user."""
    if not ctx.respond_to_other_apps or ctx.company is not None:
        return False
    # The run's stored user names the app's account even for a webhook, whose bot id users.info cannot look up
    mapped = ctx.users is not None and not ctx.senders_authorized and event_context.owner in ctx.users
    if not mapped and event_context.user_id.startswith(SERVICE_ACCOUNT_PRINCIPAL_PREFIX):
        return True
    if not event_context.owner.startswith(("U", "W")):
        return False
    member = await ctx.lookup_cache.member(client or ctx.web(), event_context.owner)
    return bool((member or {}).get("is_bot"))


async def admin_of_app_run(
    ctx: "SlackContext", user: str, event_context: "EventContext", client: Any = None
) -> Optional[str]:
    """The clicker's user on a run another app started, when their own roles grant admin; None otherwise."""
    client = client or ctx.web()
    if not user:
        return None
    try:
        if ctx.senders_authorized:
            principal = await member_principal(ctx, client, user, event_context.team_id)
        else:
            principal = (ctx.users or {}).get(user)
        if principal is None:
            return None
        authority = await resolve_principal_authorization(ctx.app, principal, ctx.resource, ctx.entity_id)
        if authority is None:
            return None
        await authority.arequire("agent_os", "admin")
    except (LookupError, PermissionError):
        return None
    except Exception as e:
        log_warning(f"authorization provider raised during route authorization; denying: {e}")
        return None
    return principal


async def arecord_slack_decision(
    ctx: "SlackContext",
    principal: str,
    allowed: bool,
    action: str = "run",
    run_id: Optional[str] = None,
    reason: Optional[str] = None,
    scopes: Optional[List[str]] = None,
) -> None:
    """Write a Slack run, approval or Stop decision to the access audit, under its own SLACK label."""
    from agno.os.authz.audit import arecord_decision

    path = f"/{ctx.resource}/{ctx.entity_id}/runs"
    # An approval or a Stop names its run, as POST /{resource}/{id}/runs/{run_id}/continue or /cancel does
    if action != "run":
        path = f"{path}/{run_id}/{action}"
    # Labelled SLACK, as WebSocket decisions are labelled WS, so a Slack decision reads apart from HTTP
    await arecord_decision(
        ctx.app,
        allowed=allowed,
        target=f"SLACK {path}",
        principal=principal,
        required_scopes=[f"{ctx.resource}:{ctx.entity_id}:run"],
        scopes=scopes,
        reason=None if allowed else reason,
    )


def refusal(error: PermissionError) -> Tuple[str, str]:
    """A refused run's Slack reply and audit reason: disabled, the directory down, or the permission it needs."""
    reason = str(error)
    if reason == "User is disabled":
        return _DISABLED_MESSAGE, "user_disabled"
    if reason == "User directory unavailable":
        return _DIRECTORY_UNAVAILABLE_MESSAGE, "directory_unavailable"
    if reason.startswith("Permission required: "):
        return _PERMISSION_MESSAGE.format(scope=reason.removeprefix("Permission required: ")), "resource_access_denied"
    return f"Sorry, this was not run: {reason}", "resource_access_denied"


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
    app: Any,
    principal_id: str,
    resource: str,
    resource_id: str,
    roles: Optional[List[str]] = None,
    disabled: Optional[bool] = None,
) -> Any:
    """A principal's authority, with roles when given; None with authorization off. Raises if disabled or denied."""
    from agno.os.auth import _authorization_enforced

    state = getattr(app, "state", None)
    user_store = getattr(state, "user_store", None)
    # A disabled switch already read, as from the row provisioning returned, is not read again
    if disabled is not None:
        if disabled:
            raise PermissionError("User is disabled")
    elif user_store is not None:
        try:
            disabled = bool(await user_store.ais_disabled(principal_id))
        except Exception as e:
            # Directory unreachable: honour the configured policy
            fail_closed = bool(getattr(state, "user_directory_fail_closed", False))
            log_warning(
                f"user directory check failed for {principal_id!r}: {e} (failing {'closed' if fail_closed else 'open'})"
            )
            # Failing closed refuses as an outage, as the 503 over HTTP, not as a disabled account
            if fail_closed:
                raise PermissionError("User directory unavailable") from e
            disabled = False
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


async def is_other_app(ctx: "SlackContext", client: Any, user: str, bot_id: str) -> bool:
    """Whether a message is another app's: a bot id with no user, or a user the cached users.info reports as a bot."""
    if not bot_id:
        return False
    if not user:
        return True
    # A user-token post carries a person's user id with the bot id
    member = await ctx.lookup_cache.member(client, user)
    if member is None:
        raise LookupError()
    return bool(member.get("is_bot"))


async def member_principal(
    ctx: "SlackContext", client: Any, user: str, team_id: Optional[str], member: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """A Slack member's user: their confirmed email under resolve_user_identity, else slack:{workspace}:{id}."""
    if member is None:
        member = await ctx.lookup_cache.member(client, user)
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


async def app_principal(ctx: "SlackContext", client: Any, event: Dict[str, Any]) -> Optional[str]:
    """Another app's service account, from allowed_apps=; None when allowed_apps= does not list it."""
    from agno.os.service_accounts import get_principal

    # An incoming webhook's event names no app id, so its bot's bots.info record does
    app_id = event.get("app_id") or (event.get("bot_profile") or {}).get("app_id")
    bot_id = event.get("bot_id") or ""
    if not app_id and bot_id:
        bot = await ctx.lookup_cache.bot(client, bot_id)
        if bot is None:
            raise LookupError()
        app_id = bot.get("app_id")
    app_id = app_id or bot_id
    # allowed_apps= names the service account; the app runs as its sa: principal, as with a PAT
    name = (ctx.allowed_apps or {}).get(app_id)
    if not name:
        log_debug(f"Slack app {app_id} is not in allowed_apps=")
        return None
    return get_principal(name)


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


async def authorize_sender(ctx: "SlackContext", event_context: "EventContext", client: Any) -> bool:
    """Run a message as its sender's directory user, created on their first message; that user's roles decide."""
    thread_ts = event_context.thread_ts
    user = event_context.owner
    # Read once, so the record that names the user also decides whether they start disabled as a guest
    member = await ctx.lookup_cache.member(client, event_context.owner)
    if member is None:
        return await refuse_unidentified(ctx, event_context, client, user)
    principal = await member_principal(ctx, client, event_context.owner, event_context.team_id, member=member)
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
    return await authorize_run(ctx, event_context, principal, client, user, thread_ts, disabled=disabled)


async def authorize_app(ctx: "SlackContext", event_context: "EventContext", client: Any) -> bool:
    """Run another app's message as the service account allowed_apps= lists it with; any other app is refused."""
    thread_ts = event_context.thread_ts
    try:
        principal = await app_principal(ctx, client, event_context.event)
    except LookupError:
        return await refuse_unidentified(ctx, event_context, client, None)
    if principal is None:
        await refuse(ctx, event_context, client, None, _APP_NOT_ALLOWED_MESSAGE, thread_ts)
        return False
    # The run is the app's service account's from here, as a PAT's run is
    event_context.user_id = principal
    return await authorize_service_account(ctx, event_context, principal, client, thread_ts=thread_ts)


async def resolve_service_account_authorization(ctx: "SlackContext", principal: str) -> Any:
    """A service account's authority from its scopes, as for its PAT; None when missing, revoked or expired."""
    from agno.os.auth import _default_authorization_provider
    from agno.os.authz.provider import AuthorizationContext
    from agno.run.authorization import RunAuthorization

    verifier = getattr(getattr(ctx.app, "state", None), "service_account_verifier", None)
    # An unreadable account raises, an outage as UNAVAILABLE over HTTP, not a revoked one
    account = (
        await verifier.aget_by_name(principal.removeprefix(SERVICE_ACCOUNT_PRINCIPAL_PREFIX))
        if verifier is not None
        else None
    )
    if account is None or account.is_revoked() or account.is_expired():
        return None
    admin_scope_raw = getattr(getattr(ctx.app, "state", None), "admin_scope", None)
    return RunAuthorization(
        _default_authorization_provider(),
        AuthorizationContext(
            principal_id=account.principal,
            scopes=list(account.scopes),
            admin_scope=admin_scope_raw if isinstance(admin_scope_raw, str) else None,
        ),
        True,
        enforce_tools=False,
    )


async def authorize_service_account(
    ctx: "SlackContext",
    event_context: "EventContext",
    principal: str,
    client: Any,
    user: Optional[str] = None,
    thread_ts: Optional[str] = None,
    action: str = "run",
    record_allowed: bool = True,
) -> bool:
    """Set the run's authority for an app mapped to a service account: its own scopes decide, as for its PAT."""
    run_id = event_context.run_id
    try:
        authority = await resolve_service_account_authorization(ctx, principal)
    except Exception:
        await refuse(ctx, event_context, client, user, _PERMISSIONS_UNAVAILABLE_MESSAGE, thread_ts)
        await arecord_slack_decision(
            ctx, principal, allowed=False, action=action, run_id=run_id, reason="provider_error"
        )
        return False
    if authority is None:
        await refuse(ctx, event_context, client, user, _SERVICE_ACCOUNT_MESSAGE, thread_ts)
        await arecord_slack_decision(
            ctx, principal, allowed=False, action=action, run_id=run_id, reason="service_account_invalid"
        )
        return False
    try:
        await authority.arequire(ctx.resource, "run", ctx.entity_id)
    except PermissionError as e:
        _, reason = refusal(e)
        message = _SERVICE_ACCOUNT_PERMISSION_MESSAGE.format(scope=str(e).removeprefix("Permission required: "))
        await refuse(ctx, event_context, client, user, message, thread_ts)
        await arecord_slack_decision(
            ctx,
            principal,
            allowed=False,
            action=action,
            run_id=run_id,
            reason=reason,
            scopes=authority.context.scopes,
        )
        return False
    event_context.authority = authority
    # Recorded as allowed only once the bot's own account allows it too
    if not await cap_to_bot(ctx, event_context, client, user, thread_ts, action):
        return False
    if record_allowed:
        await arecord_slack_decision(
            ctx, principal, allowed=True, action=action, run_id=run_id, scopes=authority.context.scopes
        )
    return True


async def bot_service_account(ctx: "SlackContext", client: Any) -> str:
    """This bot's own service account name: the one given, or with True slack-<its app id>; raises if unknown."""
    if isinstance(ctx.service_account, str):
        return ctx.service_account
    # The bot's app id is resolved as another app's is, from its bot id through the cached bots.info
    app_id = None
    if ctx.bot_id:
        app_id = (await ctx.lookup_cache.bot(client, ctx.bot_id) or {}).get("app_id")
    if not app_id:
        raise LookupError()
    return f"slack-{app_id.lower()}"


async def refuse_capped(
    ctx: "SlackContext",
    event_context: "EventContext",
    client: Any,
    user: Optional[str],
    text: str,
    thread_ts: Optional[str],
) -> None:
    """Refuse a run the bot's own account does not allow; an app answered unchecked is told in the thread."""
    event = event_context.event
    if user is not None and user == event_context.owner and event.get("bot_id"):
        try:
            if await is_other_app(ctx, client, event.get("user") or "", event["bot_id"]):
                user = None
        except LookupError:
            log_debug("Slack could not say whether a refused sender is an app")
    await refuse(ctx, event_context, client, user, text, thread_ts)


async def cap_to_bot(
    ctx: "SlackContext",
    event_context: "EventContext",
    client: Any,
    user: Optional[str],
    thread_ts: Optional[str],
    action: str = "run",
) -> bool:
    """Cap a run's authority to the bot's own service account; refuse when that account cannot run the entity."""
    from agno.os.service_accounts import get_principal
    from agno.run.authorization import InterfaceAuthorization

    if ctx.service_account is None or ctx.service_account is False:
        return True
    run_id = event_context.run_id
    try:
        name = await bot_service_account(ctx, client or ctx.web())
    except LookupError:
        # Without its own app id the bot cannot find its account, so it refuses rather than run uncapped
        # A failed bots.info is already logged; only a bot with no bot id is not
        if not ctx.bot_id:
            log_warning("Slack lookup failed for this bot's app id")
        await refuse_capped(ctx, event_context, client, user, _BOT_SERVICE_ACCOUNT_MESSAGE, thread_ts)
        # The account has no name yet, so the denial is recorded for the run's user
        await arecord_slack_decision(
            ctx, event_context.user_id, allowed=False, action=action, run_id=run_id, reason="service_account_unknown"
        )
        return False
    principal = get_principal(name)
    try:
        interface = await resolve_service_account_authorization(ctx, principal)
    except Exception:
        await refuse_capped(ctx, event_context, client, user, _PERMISSIONS_UNAVAILABLE_MESSAGE, thread_ts)
        await arecord_slack_decision(
            ctx, principal, allowed=False, action=action, run_id=run_id, reason="provider_error"
        )
        return False
    failing_key = f"service_account:{name}"
    if interface is None:
        if failing_key not in ctx.failing:
            log_warning(f"Slack service account '{name}' is missing, revoked or expired, so every message is refused")
        ctx.failing.add(failing_key)
        await refuse_capped(ctx, event_context, client, user, _BOT_SERVICE_ACCOUNT_MESSAGE, thread_ts)
        await arecord_slack_decision(
            ctx, principal, allowed=False, action=action, run_id=run_id, reason="service_account_invalid"
        )
        return False
    ctx.failing.discard(failing_key)
    try:
        await interface.arequire(ctx.resource, "run", ctx.entity_id)
    except PermissionError as e:
        text = _BOT_PERMISSION_MESSAGE.format(scope=str(e).removeprefix("Permission required: "))
        _, reason = refusal(e)
        await refuse_capped(ctx, event_context, client, user, text, thread_ts)
        await arecord_slack_decision(
            ctx,
            principal,
            allowed=False,
            action=action,
            run_id=run_id,
            reason=reason,
            scopes=interface.context.scopes,
        )
        return False
    # A parked run's authority is already capped, so a later decision replaces the cap instead of adding one
    caller = event_context.authority
    if isinstance(caller, InterfaceAuthorization):
        caller = caller.caller
    if caller is None:
        # A run that is otherwise unchecked is checked against the bot's account alone, still as its sender
        event_context.authority = InterfaceAuthorization(
            interface.provider,
            replace(interface.context, principal_id=event_context.user_id),
            enforce_tools=interface.enforce_tools,
            interface=interface,
        )
    else:
        event_context.authority = InterfaceAuthorization.wrap(caller, interface)
    return True


async def authorize_unmapped(
    ctx: "SlackContext",
    event_context: "EventContext",
    client: Any,
    user: str,
    thread_ts: Optional[str] = None,
    action: str = "run",
    record_allowed: bool = True,
) -> bool:
    """A run whose owner is not in users=: the default role's, no roles on Super Agent, else none; capped by the bot."""
    # The member acts and is recorded as themselves; the default role only supplies the permissions
    if ctx.default_role is not None:
        return await authorize_run(
            ctx,
            event_context,
            event_context.user_id,
            client,
            user,
            thread_ts,
            roles=[ctx.default_role],
            action=action,
            record_allowed=record_allowed,
        )
    # Without a default role only Super Agent (ctx.company is set) is checked, with no roles; others run unchecked
    if ctx.company is not None:
        event_context.authority = no_roles_authorization(ctx.app, event_context.owner)
    return await cap_to_bot(ctx, event_context, client, user, thread_ts, action)


async def authorize_run(
    ctx: "SlackContext",
    event_context: "EventContext",
    principal: str,
    client: Any,
    user: Optional[str],
    thread_ts: Optional[str] = None,
    roles: Optional[List[str]] = None,
    action: str = "run",
    record_allowed: bool = True,
    disabled: Optional[bool] = None,
) -> bool:
    """Set the run's platform authority for a principal; a refused person gets the refusal ephemeral."""
    if ctx.company is not None:
        # Super Agent decides its own senders, so its refusal keeps the Not run text and writes no audit row
        try:
            event_context.authority = await ctx.company.authorize(ctx.app, principal, ctx.entity_id, roles)
        except PermissionError as e:
            await refuse(ctx, event_context, client, user, f"Not run: {e}", thread_ts)
            return False
        return await cap_to_bot(ctx, event_context, client, user, thread_ts, action)
    run_id = event_context.run_id
    try:
        event_context.authority = await resolve_principal_authorization(
            ctx.app, principal, ctx.resource, ctx.entity_id, roles, disabled=disabled
        )
    except PermissionError as e:
        message, reason = refusal(e)
        await refuse(ctx, event_context, client, user, message, thread_ts)
        await arecord_slack_decision(ctx, principal, allowed=False, action=action, run_id=run_id, reason=reason)
        return False
    except Exception as e:
        # A provider that raised (an unreachable role database) is a denial, as over HTTP
        log_warning(f"authorization provider raised during route authorization; denying: {e}")
        await refuse(ctx, event_context, client, user, _PERMISSIONS_UNAVAILABLE_MESSAGE, thread_ts)
        await arecord_slack_decision(
            ctx, principal, allowed=False, action=action, run_id=run_id, reason="provider_error"
        )
        return False
    # Recorded as allowed only once the bot's own account allows it too
    if not await cap_to_bot(ctx, event_context, client, user, thread_ts, action):
        return False
    if record_allowed:
        await arecord_slack_decision(ctx, principal, allowed=True, action=action, run_id=run_id)
    return True
