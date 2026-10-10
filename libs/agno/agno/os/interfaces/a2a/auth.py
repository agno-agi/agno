from typing import Any, Optional, Tuple

from fastapi import HTTPException, Request

try:
    from a2a.compat.v0_3.types import MessageSendParams
    from a2a.types import SendMessageRequest
    from google.protobuf.json_format import ParseDict
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e


from agno.os.auth import acheck_resource_access, resolve_authorization_provider, run_continuation_blocked_reason
from agno.os.authz.provider import AuthorizationContext
from agno.os.middleware.user_scope import assert_session_writable, caller_is_admin, resolve_run_user_id
from agno.remote.base import BaseRemote
from agno.utils.log import log_warning

# A2A methods that only read, by their v1.0 and v0.3 names. Every other method requires :run.
_READ_METHODS = frozenset(
    {
        "GetTask",
        "ListTasks",
        "SubscribeToTask",
        "GetExtendedAgentCard",
        "GetTaskPushNotificationConfig",
        "ListTaskPushNotificationConfigs",
        "tasks/get",
        "tasks/resubscribe",
        "agent/getAuthenticatedExtendedCard",
        "tasks/pushNotificationConfig/get",
        "tasks/pushNotificationConfig/list",
    }
)
_SEND_METHODS = frozenset({"SendMessage", "SendStreamingMessage", "message/send", "message/stream"})
_CANCEL_METHODS = frozenset({"CancelTask", "tasks/cancel"})


