from dataclasses import replace
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agno.os.interfaces.slack.helpers import post_ephemeral
from agno.os.interfaces.slack.links import MemberLink, PlatformUnavailable
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.os.interfaces.slack.context import EventContext, SlackContext

_LINK_TEXT = "Link your Agno account to use {name} from Slack. You act here with your permissions on this AgentOS."
_NO_ACCESS_TEXT = "Your linked Agno account cannot use {name}: {reason} Link an account with access to continue."
_LINKING_UNAVAILABLE = "Not run: Agno accounts cannot be checked right now. Try again shortly."
_OWNER_NOT_LINKED = "Not run: the run's owner no longer has a linked Agno account with access."
_EMAIL_HIDDEN = (
    "Slack does not share your email with this app, so your Agno account can't be linked. "
    "Ask whoever manages the Slack app to add the users:read.email scope."
)


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
    if ctx.users is not None and user in ctx.users:
        return ctx.users[user] == event_context.user_id
    if linking_enabled(ctx):
        # Another Slack account linked to the run's Agno account acts as the same person
        try:
            _, authority = await linked_authorization(ctx, client or ctx.web(), user)
        except (PlatformUnavailable, PermissionError):
            return False
        return authority is not None and authority.context.principal_id == event_context.user_id
    if ctx.users is not None:
        return False
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

    await _require_enabled(app, principal_id)
    # The user directory applies on its own, as over HTTP; roles only under AgentOS authorization.
    # The middleware is checked here too: one added after get_app() is not in the flag
    if not _authorization_enforced(app):
        return None
    # Roles are resolved fresh on every check, so a revoked grant applies to the next message
    authority = principal_authorization(app, principal_id, roles)
    await authority.arequire(resource, "run", resource_id)
    return authority


async def _require_enabled(app: Any, principal_id: str, claims: Optional[Dict[str, Any]] = None) -> None:
    """Raise when the user directory marks the principal disabled; with claims, a new user is provisioned."""
    state = getattr(app, "state", None)
    user_store = getattr(state, "user_store", None)
    if user_store is None:
        return
    try:
        if claims is not None and getattr(state, "user_auto_provision", False):
            from agno.os.auth import aprovision_user_with_default_role

            # As over HTTP and WebSocket: a token's first use adds its user to the directory
            provisioned = await aprovision_user_with_default_role(
                user_store,
                getattr(state, "role_store", None),
                principal_id,
                claims,
                email_claim=getattr(state, "user_email_claim", "email"),
                name_claim=getattr(state, "user_name_claim", "name"),
            )
            disabled = bool(provisioned.get("disabled")) if provisioned is not None else False
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


# ==================== Super Agent members acting as their linked Agno accounts ====================


def linking_enabled(ctx: "SlackContext", app: Any = None) -> bool:
    """Whether Super Agent members act as their linked os.agno.com accounts.

    Needs Super Agent, AGNO_OS_SERVICE_TOKEN, and AgentOS authorization with JWT verification, which
    verifies the user tokens the platform issues. users= still applies to the members it maps.
    """
    if getattr(ctx, "company", None) is None or getattr(ctx, "links", None) is None:
        return False
    from agno.os.auth import _authorization_enforced
    from agno.os.utils import resolve_ws_jwt_config

    app = app if app is not None else ctx.app
    enabled = (
        app is not None and _authorization_enforced(app) and resolve_ws_jwt_config(app).get("validator") is not None
    )
    if not enabled and "account_linking" not in ctx.failing:
        log_warning(
            "AGNO_OS_SERVICE_TOKEN is set, but Slack members are not linked to Agno accounts: "
            "that needs AgentOS authorization with JWT verification"
        )
        ctx.failing.add("account_linking")
    return enabled


async def token_authorization(app: Any, token: str) -> Any:
    """The authority of a user token the platform issued, verified as the JWT middleware verifies one.

    Raises PermissionError when the token does not verify, names a reserved principal, or its user is disabled.
    """
    from agno.os.auth import resolve_authorization_provider
    from agno.os.authz.provider import AuthorizationContext
    from agno.os.middleware.jwt import is_reserved_principal, resolve_expected_audience
    from agno.os.utils import resolve_ws_jwt_config
    from agno.run.authorization import RunAuthorization

    config = resolve_ws_jwt_config(app)
    validator = config.get("validator")
    if validator is None:
        raise PermissionError("JWT verification is not configured")
    audience = resolve_expected_audience(
        verify_audience=bool(config.get("verify_audience")),
        audience=config.get("audience"),
        os_id=getattr(app.state, "agent_os_id", None),
    )
    try:
        payload = validator.validate_token(token, audience)
    except Exception as e:
        raise PermissionError(f"Agno account token did not verify: {getattr(e, 'detail', e)}") from e
    claims = validator.extract_claims(payload)
    principal_id = claims.get("user_id")
    if not isinstance(principal_id, str) or not principal_id or is_reserved_principal(principal_id):
        raise PermissionError("Invalid token subject")
    await _require_enabled(app, principal_id, payload)
    return RunAuthorization(
        resolve_authorization_provider(app),
        AuthorizationContext(
            principal_id=principal_id,
            scopes=list(claims.get("scopes") or []),
            claims=payload,
            admin_scope=config.get("admin_scope"),
        ),
        enforce_tools=False,
    )


