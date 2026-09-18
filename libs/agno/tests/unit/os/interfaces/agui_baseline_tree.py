"""The AG-UI interface as it was before the interrupt round trip, importable beside it.

The interrupt outcome is off by default, and the promise that makes it safe to
ship to released clients is that with it off a client receives what it received
before the feature existed. Nothing in the suite pinned that, so it held only for
as long as somebody kept checking it by hand.

Pinning it needs the old emission to run rather than to be described, so the
package as it stood at the commit named in ``BASELINE_COMMIT`` is checked in
here, one ``.py.snapshot`` per module. Verbatim, and under a suffix the tooling
does not read: a checked-in ``.py`` would be reformatted by this repo's own
formatter and linted against today's rules, and either one edits the baseline,
which is the one thing it may never be. ``test_agui_emission_identity`` holds the
snapshot against the commit whenever the checkout can still reach it, so what is
checked in cannot drift from what was released.

Importing it takes one rewrite: the package's own absolute imports of
``agno.os.interfaces.agui.X`` have to reach these modules rather than today's.
Nothing else is touched, so everything outside the package, ``agno.run``,
``agno.models`` and the protocol itself, resolves to the installed one. That is
what makes the comparison one of this interface rather than of its dependencies.
"""

import atexit
import importlib
import re
import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Dict

# The last commit before the interrupt round trip reached this package.
BASELINE_COMMIT = "1aa4b49a8"

# Where the snapshot was taken from, so the provenance check reads the same
# files back out of that commit.
PACKAGE_PATH_IN_REPO = "libs/agno/agno/os/interfaces/agui"

SNAPSHOT_DIR = Path(__file__).parent / "agui_baseline"
SNAPSHOT_SUFFIX = ".py.snapshot"

LIVE_PACKAGE = "agno.os.interfaces.agui"
BASELINE_PACKAGE = "agui_before_the_interrupt_round_trip"


def snapshot_sources() -> Dict[str, str]:
    """Every module of the snapshot, by module name, exactly as it is checked in."""
    return {
        path.name[: -len(SNAPSHOT_SUFFIX)]: path.read_text()
        for path in sorted(SNAPSHOT_DIR.glob("*" + SNAPSHOT_SUFFIX))
    }


def rewritten(source: str) -> str:
    """One snapshot module with its own package's imports pointed at the snapshot.

    Bounded to the package's own dotted name, so an import of anything else in
    ``agno`` still resolves to the installed one. Word-bounded on the right too:
    the live name is a prefix of nothing in the package today but would be of a
    later sibling, and a rewrite that matched one would move a live module in
    under the baseline.
    """
    return re.sub(rf"\b{re.escape(LIVE_PACKAGE)}\b", BASELINE_PACKAGE, source)


def _materialize() -> ModuleType:
    root = Path(tempfile.mkdtemp(prefix="agui-baseline-"))
    atexit.register(shutil.rmtree, root, True)
    package = root / BASELINE_PACKAGE
    package.mkdir()
    for name, source in snapshot_sources().items():
        (package / f"{name}.py").write_text(rewritten(source))
    sys.path.insert(0, str(root))
    return importlib.import_module(BASELINE_PACKAGE)


_package = _materialize()


def module(name: str) -> ModuleType:
    """One module of the baseline package, under the name it has in the live one."""
    return importlib.import_module(f"{BASELINE_PACKAGE}.{name}")


baseline_stream = module("stream")
baseline_router = module("router")
