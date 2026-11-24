"""The agno scope <-> policy convention.

How an agno scope string is written as a policy ``(resource, action)`` pair and
read back. This is the single source of truth shared by every :class:`PolicyEngine`
implementation, so policy is *written* and *checked* with the same spelling.

Resources use a ``type/id`` shape with ``/*`` for the collection/global form;
``agent_os:admin`` maps to the all-resources/all-actions wildcard ``("*", "*")``.
"""

from typing import List, Optional, Tuple

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
    # A scope with whitespace in it ("agents:*:read ", "agents: read") is stored as written,
    # matches nothing at the gate, and is invisible in the role view. Refuse it so the typo is
    # caught on save rather than discovered as a denial.
    if any(char.isspace() for char in scope):
        raise ValueError(f"Unrecognised scope {scope!r}: scopes cannot contain whitespace.")
    # The resource type is what the gate matches on; "*" is not a type, so "*:read" would be
    # stored under a "*/..." resource that grants nothing. The one all-resources grant is admin.
    if parts[0] == "*":
        raise ValueError(
            f"Unrecognised scope {scope!r}: '*' is not a resource type. Name the type ('agents:read'), "
            f"or grant {ADMIN_SCOPE!r} for everything."
        )
    # Resources are stored as "type/id", so a "/" in the type would split into a different
    # type on read-back.
    if "/" in parts[0]:
        raise ValueError(f"Unrecognised scope {scope!r}: the resource type cannot contain '/'.")
    # Legacy spelling: the scope provider reads "system:read" as "config:read" (see
    # agno.os.scopes.LEGACY_RESOURCE_ALIASES); store the same spelling so a managed role
    # written with the old name satisfies the route.
    from agno.os.scopes import LEGACY_RESOURCE_ALIASES

    parts[0] = LEGACY_RESOURCE_ALIASES.get(parts[0], parts[0])
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
    if rtype.startswith(_APPLICATION_PREFIX):
        return f"{rtype}:{rid}:{action}"
    if resource.endswith("/*"):
        return f"{resource[:-2]}:{action}"
    return f"{rtype}:{rid}:{action}"


# Resource types whose policy rows may carry the old name. A row under the old name covers both the
# current type and an application's own type of the old name.
_RENAMED_POLICY_TYPES = {"products": "goals"}
# Marks a row that covers only an application's own type of a renamed name. A scope's resource type
# cannot contain ":", so no user-defined type is stored like this. It is written as a four-part scope
# ("application:products:*:read"), which no other scope is.
_APPLICATION_PREFIX = "application:"


def policy_resource(resource: str, requested_type: str) -> Optional[str]:
    """A stored policy's resource, under ``requested_type`` when the policy covers that type by another name.

    None when the policy covers only an application's own type and that is not the one requested.
    """
    resource_type, separator, rest = resource.partition("/")
    if _RENAMED_POLICY_TYPES.get(resource_type) == requested_type:
        return requested_type + separator + rest
    if resource_type.startswith(_APPLICATION_PREFIX):
        covered = resource_type[len(_APPLICATION_PREFIX) :]
        return requested_type + separator + rest if covered == requested_type else None
    return resource


def legacy_resources(resource: str) -> List[str]:
    """The spellings of ``resource`` under the old names of its type."""
    resource_type, separator, rest = resource.partition("/")
    return [old + separator + rest for old, new in _RENAMED_POLICY_TYPES.items() if new == resource_type]


def application_resource(legacy: str) -> str:
    """The resource that keeps a legacy policy for an application's own type only."""
    return _APPLICATION_PREFIX + legacy


def is_legacy_scope(scope: str) -> bool:
    """Whether ``scope`` is spelled with a resource type's old name."""
    return scope.partition(":")[0] in _RENAMED_POLICY_TYPES


def scope_to_policy(scope: str) -> Tuple[str, str]:
    """The ``(resource, action)`` a scope is stored under.

    The old name of a renamed type is kept, and an application-only scope is accepted: it exists
    only in stored policies, so :func:`scope_to_resource_action` refuses it.
    """
    for old in _RENAMED_POLICY_TYPES:
        prefix = f"{_APPLICATION_PREFIX}{old}:"
        if scope.startswith(prefix) and scope.count(":") == 3:
            resource, action = scope_to_resource_action(f"{old}:{scope[len(prefix) :]}")
            return f"{_APPLICATION_PREFIX}{old}/{resource.partition('/')[2]}", action
    resource, action = scope_to_resource_action(scope)
    if is_legacy_scope(scope):
        resource = scope.partition(":")[0] + "/" + resource.partition("/")[2]
    return resource, action


def write_order(scope: str, effect: str) -> int:
    """Where a scope goes in a diff, so that granting a current type cannot rewrite what the diff says of its old name."""
    if not is_legacy_scope(scope):
        return 1
    return 2 if effect == "deny" else 0


def resource_matches(pattern: str, request: str) -> bool:
    """Does a policy's ``pattern`` resource match a request's ``request`` resource?

    Glob-style matching over our restricted resource space
    (``"*"`` / ``"type/*"`` / ``"type/id"``):

    - ``"*"``        matches anything (admin),
    - ``"type/*"``   matches ``"type/<id>"`` and the collection key ``"type/*"``
      itself (what a create or list request is evaluated as), but never the bare
      string ``"type"``, which no policy writes,
    - otherwise an exact match.

    A policy stored under a resource type that was since renamed also matches the current type.
    """
    if pattern == "*":
        return True
    covered = policy_resource(pattern, request.partition("/")[0])
    if covered is None:
        return False
    pattern = covered
    if pattern == request:
        return True
    if pattern.endswith("/*"):
        return request.startswith(pattern[:-1])  # "type/" prefix
    return False
