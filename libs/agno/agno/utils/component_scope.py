"""Owner-scope for DB-backed component reconstruction.

When a stored team/workflow is loaded for a scoped (non-admin) caller, its
members and nested workflow-step executors must resolve as the same owner, or a
reference to another user's private component would be silently rehydrated.
Reconstruction recurses through ``Team`` ``from_dict`` and the workflow step
tree, so the owner id rides in a ``ContextVar`` rather than threaded through
every nested signature. ``None`` means unscoped (admin / isolation off) and
resolves references regardless of owner.
"""

import contextvars
from contextlib import contextmanager
from typing import Generator, Optional

# Use ContextVar instead of threading.local so the scope is isolated per
# coroutine/task, not per thread, keeping concurrent loads from leaking owners.
_component_owner_scope: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_component_owner_scope", default=None
)


def get_component_owner_scope() -> Optional[str]:
    """Return the owner ``user_id`` to scope member/step resolution to, or None."""
    return _component_owner_scope.get()


@contextmanager
def component_owner_scope(user_id: Optional[str]) -> Generator[None, None, None]:
    """Scope nested DB-backed member/step resolution to ``user_id`` for the block.

    ``user_id=None`` is a no-op (unscoped) and is safe to nest; the previous
    value is always restored on exit.
    """
    token = _component_owner_scope.set(user_id)
    try:
        yield
    finally:
        _component_owner_scope.reset(token)
