"""Internal helpers for the RAG retrieval scope override.

When ``AuthorizationConfig(user_isolation=True)`` is on, the agents router
threads the JWT ``sub`` into ``Agent.arun(user_id=...)`` so the run, session,
traces, and metrics are attributed to the caller. For admins (callers with
the configured ``admin_scope``) the same ``user_id`` was — until this fix —
also used by the vector-DB retrieval path, producing the
"admin-uploaded-nothing → admin-sees-no-member-docs" bug from the per-user
isolation rollout: session ownership and retrieval scope are two different
uses of ``user_id`` and need to be decoupled.

To avoid widening every public ``Agent.run`` / ``arun`` overload with a new
``rag_user_id`` kwarg, we carry the override on ``RunContext.dependencies``
under the reserved key below. Userland code that needs the same effect
(e.g. an Agent constructed outside AgentOS) can set the same key — it is
the supported way to ask retrieval to ignore the run's ``user_id``.

Single source of truth so the router, ``_messages`` retrieval path, and
``KnowledgeTools`` all agree on the key name and semantics.
"""

from typing import Any, Dict, Optional

# Reserved key on RunContext.dependencies. The leading/trailing ``__agno_``
# is a soft-namespace so userland callers aren't tempted to name a
# dependency the same thing.
RAG_SCOPE_OVERRIDE_KEY: str = "__agno_rag_scope_override__"

# Sentinel for "retrieve without a user filter" (admin bypass). Distinct
# from ``None`` because ``None`` is what an absent override looks like
# and we need to tell the two apart in the retrieval path.
RAG_SCOPE_ALL: str = "__all__"


def resolve_rag_user_id(
    run_context_user_id: Optional[str],
    dependencies: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Return the ``user_id`` value retrieval should use.

    Precedence:
    1. ``dependencies[RAG_SCOPE_OVERRIDE_KEY] == RAG_SCOPE_ALL`` → ``None``
       (admin bypass — retrieve across all owners).
    2. Otherwise → ``run_context_user_id`` (the regular per-user scope).

    Returning ``None`` is the existing "no owner filter" contract on
    ``Knowledge.search`` / vector-DB backends — see
    ``cookbook/07_knowledge/04_advanced/07_per_user_isolation/README.md``.
    """
    if dependencies is not None and dependencies.get(RAG_SCOPE_OVERRIDE_KEY) == RAG_SCOPE_ALL:
        return None
    return run_context_user_id
