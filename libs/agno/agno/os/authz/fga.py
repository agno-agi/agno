"""Fine-grained / relationship-based authorization (ReBAC) for AgentOS.

RBAC answers "what may a *role* do?"; FGA answers "what may *this user* do on
*this specific object*, given the relationships between them?" — e.g. "alice may
run workflow-7 because she owns the folder it lives in." That's the model behind
Zanzibar, OpenFGA, and WorkOS FGA.

AgentOS doesn't embed an FGA engine — relationship evaluation belongs in a
purpose-built store (OpenFGA, a WorkOS FGA tenant, SpiceDB, ...). Instead this
plugs any such store into the existing :class:`AuthorizationProvider` seam:

    AuthorizationContext            FGA query
    ─────────────────────────────   ─────────────────────────────────────────
    principal_id  = "alice"     →   user     = "user:alice"
    action        = "run"       →   relation = "run"
    resource_type = "workflows"     object   = "workflows:workflow-7"
    resource_id   = "workflow-7"

So a per-resource check becomes one FGA ``Check`` call, and list-filtering becomes
one ``ListObjects`` call — the two primitives every FGA engine has.

Bring your own backend by implementing the tiny :class:`FGAClient` port (two
methods). :class:`OpenFGAClient` is a batteries-included adapter for OpenFGA
(``pip install "agno[fga]"``); the same provider works against WorkOS FGA or any
other engine by writing an equally small client.

Typical wiring composes FGA (per-resource ReBAC) with the scope provider (coarse
route gating), since FGA has no notion of non-resource routes like ``/config``::

    AuthorizationConfig(authorization_provider=[
        ScopeAuthorizationProvider(),          # gates /config, /sessions, ... by scope
        FGAAuthorizationProvider(fga_client),  # per-resource agents/teams/workflows by relationship
    ])
"""

from typing import List, Optional, Set

from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider

try:  # Protocol is the right type for a duck-typed port; fall back for old pythons.
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore[assignment,misc]


class FGAClient(Protocol):
    """The two relationship queries AgentOS needs from any FGA engine.

    Both speak the engine's own object notation (``"type:id"``), e.g.
    ``check("user:alice", "run", "workflows:wf-7")``. Implement this over OpenFGA,
    WorkOS FGA, SpiceDB, or a test double — :class:`FGAAuthorizationProvider`
    doesn't care which.
    """

    def check(self, user: str, relation: str, obj: str) -> bool:
        """True if ``user`` has ``relation`` to ``obj``."""
        ...

    def list_objects(self, user: str, relation: str, object_type: str) -> List[str]:
        """The objects of ``object_type`` that ``user`` has ``relation`` to,
        as ``"type:id"`` strings (the engine's ListObjects)."""
        ...


class FGAAuthorizationProvider(AuthorizationProvider):
    """An :class:`AuthorizationProvider` that decides via relationship checks
    against an :class:`FGAClient` (OpenFGA / WorkOS FGA / any ReBAC engine).

    It governs the per-resource families (agents/teams/workflows) relationally.
    Routes it can't express as a single object (``/config``, ``/sessions``, the
    scope-gated routes) it ABSTAINS on — so pair it with a scope provider via the
    list form of ``authorization_provider`` (see the module docstring).
    """

    def __init__(
        self,
        client: FGAClient,
        *,
        user_type: str = "user",
        relation_map: Optional[dict] = None,
    ):
        """
        Args:
            client: the relationship engine (see :class:`FGAClient`).
            user_type: the engine's user object type — the subject is sent as
                ``f"{user_type}:{principal_id}"`` (OpenFGA convention, default
                ``"user"``).
            relation_map: optional ``{agno_action: fga_relation}`` overrides when
                your model's relation names differ from agno actions
                (``read``/``run``/``write``/``delete``). Identity by default.
        """
        self._client = client
        self._user_type = user_type
        self._relation_map = relation_map or {}

    def _user(self, ctx: AuthorizationContext) -> Optional[str]:
        return f"{self._user_type}:{ctx.principal_id}" if ctx.principal_id else None

    def _relation(self, action: str) -> str:
        return self._relation_map.get(action, action)

    def check(self, ctx: AuthorizationContext) -> bool:
        # Non-resource check: nothing to ask the relationship engine; defer (the
        # route gate / a composed scope provider handles it). Same contract the
        # scope and engine providers follow.
        if not ctx.resource_type or not ctx.action:
            return True
        user = self._user(ctx)
        if not user:
            return False
        # List endpoint (no specific id): allow, and let accessible_resource_ids
        # narrow the response — mirrors how the middleware filters collections.
        if not ctx.resource_id:
            return True
        return bool(self._client.check(user, self._relation(ctx.action), f"{ctx.resource_type}:{ctx.resource_id}"))

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> Set[str]:
        if not ctx.resource_type or not ctx.action:
            return set()
        user = self._user(ctx)
        if not user:
            return set()
        objects = self._client.list_objects(user, self._relation(ctx.action), ctx.resource_type)
        prefix = f"{ctx.resource_type}:"
        # FGA returns concrete objects (never a wildcard), so we return concrete
        # ids — list endpoints get exactly the set the user is related to.
        return {o[len(prefix) :] for o in objects if o.startswith(prefix)}

    def authorize_route(self, ctx: AuthorizationContext, required_scopes: List[str]) -> bool:
        # Per-resource routes: decide relationally. Everything else (non-resource
        # routes the FGA model doesn't describe) we ABSTAIN on by returning False,
        # so it never fail-opens a /config or /sessions route when OR-composed —
        # a scope provider in the list is expected to authorize those.
        if ctx.resource_type:
            return self.check(ctx)
        return False


class OpenFGAClient:
    """Reference :class:`FGAClient` for OpenFGA. Requires ``pip install "agno[fga]"``.

    Thin wrapper over the OpenFGA Python SDK's *sync* client. Your OpenFGA
    authorization model must define relations matching the agno actions you gate
    (``read``/``run``/``write``/``delete``) on the agent/team/workflow object
    types. Point it at a self-hosted OpenFGA or any OpenFGA-compatible endpoint.
    """

    def __init__(
        self,
        api_url: str,
        store_id: str,
        authorization_model_id: Optional[str] = None,
        credentials=None,
    ):
        try:
            from openfga_sdk import ClientConfiguration
            from openfga_sdk.sync import OpenFgaClient as _OpenFgaClient
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                'OpenFGA support needs the optional extra. Install it with: pip install "agno[fga]"'
            ) from e

        self._client = _OpenFgaClient(
            ClientConfiguration(
                api_url=api_url,
                store_id=store_id,
                authorization_model_id=authorization_model_id,
                credentials=credentials,
            )
        )

    def check(self, user: str, relation: str, obj: str) -> bool:
        from openfga_sdk import ClientCheckRequest

        resp = self._client.check(ClientCheckRequest(user=user, relation=relation, object=obj))
        return bool(getattr(resp, "allowed", False))

    def list_objects(self, user: str, relation: str, object_type: str) -> List[str]:
        from openfga_sdk import ClientListObjectsRequest

        resp = self._client.list_objects(ClientListObjectsRequest(user=user, relation=relation, type=object_type))
        return list(getattr(resp, "objects", []) or [])
