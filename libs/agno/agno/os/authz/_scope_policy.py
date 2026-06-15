"""The agno scope <-> policy convention.

How an agno scope string is written as a policy ``(resource, action)`` pair and
read back. This is the single source of truth shared by every :class:`PolicyEngine`
implementation, so policy is *written* and *checked* with the same spelling.

Resources use a ``type/id`` shape with ``/*`` for the collection/global form;
``agent_os:admin`` maps to the all-resources/all-actions wildcard ``("*", "*")``.
"""

from typing import Tuple

ADMIN_SCOPE = "agent_os:admin"


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
    if resource.endswith("/*"):
        return f"{resource[:-2]}:{action}"
    rtype, _, rid = resource.partition("/")
    return f"{rtype}:{rid}:{action}"


def resource_matches(pattern: str, request: str) -> bool:
    """Does a policy's ``pattern`` resource match a request's ``request`` resource?

    Glob-style matching over our restricted resource space
    (``"*"`` / ``"type/*"`` / ``"type/id"``):

    - ``"*"``        matches anything (admin),
    - ``"type/*"``   matches ``"type/<id>"`` but NOT the bare collection
      ``"type"`` (a collection request is handled via accessible-ids, not the
      route gate),
    - otherwise an exact match.
    """
    if pattern == "*":
        return True
    if pattern == request:
        return True
    if pattern.endswith("/*"):
        return request.startswith(pattern[:-1])  # "type/" prefix
    return False
