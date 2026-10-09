"""Assert rewriting for the shared stream-invariant helper.

The helper is not a test module, so pytest rewrites its asserts only when it is
registered, and it has to be registered before any suite here imports it, which
is what a conftest guarantees. Unregistered, a broken invariant arrives as a
bare AssertionError without the values that say what the stream actually did.

Registration takes a dotted path and says nothing when it names no module, so a
mistyped or stale path leaves every suite here running against an unrewritten
helper and passing. Both ways that can happen are checked rather than trusted:
the path has to resolve to the helper sitting beside this file, and the helper
must not already be imported, since registering after the import is the other
way this silently does nothing.

The order of those two matters. Resolving the dotted path is what imports the
packages along it, so the helper cannot yet be in ``sys.modules`` when the
lookup has not run, and an import check placed first passes on a tree where one
of those packages imports the helper. The lookup goes first, the import check
second.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_HELPER = "tests.unit.os.interfaces.agui_stream_invariants"
_HELPER_FILE = Path(__file__).with_name("agui_stream_invariants.py").resolve()

assert _HELPER_FILE.exists(), f"the shared stream-invariant helper is gone from {_HELPER_FILE.parent}"

try:
    _spec = importlib.util.find_spec(_HELPER)
except ModuleNotFoundError:  # a package along the dotted path does not exist
    _spec = None
# Both sides resolved: a checkout reached through a symlink gives the spec an
# origin naming this very file by another path, which a string comparison reads
# as some other module and refuses a registration that would have worked.
_origin = Path(_spec.origin).resolve() if _spec is not None and _spec.origin is not None else None
assert _origin == _HELPER_FILE, (
    f"{_HELPER} resolves to {_origin or 'nothing'}, not {_HELPER_FILE}: "
    "registering that path rewrites nothing, and every invariant here would then fail without its values"
)

assert _HELPER not in sys.modules, (
    f"{_HELPER} was imported before this conftest ran, so registering its assert rewrite here does nothing"
)

pytest.register_assert_rewrite(_HELPER)