def _get_a2a_message_ids(
    method: Optional[str], request_body: dict
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Get the context id, task id and ``metadata.userId`` of the message a send request carries.

    The message is parsed the way the A2A server parses it, so the checks see the ids the
    run will use: the server accepts ``contextId`` and ``context_id`` for the same field.
    A message the A2A server would reject yields no ids, and is left to it to reject.
    """
    params = request_body.get("params")
    try:
        if method in ("message/send", "message/stream"):
            v0_3_message = MessageSendParams.model_validate(params).message
            return v0_3_message.context_id, v0_3_message.task_id, (v0_3_message.metadata or {}).get("userId")
        message = ParseDict(params, SendMessageRequest(), ignore_unknown_fields=True).message
        client_uid = str(message.metadata["userId"]) if "userId" in message.metadata else None
        return message.context_id or None, message.task_id or None, client_uid
    except Exception:
        return None, None, None


def resolve_a2a_user_id(request: Request, client_uid: Optional[str]) -> Optional[str]:
    """Resolve the run's ``user_id``, mirroring the REST run route's identity pinning.

    A2A must not take run identity from the client: the client-supplied ``X-User-ID``
    header / ``metadata.userId`` is honoured for attribution only when the caller is
    anonymous (see ``resolve_run_user_id`` for the full precedence).
    """
    return resolve_run_user_id(request, request.headers.get("X-User-ID") or client_uid)


async def _authorize_a2a_route(request: Request, resource_type: str, resource_id: str, action: str) -> bool:
    """Ask the authorization provider for its route decision on an A2A method.

    A2A routes are not in the scope map, so the route-level scope gate does not ask
    the provider about them. This asks with the scope the method requires, the way the gate
    asks for a mapped route. A provider that raises is a denial.
    """
    from agno.os.auth import _default_authorization_provider

    state = request.state
    # A service-account PAT and the internal service token carry their scopes as their ACL
    # and have no subject in a managed store, so the scope provider decides for them
    is_scope_caller = getattr(state, "service_account_name", None) is not None or getattr(
        state, "is_internal_service", False
    )
    provider = _default_authorization_provider() if is_scope_caller else resolve_authorization_provider(request)
    admin_scope = getattr(state, "admin_scope", None)
    ctx = AuthorizationContext(
        principal_id=getattr(state, "user_id", None),
        scopes=list(getattr(state, "scopes", None) or []),
        claims=getattr(state, "claims", None) or {},
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        admin_scope=admin_scope if isinstance(admin_scope, str) else None,
    )
    try:
        return await provider.aauthorize_route(ctx, [f"{resource_type}:{action}"])
    except Exception as e:
        log_warning(f"authorization provider raised during route authorization; denying: {e}")
        return False


async def authorize_a2a_access(request: Request, resource_type: str, resource_id: str, action: str) -> None:
    """Check the caller may read or run an entity over A2A, and record the decision.

    Args:
        request: The A2A request
        resource_type: The type of the entity ("agents", "teams", "workflows")
        resource_id: The id of the entity
        action: The action the request requires ("read" or "run")
    """
    # Only check authorization if it's enabled
    if not getattr(request.state, "authorization_enabled", False):
        return

    allowed = await _authorize_a2a_route(request, resource_type, resource_id, action)
    if allowed:
        allowed = await acheck_resource_access(request, resource_id, resource_type, action)

    # Record the per-method decision. The route gate does not see the A2A method,
    # so this is the decision the access audit must show, allowed or denied.
    from agno.os.authz.audit import arecord_decision

    await arecord_decision(
        request,
        allowed=allowed,
        target=f"{request.method} {request.url.path}",
        principal=getattr(request.state, "user_id", None),
        required_scopes=[f"{resource_type}:{resource_id}:{action}"],
        scopes=list(getattr(request.state, "scopes", None) or []),
        claims=getattr(request.state, "claims", None),
        reason=None if allowed else "resource_access_denied",
    )
    if not allowed:
        raise HTTPException(status_code=403, detail=f"Access denied to {action} this {resource_type[:-1]}")


async def authorize_a2a_request(request: Request, resource_type: str, entity: Any) -> None:
    """Authorize an A2A request against the entity it targets, before it reaches the A2A server.

    All A2A methods of an entity share one HTTP route, so the route-level scope gate
    cannot tell reading a task from running the entity. The check happens here, per
    method: reading requires ``read``, everything else requires ``run``.

    1. Read the A2A method
    2. Check the caller may read or run the entity
    3. Check the caller may write to the session and continue the task it names

    Args:
        request: The A2A request
        resource_type: The type of the entity ("agents", "teams", "workflows")
        entity: The Agno Agent, Team or Workflow the request targets
    """
    resource_id = getattr(entity, "id", None) or ""
    db = getattr(entity, "db", None)

    # 1. Read the A2A method
    # A malformed body is left to the A2A server to reject
    try:
        request_body = await request.json()
    except Exception:
        return
    if not isinstance(request_body, dict):
        return
    method = request_body.get("method")
    action = "read" if method in _READ_METHODS else "run"

    # 2. Check the caller may read or run the entity
    await authorize_a2a_access(request, resource_type, resource_id, action)

    # A remote entity runs on another server, which owns the run and its cancellation
    if isinstance(entity, BaseRemote) and method in _CANCEL_METHODS:
        raise HTTPException(status_code=400, detail="Task cancellation is not supported for remote agents")

    if method not in _SEND_METHODS:
        return
    context_id, task_id, client_uid = _get_a2a_message_ids(method, request_body)

    # 3. Check the caller may write to the session and continue the task it names
    # contextId is client-supplied and becomes the session id, so a caller can
    # name another user's session. Refuse before dispatch: the run would otherwise
    # be persisted into that session and replayed as the owner's history.
    await assert_session_writable(
        db,
        context_id,
        resolve_a2a_user_id(request, client_uid) or getattr(entity, "user_id", None),
        is_admin=caller_is_admin(request),
    )

    # A message naming a task continues its run. A run paused on an admin-required approval
    # must not be continued by its own initiator (parity with the REST continue route).
    if task_id:
        reason = await run_continuation_blocked_reason(
            db,
            task_id,
            authorization_enabled=getattr(request.state, "authorization_enabled", False),
            user_scopes=getattr(request.state, "scopes", []),
            request=request,
        )
        if reason:
            raise HTTPException(status_code=403, detail=reason)
