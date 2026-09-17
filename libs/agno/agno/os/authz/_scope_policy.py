"""The agno scope <-> policy convention.

How an agno scope string is written as a policy ``(resource, action)`` pair and
read back. This is the single source of truth shared by every :class:`PolicyEngine`
implementation, so policy is *written* and *checked* with the same spelling.

Resources use a ``type/id`` shape with ``/*`` for the collection/global form;
``agent_os:admin`` maps to the all-resources/all-actions wildcard ``("*", "*")``.
"""

from typing import Tuple

ADMIN_SCOPE = "agent_os:admin"
# The namespace of the admin scope. Not a resource type: no other scope may use it.
ADMIN_NAMESPACE = ADMIN_SCOPE.split(":")[0]


def scope_to_resource_action(scope: str) -> Tuple[str, str]:
    """Map an agno scope string to its policy ``(resource, action)`` pair.

    - ``agent_os:admin``             -> ("*", "*")
    - ``sessions:write``             -> ("sessions/*", "write")   (collection/global)
    - ``agents:research-agent:run``  -> ("agents/research-agent", "run")
    - ``agents:*:run``               -> ("agents/*", "run")
    """
    if scope == ADMIN_SCOPE:
        return ("*", "*")
    parts = scope.split(":")
    if any(part == "" for part in parts):
        raise ValueError(f"Unrecognised scope (empty component): {scope!r}")
    if parts[0] == ADMIN_NAMESPACE:
        # ``agent_os`` is not a resource type; the only scope in that namespace is the admin
        # super-scope. Anything else here (``agent_os:*:admin``, ``agent_os:x:read``) would be
        # stored under an ``agent_os/...`` resource that grants nothing -- and the read-back
        # of ``agent_os/*`` + ``admin`` used to render as ``agent_os:admin``, so an edit-and-save
        # through the UI or API silently turned a no-op grant into full admin.
        raise ValueError(
            f"Unrecognised scope {scope!r}: {ADMIN_NAMESPACE!r} is not a resource type. The only scope "
            f"in that namespace is {ADMIN_SCOPE!r}."
        )
    if len(parts) == 2:
        resource, action = f"{parts[0]}/*", parts[1]
    elif len(parts) == 3:
        resource, action = f"{parts[0]}/{parts[1]}", parts[2]
    else:
        raise ValueError(f"Unrecognised scope: {scope!r}")
    # Reject an action wildcard. ``*`` in the matcher means "all actions", but the
    # scope provider compares actions literally, so the SAME scope string (e.g.
    # ``agents:*:*``) would grant everything here and nothing there. Refuse it so a
    # managed role can't carry a silently-divergent broad grant; the one documented
    # way to grant all actions is ``agent_os:admin``.
    if action == "*":
        raise ValueError(
            f"Action wildcard '*' is not allowed in scope {scope!r}: it would mean 'all actions' "
            f"in policy but nothing under the scope provider. List explicit actions "
            f"(read/run/write/delete), use a resource-id wildcard like 'agents:*:run', or grant "
            f"'agent_os:admin'."
        )
    return (resource, action)


def resource_action_to_scope(resource: str, action: str) -> str:
    """Best-effort reverse of :func:`scope_to_resource_action`, for display/read-back.

    Lossy where two scope spellings collapse to the same policy (``agents:read``
    and ``agents:*:read`` both store as ``("agents/*", "read")``); we render the
    global ``resource:action`` form in that case.
    """
    if resource == "*":
        return ADMIN_SCOPE
    rtype, _, rid = resource.partition("/")
    if rtype == ADMIN_NAMESPACE:
        # A legacy row under the admin namespace grants nothing, so it must never read back as
        # the admin super-scope: render the explicit three-part form, which the parser now
        # refuses on save, so the row gets cleaned up instead of promoted.
        return f"{rtype}:{rid}:{action}"
    if resource.endswith("/*"):
        return f"{resource[:-2]}:{action}"
    return f"{rtype}:{rid}:{action}"


def resource_matches(pattern: str, request: str) -> bool:
    """Does a policy's ``pattern`` resource match a request's ``request`` resource?

    Glob-style matching over our restricted resource space
    (``"*"`` / ``"type/*"`` / ``"type/id"``):

    - ``"*"``        matches anything (admin),
    - ``"type/*"``   matches ``"type/<id>"`` and the collection key ``"type/*"``
      itself (what a create or list request is evaluated as), but never the bare
      string ``"type"``, which no policy writes,
    - otherwise an exact match.
    """
    if pattern == "*":
        return True
    if pattern == request:
        return True
    if pattern.endswith("/*"):
        return request.startswith(pattern[:-1])  # "type/" prefix
    return False
