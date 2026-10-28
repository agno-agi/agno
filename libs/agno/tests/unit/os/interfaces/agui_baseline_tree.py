"""The AG-UI interface as it was before the interrupt round trip, importable beside it.

The interrupt outcome is off by default, and the promise that makes it safe to
ship to released clients is that with it off a client receives what it received
before the feature existed. Nothing in the suite pinned that, so it held only for
as long as somebody kept checking it by hand.

Pinning it needs the old emission to run rather than to be described, so the
package as it stood immediately before the round trip is checked in here, one
``.py.snapshot`` per module. Verbatim, and under a suffix the tooling does not
read: a checked-in ``.py`` would be reformatted by this repo's own formatter and
linted against today's rules, and either one edits the baseline, which is the one
thing it may never be. Which revision that is is worked out from HEAD's own
history by ``baseline_revision`` rather than written down, and
``test_agui_emission_identity`` holds every snapshot module against it, so a
snapshot that stops being the code this branch is a change to fails rather than
quietly goes on being compared.

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
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Tuple

# The package the snapshot is of, so the provenance check reads the same files
# back out of the revision it works out.
PACKAGE_PATH_IN_REPO = "libs/agno/agno/os/interfaces/agui"

# The module the round trip added, and the one thing that tells a revision of
# this package apart from the code the round trip was a change to.
FEATURE_MODULE = "interrupts"

SNAPSHOT_DIR = Path(__file__).parent / "agui_baseline"
SNAPSHOT_SUFFIX = ".py.snapshot"

LIVE_PACKAGE = "agno.os.interfaces.agui"
BASELINE_PACKAGE = "agui_before_the_interrupt_round_trip"


class BaselineUnreachable(Exception):
    """This checkout cannot say which revision the snapshot has to be."""


class HistoryTruncated(BaselineUnreachable):
    """And cannot, because it was cloned without the commits the answer is in.

    Kept apart from its base class because it is the one reason a caller may
    decline to run rather than fail. See ``truncation_boundary`` for what has to
    be true of the clone before this is raised, and why no state of the snapshot
    or of the branch can make it true.
    """


def _git(*arguments: str, root: Optional[Path] = None) -> "subprocess.CompletedProcess[str]":
    """One git command, run where ``PACKAGE_PATH_IN_REPO`` means what it says.

    At the root, because a pathspec is read relative to the working directory and
    this one is written from the root. Found rather than counted up from this
    file: a hard-coded number of parent directories is wrong the first time
    anything moves, and wrong in the direction that makes a pathspec match nothing
    and a history walk come back empty.

    ``root`` names a different checkout, which is how the tests put this against
    clones they made themselves rather than against assertions about clones.
    """
    return subprocess.run(["git", *arguments], capture_output=True, text=True, cwd=root or _repo_root())


@lru_cache(maxsize=1)
def _repo_root() -> Path:
    here = Path(__file__).parent
    found = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, cwd=here)
    if found.returncode != 0:
        raise BaselineUnreachable(f"{here} is not inside a git checkout: {found.stderr.strip()}")
    return Path(found.stdout.strip())


@lru_cache(maxsize=1)
def baseline_revision() -> str:
    """The newest revision in HEAD's own history where this package was not yet the feature.

    Worked out rather than written down, because a written-down hash answers a
    different question. What has to be true is that the snapshot is this package
    as the code under HEAD found it; a hash only records where somebody once took
    a copy from. A rebase moves the code underneath and leaves the hash naming an
    abandoned commit, which git goes on reading for as long as the object
    survives, so the check keeps certifying a copy of code nothing is built on.
    That is how this snapshot went stale, and no way of writing a hash down
    prevents it.

    The branch's merge base with main would not do either. The round trip sits on
    top of another unmerged change to this same package, so the merge base is
    older than the code the round trip was a change to, and every difference that
    other change made would be credited to this one.

    Raises ``BaselineUnreachable`` where the answer cannot be worked out, which
    callers have to report as a failure: a provenance check that cannot run has
    not established anything, and saying so quietly is the same hole this
    replaces. The one exception is ``HistoryTruncated``, raised only where the
    commits the answer would be in are demonstrably not in this clone at all.
    """
    revisions = _git("rev-list", "HEAD", "--", PACKAGE_PATH_IN_REPO)
    if revisions.returncode != 0:
        raise BaselineUnreachable(f"git could not walk {PACKAGE_PATH_IN_REPO}: {revisions.stderr.strip()}")
    for revision in revisions.stdout.split():
        if not has_feature(revision):
            return revision
    unreachable = f"no revision of {PACKAGE_PATH_IN_REPO} under HEAD predates {FEATURE_MODULE}.py"
    boundary = truncation_boundary()
    if boundary is None:
        raise BaselineUnreachable(unreachable)
    ends_at, missing_parent = boundary
    raise HistoryTruncated(
        f"{unreachable}, and this clone could not hold one: the history it carries stops at {ends_at}, "
        f"which names a parent {missing_parent} that is not in this object store. The clone was made "
        "without the history (git clone --depth, or actions/checkout with its default fetch-depth of 1). "
        "Fetch it with `git fetch --unshallow`, or give the checkout step `fetch-depth: 0`, and this "
        "check runs."
    )


# A parent as a commit object spells one, in either hash length git uses.
_NAMES_A_PARENT = re.compile(r"^parent ([0-9a-f]{40,64})$", re.MULTILINE)


def truncation_boundary(root: Optional[Path] = None) -> Optional[Tuple[str, str]]:
    """Where HEAD's history stops short of its own beginning, if it does.

    The one condition a caller may decline to run on, and it is deliberately not
    the condition the old pinned-hash guard declined on. That one stood down when
    a revision was unreachable, which is exactly what a rebase produces, so going
    stale silenced the check that exists to catch going stale. Nothing here can
    couple that way, because nothing here reads the snapshot or the branch.

    What is read is the end of the walk. Follow HEAD back to the commits git
    reports as parentless and ask each one's own object what it says. A commit
    that names no parent is a real beginning and the history is all present. A
    commit that names a parent this object store does not hold is not a beginning
    at all: it is where a clone was cut, and the proof is the repository's own
    object contradicting its own walk. Returned as that pair, so a caller can say
    which commit and which missing parent.

    No file in the working tree can produce it. Staleness is content under
    ``SNAPSHOT_DIR``, and writing a file neither puts a parent header on a commit
    object nor takes an object out of the store. Nor can a rebase, the state that
    silenced the old guard: rebasing writes new commits, and every commit
    reachable from the new HEAD still carries its whole ancestry, so the walk
    still ends at a real beginning.

    Conservative where it is unsure. A repository git calls shallow whose cut is
    not reachable from HEAD answers ``None`` here, and the caller fails.
    """
    ends = _git("rev-list", "--max-parents=0", "HEAD", root=root)
    if ends.returncode != 0:
        return None
    for end in ends.stdout.split():
        commit = _git("cat-file", "commit", end, root=root)
        if commit.returncode != 0:
            continue
        for parent in _NAMES_A_PARENT.findall(commit.stdout):
            if _git("cat-file", "-e", parent, root=root).returncode != 0:
                return end, parent
    return None


def has_feature(revision: str) -> bool:
    return _git("cat-file", "-e", f"{revision}:{PACKAGE_PATH_IN_REPO}/{FEATURE_MODULE}.py").returncode == 0


def modules_at(revision: str) -> List[str]:
    """Every module this package had at the given revision."""
    found = _git("ls-tree", "--name-only", revision, f"{PACKAGE_PATH_IN_REPO}/")
    if found.returncode != 0:
        raise BaselineUnreachable(f"{PACKAGE_PATH_IN_REPO} is not in {revision}: {found.stderr.strip()}")
    return [Path(line).stem for line in found.stdout.split() if line.endswith(".py")]


def source_at(revision: str, module: str) -> str:
    """One module of this package as the given revision has it."""
    path = f"{PACKAGE_PATH_IN_REPO}/{module}.py"
    found = _git("show", f"{revision}:{path}")
    if found.returncode != 0:
        raise BaselineUnreachable(f"{path} is not in {revision}: {found.stderr.strip()}")
    return found.stdout


def is_under_head(revision: str) -> bool:
    """Whether a revision is one HEAD is built on, rather than one it merely still holds."""
    return _git("merge-base", "--is-ancestor", revision, "HEAD").returncode == 0


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
