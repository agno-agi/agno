"""Utilities for deep_copy() in Agent, Team, and Workflow.

These classes use @dataclass(init=False) with custom __init__ methods that don't
accept all dataclass fields (e.g. team_id, workflow_id are set at runtime).
deep_copy() must only pass init-accepted fields to the constructor, then restore
non-init fields via setattr.
"""

import inspect
from functools import lru_cache
from typing import FrozenSet, Type


@lru_cache(maxsize=None)
def get_init_params(cls: Type) -> FrozenSet[str]:
    """Return the set of parameter names accepted by cls.__init__ (excluding 'self').

    Results are cached per class since __init__ signatures don't change at runtime.
    """
    sig = inspect.signature(cls.__init__)
    return frozenset(name for name in sig.parameters if name != "self")