async def _workspace(ctx: "SlackContext", client: Any) -> Tuple[str, Optional[str]]:
    """The id and name of the bot's Slack workspace, which links are kept under."""
    cached = ctx.lookup_cache.get("workspace")
    if cached is None:
        try:
            response = await client.auth_test()
        except Exception as e:
            raise PlatformUnavailable(f"Could not read the Slack workspace: {e}") from e
        cached = (response.get("team_id") or "", response.get("team"))
        ctx.lookup_cache.set("workspace", cached)
    return cached


async def linked_authorization(
    ctx: "SlackContext", client: Any, member: str, app: Any = None
) -> Tuple[MemberLink, Any]:
    """A Slack member's link, and the authority of their Agno account when linked with access, else None.

    Raises PlatformUnavailable when the platform cannot answer, PermissionError when the account is refused.
    """
    if ctx.links is None:
        raise PlatformUnavailable("AGNO_OS_SERVICE_TOKEN is not set")
    team_id, team_name = await _workspace(ctx, client)
    email, name = await ctx.lookup_cache.user_identity(client, member)
    member_email = email if "@" in email else None
    link = await ctx.links.resolve_slack_member(
        team_id,
        member,
        team_name=team_name,
        member_name=name,
        member_email=member_email,
    )
    # The platform links an account only to the Agno account with the member's Slack email, so without it the
    # link would be refused
    if link.link_url and member_email is None:
        if "users_read_email" not in ctx.failing:
            log_warning("Slack account linking needs the users:read.email scope; members can't link without it")
        ctx.failing.add("users_read_email")
        link = replace(link, link_url=None, reason=_EMAIL_HIDDEN)
    if link.status != "linked" or not link.token:
        return link, None
    try:
        authority = await token_authorization(app if app is not None else ctx.app, link.token)
    except PermissionError:
        ctx.links.forget(team_id, member)
        raise
    return link, authority


async def authorize_linked(
    ctx: "SlackContext",
    event_context: "EventContext",
    client: Any,
    user: str,
    thread_ts: Optional[str] = None,
) -> bool:
    """Run as the owner's linked Agno account; refused otherwise, with a link button when user is the owner."""
    try:
        link, authority = await linked_authorization(ctx, client, event_context.owner)
        if authority is not None:
            await authority.arequire("teams", "run", ctx.entity_id)
    except PlatformUnavailable as e:
        log_warning(f"Slack account linking unavailable: {e}")
        await post_ephemeral(client, event_context.channel, user, _LINKING_UNAVAILABLE, thread_ts)
        return False
    except PermissionError as e:
        await post_ephemeral(client, event_context.channel, user, f"Not run: {e}", thread_ts)
        return False
    if authority is None:
        # Only the member gets the button: whoever confirms a link session links that Slack account to themselves
        if user != event_context.owner:
            await post_ephemeral(client, event_context.channel, user, _OWNER_NOT_LINKED, thread_ts)
        elif link.link_url:
            await post_link_prompt(ctx, client, event_context.channel, user, link, thread_ts)
        else:
            # Linking can't help (the AgentOS's plan or settings, or a hidden Slack email), so only the reason
            reason = link.reason or f"your Agno account cannot use {ctx.entity_name}."
            await post_ephemeral(client, event_context.channel, user, f"Not run: {reason}", thread_ts)
        return False
    event_context.authority = authority
    event_context.user_id = authority.context.principal_id
    act = delegation(authority)
    if act is not None:
        log_debug(f"Slack member {event_context.owner} acts as {event_context.user_id} through {act.get('sub')}")
    return True


def delegation(authority: Any) -> Optional[Dict[str, Any]]:
    """The token's act claim: who acts for the account (this AgentOS, through Slack), when the platform set one."""
    claims = getattr(getattr(authority, "context", None), "claims", None) or {}
    act = claims.get("act")
    return act if isinstance(act, dict) else None


async def post_link_prompt(
    ctx: "SlackContext", client: Any, channel: str, user: str, link: MemberLink, thread_ts: Optional[str] = None
) -> None:
    """The member's private prompt to link their Agno account, or one with access."""
    from agno.os.interfaces.slack.builders import build_link_prompt

    if link.status == "no_access":
        text = _NO_ACCESS_TEXT.format(name=ctx.entity_name, reason=link.reason or "it has no access.")
    else:
        text = _LINK_TEXT.format(name=ctx.entity_name)
    await post_ephemeral(client, channel, user, text, thread_ts, blocks=build_link_prompt(text, link.link_url or ""))
