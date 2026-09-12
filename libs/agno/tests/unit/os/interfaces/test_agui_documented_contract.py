"""The AG-UI cookbook's documented contract, read out of the document and checked.

The 16_agui README and TEST_LOG restate facts that live in the interface: which
events carry a member's ``subagentRunId``, which visibility values exist and
which one is the default, what an announcement's parent links are called, which
files the folder holds. A restatement that nothing recomputes drifts silently,
so every enumerable claim is parsed out of the document here and compared with
the implementation's own constants rather than with a second copy of them.
Adding an event type to the interface, or a visibility value, or a field to any
of the lineage events, without saying so in the README fails one of these tests.

Genuine prose is left alone. Only claims that enumerate something the code
already enumerates are pinned.
"""

import ast
import importlib
import inspect
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import BaseEvent, RunAgentInput

from agno.models.response import ToolExecution, UserInputField
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.agui import handlers as agui_handlers
from agno.os.interfaces.agui import interrupts as agui_interrupts
from agno.os.interfaces.agui import state as agui_state
from agno.os.interfaces.agui.handlers import on_run_completed, validate_subagent_visibility
from agno.os.interfaces.agui.resume import (
    ADVERTISED_KEYWORDS_READ,
    RESUME_RESOLVED,
    SCHEMA_ANNOTATIONS,
    SCHEMA_COMPLETENESS,
)
from agno.os.interfaces.agui.state import SUBAGENT_VISIBILITY_VALUES, StreamState
from agno.run.agent import RunPausedEvent
from agno.run.requirement import RunRequirement
from agno.tools.function import UserFeedbackOption, UserFeedbackQuestion

from .agui_stream_invariants import (
    LINEAGE_EVENTS_PROTOCOL_FLOOR,
    assert_well_formed_stream,
    needs_lineage_events,
    require_lineage_events,
)

_REPO_ROOT = Path(__file__).resolve().parents[6]
_COOKBOOK = _REPO_ROOT / "cookbook" / "05_agent_os" / "16_agui"
_README = _COOKBOOK / "README.md"
_TEST_LOG = _COOKBOOK / "TEST_LOG.md"
_EXAMPLE = _COOKBOOK / "team_subagent_lineage.py"
_INTERRUPT_EXAMPLE = _COOKBOOK / "interrupt_round_trip.py"

# The examples that ask for an optional part of the protocol, and so have to name
# the release that first served it. Listed rather than discovered, because an
# example that stops naming its floor is exactly what the check below is for and
# a discovery rule keyed on the naming would then find nothing to check.
_FLOOR_EXAMPLES = (_EXAMPLE, _INTERRUPT_EXAMPLE)
_PACKAGE_PYPROJECT = _REPO_ROOT / "libs" / "agno" / "pyproject.toml"

# A floor as any of the documents write it: the release named in prose after the
# package, the constraint the reader is told to install, and the constraint the
# package's own extra declares. One pattern for every check below, so two of
# them cannot disagree about what counts as a stated floor and read different
# sets out of the same document.
_FLOOR = r"ag-ui-protocol[`'\s>=]{1,4}(\d+\.\d+\.\d+)"

# The root is identified by the package these tests are about, which sits at a
# fixed place under it. Counted wrong, the walk above lands somewhere with no
# cookbook under it, and every document read below then reads as a checkout
# that ships none: moving this file one directory turned most of this module
# into skips, the protocol-floor check among them.
assert (_REPO_ROOT / "libs" / "agno" / "agno" / "os" / "interfaces" / "agui").is_dir(), (
    f"{_REPO_ROOT} is not this repository's root, so every document this module reads would be "
    "reported as absent from the checkout rather than checked"
)

# The sentence the machine-checkable event list hangs off. Kept as one string so
# a README that drops the list fails here instead of passing vacuously.
_ATTRIBUTED_LIST_MARKER = "These are the events that carry a `subagentRunId`:"
_UNATTRIBUTED_MARKER = "kinds of event carry none."

# The unattributed marker does carry a count, one word ahead of it, so that word
# is recomputed from the same paragraph rather than left to be edited in
# lockstep. Spelled numbers only, which is how the document writes it.
_SPELLED_COUNTS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}


def _doc(path: Path) -> str:
    """One document of the cookbook folder, skipped only when the folder itself is gone.

    A checkout can ship without the cookbook, which is the one thing worth
    skipping for. A file missing from a folder that is there is a document this
    module was written against and no longer holds, so it fails.
    """
    if not _COOKBOOK.is_dir():
        pytest.skip("cookbook not present in this checkout")
    assert path.exists(), f"the cookbook folder no longer holds {path.name}, which this module reads"
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """One section of a markdown document, heading excluded.

    Anchored at the start of a line, so a heading named in a sentence somewhere
    above cannot be mistaken for the section itself, and reported rather than
    raised bare, so a renamed heading says which one went missing.

    The section ends at the next heading of any depth, the document's own title
    level included. Cut at a `##` heading alone, a `###` subsection was read as
    part of the section holding it, so a claim checked against one section could
    be satisfied by a sentence in a subsection about something else, and a
    subsection could not be read on its own at all. Cut at `##` and deeper, a
    section that a `#` heading ends ran on to the end of the document, which is
    the same failure one level up.
    """
    found = re.search(rf"^{re.escape(heading)}$", text, re.MULTILINE)
    assert found is not None, f"the document no longer has a {heading!r} section, so nothing here can read it"
    rest = text[found.end() :]
    end = re.search(r"^#{1,6} ", rest, re.MULTILINE)
    return rest if end is None else rest[: end.start()]


def _attribution_section() -> str:
    return _section(_doc(_README), "## Team member attribution")


# Every place the README accounts for the member surface. The attribution
# section describes the lanes themselves; the subsection on a member the run
# paused inside describes what a member's terminal carries when the pause was
# reported inside it, which is where one of that terminal's own fields is
# documented. A census of those fields has to read both, or a field documented
# in one reads as undocumented because the other was the section that was handy.
_MEMBER_SURFACE_HEADINGS = ("## Team member attribution", "### A member the run paused inside")


def _member_surface_documentation() -> str:
    readme = _doc(_README)
    return "\n\n".join(_section(readme, heading) for heading in _MEMBER_SURFACE_HEADINGS)


def test_a_section_ends_at_the_next_heading_of_any_depth():
    """A subsection is a section of its own, not the tail of the one holding it.

    The last two hold the shallowest heading level: a section the document's own
    title ends must not run on into whatever the next title introduces.
    """
    document = "## One\n\nfirst\n\n### Under one\n\nsecond\n\n## Two\n\nthird\n\n# Elsewhere\n\nfourth\n"
    assert _section(document, "## One").split() == ["first"]
    assert _section(document, "### Under one").split() == ["second"]
    assert _section(document, "## Two").split() == ["third"]
    assert _section(document, "# Elsewhere").split() == ["fourth"]


_FIRST_CELL = re.compile(r"^\| `([^`]+)`([^|]*)\|")


def _table_rows(section: str) -> List[Tuple[str, str]]:
    """(backticked value, rest of that first cell) per table row, first cell only.

    Read with one pattern rather than by splitting on backticks and pipes,
    which raises an index error of its own on a row shaped differently, and cut
    at the first cell so a word in the row's description cannot be read as a
    mark on its value.
    """
    rows: List[Tuple[str, str]] = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        found = _FIRST_CELL.match(line)
        assert found is not None, f"this table row does not open with a backticked cell: {line}"
        rows.append((found.group(1), found.group(2)))
    return rows


def _first_column_entries(section: str) -> List[str]:
    """The backticked value opening every table row in a section."""
    return [value for value, _ in _table_rows(section)]


def _backticked(text: str) -> List[str]:
    return re.findall(r"`([^`\n]+)`", text)


def _unwrapped(text: str) -> str:
    """One piece of prose with the document's own line wrapping taken out.

    Every claim below is read off prose normalised here rather than off the raw
    text, because a hard-wrapped document breaks a claim wherever the line
    happens to end and a parse that reads the raw text then says the document
    stopped making it. An inline-code span that wrapped desynchronised the
    backtick reader onto the next span, and a phrase that wrapped between two of
    its own words was not found at all. Normalised in one place, so no two
    parses can disagree about what the document says.
    """
    return " ".join(text.split())


def _paragraphs(text: str) -> List[str]:
    """The paragraphs of one piece of prose, each with its wrapping taken out.

    Paragraph by paragraph rather than whole, so a fenced block stays a block of
    its own rather than being run into the prose around it and pairing every
    backtick after it wrongly.
    """
    return [_unwrapped(paragraph) for paragraph in re.split(r"\n\s*\n", text)]


def test_a_claim_reads_the_same_whether_it_wraps_or_sits_on_one_line():
    """The document's line wrapping is the document's, not the claim's.

    A claim dropped because it wrapped is a claim nothing checks, so the
    document can then drift by being reflowed. Both halves are held here: the
    wrapped form reads as the same claim as the unwrapped one, and a span whose
    own content wraps stays one token instead of resynchronising the reader onto
    the backtick after it.
    """
    wrapped = 'The `STATE_DELTA` and the `{"type": "suspended",\n"interruptIds": [...]}` it carries.'
    assert _backticked(_unwrapped(wrapped)) == ["STATE_DELTA", '{"type": "suspended", "interruptIds": [...]}']
    assert _backticked(_unwrapped(wrapped)) == _backticked(_unwrapped(wrapped.replace("\n", " ")))


def _expand_event_token(token: str) -> Set[str]:
    """An event name, or the documented ``PREFIX_*`` family, within what is emitted.

    Expanded over the events this interface emits rather than over the installed
    protocol's whole enumeration. A family covers whatever the protocol adds to
    it, and an addition this interface never emits is not something the README
    can be expected to have accounted for.
    """
    emitted = _implementation_emitted_events()
    if token.endswith("_*"):
        prefix = token[:-1]
        return {name for name in emitted if name.startswith(prefix)}
    return {token} & emitted


def _implementation_attributed_events() -> Set[str]:
    return {event_type.value for event_type in agui_handlers._SUBAGENT_ATTRIBUTABLE_EVENT_TYPES}


_AG_UI = "ag_ui"
_AG_UI_CORE = "ag_ui.core"
_CORE = "core"


def _dotted(node: ast.expr) -> Optional[str]:
    """A ``Name`` or dotted ``Attribute`` chain rendered back as source text."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _protocol_module(name: str) -> Optional[ModuleType]:
    """One module of the installed protocol, or None on a release that has no such module."""
    if name != _AG_UI_CORE and not name.startswith(_AG_UI_CORE + "."):
        return None
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _names_the_protocol(module: Optional[str]) -> bool:
    """Whether a from-import's module is ``ag_ui.core`` or a submodule of it.

    The package re-exports its event classes and the interface imports them
    from there, but importing the same class out of the submodule that defines
    it is the same construction and this census has to see it.
    """
    return module == _AG_UI_CORE or (module or "").startswith(_AG_UI_CORE + ".")


def _event_class_named(name: str, module: str = _AG_UI_CORE) -> Optional[type]:
    """An AG-UI event class of the protocol, by the name the protocol gives it.

    Looked for on the module the import named and then on the package that
    re-exports it, so a class taken out of a submodule resolves whichever of the
    two the installed release defines it on.
    """
    for where in (module, _AG_UI_CORE):
        found = getattr(_protocol_module(where), name, None)
        if isinstance(found, type) and issubclass(found, BaseEvent):
            return found
    return None


def _event_classes_by_local_name(tree: ast.Module) -> Dict[str, type]:
    """Every AG-UI event class one module imported, under the name it uses locally.

    Aliased imports are what make a text search unreliable here: the interface
    imports the protocol's run-error event under a name of its own.
    """
    classes: Dict[str, type] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not _names_the_protocol(node.module):
            continue
        for alias in node.names:
            imported = _event_class_named(alias.name, node.module or _AG_UI_CORE)
            if imported is not None:
                classes[alias.asname or alias.name] = imported
    return classes


def _core_module_aliases(tree: ast.Module) -> Dict[str, str]:
    """Every local dotted prefix that reaches the protocol, against the module it names.

    An event built through the module rather than through a from-imported class
    is the same construction, and reading only ``Call`` nodes whose callee is a
    bare name misses it. Reading any attribute call by its last segment instead
    would credit ``anything.RawEvent(...)``, so the prefixes are resolved here
    and nothing else is treated as the protocol.

    ``import ag_ui`` binds the package alone, and the protocol is then reached
    one attribute further along, which is why the prefix recorded for it carries
    that attribute rather than the bound name.

    A submodule imported out of the protocol, ``from ag_ui.core import events``,
    binds a name that reaches it too, so it is recorded here as well: a name
    imported that way is a module only on the installed release, which is what
    decides it rather than the shape of the import.
    """
    aliases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _AG_UI:
                    aliases[f"{alias.asname or _AG_UI}.{_CORE}"] = _AG_UI_CORE
                elif alias.name == _AG_UI_CORE or alias.name.startswith(_AG_UI_CORE + "."):
                    # Without an alias the whole dotted path is what the source
                    # writes, since the name bound is the top package.
                    aliases[alias.asname or alias.name] = alias.name
                    if alias.asname is None:
                        # The statement binds the top package, so everything
                        # under it is reachable, not only the submodule named:
                        # ``import ag_ui.core.events`` and then
                        # ``ag_ui.core.RawEvent()`` is the same construction as
                        # the one written through the module it was imported
                        # from, and was credited to no scope at all.
                        aliases.setdefault(_AG_UI_CORE, _AG_UI_CORE)
        elif isinstance(node, ast.ImportFrom) and node.module == _AG_UI:
            for alias in node.names:
                if alias.name == _CORE:
                    aliases[alias.asname or _CORE] = _AG_UI_CORE
        elif isinstance(node, ast.ImportFrom) and _names_the_protocol(node.module):
            for alias in node.names:
                submodule = f"{node.module}.{alias.name}"
                if _protocol_module(submodule) is not None:
                    aliases[alias.asname or alias.name] = submodule
    return aliases


def _protocol_module_reached_by(prefix: str, aliases: Dict[str, str]) -> Optional[str]:
    """The protocol module a local dotted prefix reaches, submodules included.

    A prefix can name a module the source never imported by name: ``import
    ag_ui`` and then ``ag_ui.core.events.RawEvent()`` reaches the submodule
    through the package alone. So the longest prefix that is a recorded alias is
    resolved and whatever the source wrote after it is read as the path below
    that module, and the result has to be a module of the protocol for the call
    to count. Nothing else does: ``ag_ui.core.registry.RawEvent()`` resolves to
    no module and is credited to no scope.
    """
    segments = prefix.split(".")
    for cut in range(len(segments), 0, -1):
        base = aliases.get(".".join(segments[:cut]))
        if base is None:
            continue
        module = ".".join([base, *segments[cut:]])
        if _protocol_module(module) is not None:
            return module
    return None


def _constructed_event_class(func: ast.expr, classes: Dict[str, type], aliases: Dict[str, str]) -> Optional[type]:
    """The AG-UI event class a call constructs, or None when it constructs none."""
    if isinstance(func, ast.Name):
        return classes.get(func.id)
    if isinstance(func, ast.Attribute):
        prefix = _dotted(func.value)
        module = _protocol_module_reached_by(prefix, aliases) if prefix is not None else None
        if module is not None:
            return _event_class_named(func.attr, module)
    return None


def _event_type_default(event_class: type) -> str:
    """The event type a protocol class declares, reported rather than raised for.

    A class with no concrete default has nothing to name it by. Read straight
    through, that arrives as an attribute error from inside the scan, which
    takes down this module and the hostile-content suite whose census rests on
    it instead of saying which class is unreadable. A class declaring no ``type``
    field at all has to arrive the same way, so the field is looked up rather
    than indexed: indexed, that one case raises a bare key error and the message
    below, which is the whole point of the guard, is never reached.
    """
    field = event_class.model_fields.get("type")  # type: ignore[attr-defined]
    declared = getattr(field, "default", None)
    assert getattr(declared, "value", None) is not None, (
        f"{event_class.__name__} declares {declared!r} as its event type, which names no event: "
        "the census cannot say what a scope building one of these builds"
    )
    return str(declared.value)


# Every node that starts a scope of its own. A construction inside one belongs
# to that scope and not to the scope holding it, so a helper defined inside a
# function cannot be covered by driving the function around it.
def _scan_scope(
    body: List[ast.stmt],
    scope: str,
    classes: Dict[str, type],
    aliases: Dict[str, str],
    built: Dict[str, Set[str]],
) -> None:
    for statement in body:
        _scan_node(statement, scope, classes, aliases, built)


def _scan_node(
    node: ast.AST,
    scope: str,
    classes: Dict[str, type],
    aliases: Dict[str, str],
    built: Dict[str, Set[str]],
) -> None:
    """Record the event constructions in one scope, nested scopes named separately."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        # A decorator, a default and a base class are evaluated where the
        # definition is written, so they stay in the enclosing scope.
        for outer in [*node.decorator_list, *getattr(node, "bases", [])]:
            _scan_node(outer, scope, classes, aliases, built)
        if not isinstance(node, ast.ClassDef):
            for outer in [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]:
                _scan_node(outer, scope, classes, aliases, built)
        _scan_scope(node.body, f"{scope}.{node.name}", classes, aliases, built)
        return
    if isinstance(node, ast.Lambda):
        for outer in [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]:
            _scan_node(outer, scope, classes, aliases, built)
        # Named by where it is written, because a lambda has no name of its own
        # and two written side by side are two scopes: called ``<lambda>`` alike,
        # they merged, and one of them was then credited with what the other
        # builds, which is the same wrong two same-named functions in one module
        # would be.
        _scan_node(node.body, f"{scope}.<lambda:{node.lineno}:{node.col_offset}>", classes, aliases, built)
        return
    if isinstance(node, ast.Call):
        event_class = _constructed_event_class(node.func, classes, aliases)
        if event_class is not None:
            built.setdefault(scope, set()).add(_event_type_default(event_class))
    for child in ast.iter_child_nodes(node):
        _scan_node(child, scope, classes, aliases, built)


MODULE_SCOPE = "<module>"


def event_constructions_in(module_name: str, source: str) -> Dict[str, Set[str]]:
    """Every AG-UI event type one module's source builds, per scope that builds it.

    Scopes are named ``module.function``, and a scope nested inside another is
    named through it, so two modules holding a function of the same name are two
    entries rather than one merged set. Code at a module's top level is named
    ``module.<module>``: an event built there is built once at import and never
    driven by any run, which is a fact about the package rather than something
    to leave unreported.
    """
    tree = ast.parse(source)
    built: Dict[str, Set[str]] = {}
    _scan_scope(
        tree.body,
        module_name,
        _event_classes_by_local_name(tree),
        _core_module_aliases(tree),
        built,
    )
    return {f"{scope}.{MODULE_SCOPE}" if scope == module_name else scope: events for scope, events in built.items()}


def event_constructions_by_function() -> Dict[str, Set[str]]:
    """Every AG-UI event type the interface builds, per source scope that builds it.

    Read off the event classes the package constructs rather than off mentions
    of ``EventType.X``, which count a comparison against a type this interface
    never emits. It is a scan of source, so it says which scopes build which
    events, not which of them any particular run reaches.

    Shared with the hostile-content suite, which uses the same scan to check
    that its table of event-building boundaries names every one of them.
    """
    package = Path(agui_handlers.__file__).parent
    built: Dict[str, Set[str]] = {}
    for module in sorted(package.glob("*.py")):
        for scope, events in event_constructions_in(module.stem, module.read_text(encoding="utf-8")).items():
            built.setdefault(scope, set()).update(events)
    assert built, "found no AG-UI event constructions in the interface package"
    return built


# Sources that build one AG-UI event by a route the scan above has to see. Each
# was a way a construction went unrecorded, so each is written out here rather
# than described: a scan that stops seeing one of these stops being the census
# the coverage test in the hostile-content suite rests on.
_CONSTRUCTIONS_THE_SCAN_HAS_TO_SEE: Dict[str, Tuple[str, str]] = {
    "through the module it was imported from": (
        "import ag_ui.core\n\ndef builds():\n    ag_ui.core.RawEvent()\n",
        "scanned.builds",
    ),
    "through an aliased module": (
        "import ag_ui.core as protocol\n\ndef builds():\n    protocol.RawEvent()\n",
        "scanned.builds",
    ),
    "through a module imported from its package": (
        "from ag_ui import core\n\ndef builds():\n    core.RawEvent()\n",
        "scanned.builds",
    ),
    "from the submodule that defines it": (
        "from ag_ui.core.events import RawEvent\n\ndef builds():\n    RawEvent()\n",
        "scanned.builds",
    ),
    "through the top package alone": (
        "import ag_ui\n\ndef builds():\n    ag_ui.core.RawEvent()\n",
        "scanned.builds",
    ),
    "through the top package under an alias": (
        "import ag_ui as protocol\n\ndef builds():\n    protocol.core.RawEvent()\n",
        "scanned.builds",
    ),
    "through an imported submodule": (
        "import ag_ui.core.events\n\ndef builds():\n    ag_ui.core.events.RawEvent()\n",
        "scanned.builds",
    ),
    "through the package an imported submodule binds": (
        "import ag_ui.core.events\n\ndef builds():\n    ag_ui.core.RawEvent()\n",
        "scanned.builds",
    ),
    "through a submodule imported out of the protocol": (
        "from ag_ui.core import events\n\ndef builds():\n    events.RawEvent()\n",
        "scanned.builds",
    ),
    "through a submodule of the top package alone": (
        "import ag_ui\n\ndef builds():\n    ag_ui.core.events.RawEvent()\n",
        "scanned.builds",
    ),
    "at a module's own top level": (
        "from ag_ui.core import RawEvent\n\nPRELUDE = RawEvent()\n",
        f"scanned.{MODULE_SCOPE}",
    ),
    "in a function nested inside another": (
        "from ag_ui.core import RawEvent\n\ndef outer():\n    def inner():\n        RawEvent()\n\n    return inner\n",
        "scanned.outer.inner",
    ),
    "in a method of a class": (
        "from ag_ui.core import RawEvent\n\nclass Builder:\n    def build(self):\n        RawEvent()\n",
        "scanned.Builder.build",
    ),
    "in a lambda": (
        "from ag_ui.core import RawEvent\n\ndef outer():\n    return lambda: RawEvent()\n",
        "scanned.outer.<lambda:4:11>",
    ),
}


@pytest.mark.parametrize("route", sorted(_CONSTRUCTIONS_THE_SCAN_HAS_TO_SEE))
def test_the_event_scan_records_a_construction_reached_by_each_route(route):
    """One construction per route, credited to the scope that really writes it."""
    source, scope = _CONSTRUCTIONS_THE_SCAN_HAS_TO_SEE[route]
    assert event_constructions_in("scanned", source) == {scope: {"RAW"}}


def test_the_event_scan_credits_no_scope_that_only_encloses_the_construction():
    """A nested scope's construction is that scope's alone.

    Credited to the function around it, a helper defined inside another is
    covered by driving the outer one, which drives none of it.
    """
    source = (
        "from ag_ui.core import RawEvent\n\ndef outer():\n    def inner():\n        RawEvent()\n\n    return inner\n"
    )
    assert "scanned.outer" not in event_constructions_in("scanned", source)


def test_the_event_scan_reads_no_event_off_an_attribute_of_something_else():
    """Only ``ag_ui.core`` itself, and the modules under it, are the protocol.

    Reading any attribute call by its last segment would credit a scope with an
    event it never built, which is the other way this census can go wrong. The
    second source is the same mistake one attribute further along: resolving a
    prefix through the protocol is what lets a submodule of it be reached
    without being imported by name, and a name under it that is no module of the
    protocol has to stay uncredited.
    """
    source = "from ag_ui.core import RawEvent\n\ndef builds(registry):\n    registry.RawEvent()\n"
    assert event_constructions_in("scanned", source) == {}
    reached_through = "import ag_ui\n\ndef builds():\n    ag_ui.core.registry.RawEvent()\n"
    assert event_constructions_in("scanned", reached_through) == {}


def test_a_dotted_import_under_an_alias_binds_the_alias_and_nothing_else():
    """Only the name the statement really binds reaches the protocol.

    A dotted import binds the top package, and one written ``as`` binds the
    alias instead, so the dotted path the source could otherwise have written
    reaches nothing and a call through it is no construction of this package's.
    """
    source = "import ag_ui.core.events as protocol\n\ndef builds():\n    ag_ui.core.RawEvent()\n"
    assert event_constructions_in("scanned", source) == {}


def test_the_event_scan_keeps_two_lambdas_of_one_scope_apart():
    """Two lambdas written side by side are two scopes, not one.

    Merged under one ``<lambda>`` name, the one that builds nothing is credited
    with what the one beside it builds, so a boundary the hostile-content table
    claims is covered by driving its neighbour.
    """
    source = (
        "from ag_ui.core import RawEvent, CustomEvent\n\n"
        "def outer():\n    return (lambda: RawEvent(), lambda: CustomEvent())\n"
    )
    built = event_constructions_in("scanned", source)
    assert sorted(built.values(), key=sorted) == [{"CUSTOM"}, {"RAW"}]
    assert len(built) == 2, f"two lambdas were credited to {sorted(built)}"


def test_the_event_scan_keeps_two_modules_same_named_functions_apart():
    """One name in two modules is two scopes.

    Merged, a function that builds nothing is credited with what its namesake
    elsewhere builds, and a row of the hostile-content table claiming either one
    accounts for both.
    """
    source = "from ag_ui.core import RawEvent\n\ndef build():\n    RawEvent()\n"
    first = event_constructions_in("one", source)
    second = event_constructions_in("two", source)
    assert set(first) == {"one.build"}
    assert set(second) == {"two.build"}
    assert not set(first) & set(second)


def _implementation_emitted_events() -> Set[str]:
    """Every AG-UI event type the interface's own source constructs an event of."""
    return set().union(*event_constructions_by_function().values())


def _documented_attributed_events() -> Set[str]:
    """The event names listed in the README's fenced block, which must be exact."""
    section = _attribution_section()
    assert _ATTRIBUTED_LIST_MARKER in section, (
        f"the attribution section no longer contains {_ATTRIBUTED_LIST_MARKER!r}, "
        "so the documented event list cannot be checked against the code"
    )
    after = section[section.index(_ATTRIBUTED_LIST_MARKER) + len(_ATTRIBUTED_LIST_MARKER) :]
    fence = re.search(r"```[a-z]*\n(.*?)```", after, re.DOTALL)
    assert fence is not None, "the documented event list is no longer a fenced block"
    return set(fence.group(1).split())


def _unattributed_paragraph() -> str:
    """The whole paragraph that accounts for the events carrying no ``subagentRunId``.

    Read from where the paragraph starts rather than from the marker inside it.
    Started at the marker, the sentence carrying it began half way through, and
    everything the paragraph said before it went unread: the count that has to
    match what the paragraph then names sits in that half.
    """
    section = _attribution_section()
    assert _UNATTRIBUTED_MARKER in section, f"the attribution section no longer contains {_UNATTRIBUTED_MARKER!r}"
    marker = section.index(_UNATTRIBUTED_MARKER)
    opens = section.rfind("\n\n", 0, marker)
    return section[0 if opens == -1 else opens + 2 :].split("\n\n")[0]


def _sentences(paragraph: str) -> List[str]:
    """The sentences of one paragraph, its line wrapping taken out."""
    return [sentence for sentence in re.split(r"(?<=\.)\s+", _unwrapped(paragraph)) if sentence]


def _documented_unattributed_events() -> Set[str]:
    """The event families the README says carry no ``subagentRunId``.

    Read off the unwrapped paragraph, like its two siblings: read off the raw
    text, a span that wrapped left the backtick reader pairing the close of one
    token with the open of the next, and the prose between them was then
    reported as an event this interface does not emit.
    """
    paragraph = _unattributed_paragraph()
    documented: Set[str] = set()
    for token in _backticked(_unwrapped(paragraph)):
        expanded = _expand_event_token(token)
        assert expanded, f"the README names {token!r} as unattributed, and this interface emits no such event"
        documented.update(expanded)
    return documented


def _subagent_event_classes() -> Dict[str, type]:
    require_lineage_events()
    from ag_ui.core import SubagentErrorEvent, SubagentFinishedEvent, SubagentStartedEvent

    return {
        "SUBAGENT_STARTED": SubagentStartedEvent,
        "SUBAGENT_FINISHED": SubagentFinishedEvent,
        "SUBAGENT_ERROR": SubagentErrorEvent,
    }


def _own_field_aliases(event_class: type) -> Set[str]:
    """The event's own payload fields, named as the wire names them.

    A field the protocol gave no alias is named as the model names it, so a
    documented field name can carry underscores.
    """
    return {
        field.alias or name
        for name, field in event_class.model_fields.items()  # type: ignore[attr-defined]
        if name not in BaseEvent.model_fields
    }


def test_the_documented_event_list_is_the_implementations_own_set():
    assert _documented_attributed_events() == _implementation_attributed_events(), (
        "the README's list of events carrying a subagentRunId no longer matches "
        "_SUBAGENT_ATTRIBUTABLE_EVENT_TYPES in agno/os/interfaces/agui/handlers.py"
    )


@needs_lineage_events
def test_every_event_the_interface_emits_unattributed_is_documented_as_such():
    # The documented families include the lineage events, which an install
    # without them cannot name at all.
    unattributed = _implementation_emitted_events() - _implementation_attributed_events()
    assert _documented_unattributed_events() == unattributed, (
        "the README's account of which events carry no subagentRunId no longer "
        "matches what the interface emits without one"
    )


def test_the_documented_count_of_unattributed_kinds_matches_the_kinds_it_then_names():
    """The count one word ahead of the marker, against the kinds the paragraph names.

    Recomputed from the same paragraph, so the sentence cannot keep saying
    "three" while accounting for a fourth kind underneath it. A kind is one
    sentence's account of one group of events, which is how the paragraph itself
    is written: the two state events are named in one sentence and are one kind.
    Grouping the names by the prefix they open with instead read two kinds that
    share a prefix as one, so a paragraph that grew a separate account of
    another ``RUN_`` event went on counting as three.
    """
    paragraph = _unattributed_paragraph()
    sentences = _sentences(paragraph)
    counted = re.search(r"(\w+) " + re.escape(_UNATTRIBUTED_MARKER), _unwrapped(paragraph))
    assert counted is not None, f"nothing in the paragraph counts the {_UNATTRIBUTED_MARKER!r}"
    word = counted.group(1).lower()
    assert word in _SPELLED_COUNTS, f"the unattributed kinds are counted as {word!r}, which is not a spelled number"

    kinds = [sentence for sentence in sentences if _backticked(sentence)]
    assert kinds, "the paragraph counting the unattributed kinds then names none of them"
    assert _SPELLED_COUNTS[word] == len(kinds), (
        f"the README counts {word} kinds of unattributed event and then gives {len(kinds)} accounts of them, "
        f"naming {[sorted(_backticked(kind)) for kind in kinds]}"
    )


def test_the_documented_visibility_values_are_the_supported_ones():
    # The visibility table is the one whose first cell is a quoted value; the
    # field table in the same section is keyed by event field instead.
    documented = {entry.strip('"') for entry in _first_column_entries(_attribution_section()) if entry.startswith('"')}
    assert documented == set(SUBAGENT_VISIBILITY_VALUES)


def test_the_value_documented_as_the_default_is_the_default():
    """Both defaults, because a caller can reach either without passing through the other.

    The interface resolves an unset keyword through the validator, and a
    ``StreamState`` built by any other route falls back to the field's own
    default. Pinning one leaves the document true of half the code.
    """
    marked = [value.strip('"') for value, rest in _table_rows(_attribution_section()) if "(default)" in rest]
    assert marked == [validate_subagent_visibility(None)], (
        "the README marks a default the validator does not resolve to"
    )
    assert marked == [agui_state.StreamState().subagent_visibility], (
        "the README marks a default that is not the one a StreamState carries when nobody sets it"
    )


def _hidden_row() -> str:
    """The visibility table's row for ``hidden``, whole.

    Read as the entire line rather than through the first-cell reader above,
    which deliberately stops before a row's description.
    """
    rows = [line for line in _attribution_section().splitlines() if line.startswith('| `"hidden"`')]
    assert len(rows) == 1, f"the attribution section holds {len(rows)} rows describing the hidden visibility, not one"
    return rows[0]


# The two claims every account of ``hidden`` has to make, because the delegation
# call it keeps carries the member id and the task text verbatim. Both, because
# a description that keeps one and drops the other still promises a client that
# half of what the member was given stays off the wire.
_WHAT_THE_DELEGATION_STILL_CARRIES = ("name the member", "carry the task")


def _hidden_visibility_comment() -> str:
    """The state module's own account of ``hidden``, and only that account.

    Matched against the whole module, the claim below is satisfied by the words
    turning up anywhere in five hundred lines, the paragraph describing a
    different visibility included, so the description of ``hidden`` could drift
    off the constant while the check stayed green. The bullet is read from the
    line naming the value to the line before the next bullet or the end of the
    comment block.
    """
    lines = Path(agui_state.__file__).read_text(encoding="utf-8").splitlines()
    opens = [index for index, line in enumerate(lines) if re.match(r'^#\s+"hidden"', line)]
    assert len(opens) == 1, f"the state module opens {len(opens)} comment bullets for the hidden visibility, not one"
    bullet = [lines[opens[0]]]
    for line in lines[opens[0] + 1 :]:
        if not line.startswith("#") or re.match(r'^#\s+"', line):
            break
        bullet.append(line)
    return "\n".join(bullet)


def _accounts_of_hidden() -> Dict[str, str]:
    """Every place this repository describes the ``hidden`` visibility, as prose.

    Read with the line breaks and comment markers taken out, so a sentence that
    says something and happens to wrap in the middle of a phrase still counts as
    saying it. Shared by the claim checks below, so a claim added to one of them
    is checked against every account rather than against whichever was handy,
    and an account added here is held to all of them.
    """
    constructor_doc = inspect.getdoc(AGUI.__init__)
    assert constructor_doc, "the AGUI constructor carries no docstring, so nothing here can check what it claims"
    return {
        where: _unwrapped(text.replace("#", " "))
        for where, text in (
            ("the README's hidden row", _hidden_row()),
            ("the AGUI constructor docstring", constructor_doc),
            ("the hidden bullet in the state module", _hidden_visibility_comment()),
        )
    }


def test_every_account_of_the_hidden_visibility_says_the_delegation_call_names_the_member():
    """Hidden withholds the member surface, and what it keeps still names the member.

    A description that says nothing reaching the client names a member is false
    in the direction that matters: it reads as a promise to keep a member's
    identity and its task off the wire, which this interface does not make.
    """
    for where, prose in _accounts_of_hidden().items():
        missing = [claim for claim in _WHAT_THE_DELEGATION_STILL_CARRIES if claim not in prose]
        assert not missing, (
            f"{where} does not say that the delegation call hidden keeps carries arguments that {missing}"
        )


# What every account of ``hidden`` has to say about a member's failure. It
# withholds the member's identity, and the interface goes on emitting a run
# terminal whose message is that member's own failure text, so an account that
# stops at "withheld" reads as a promise the operator's client will not see why
# the run stopped.
_WHAT_HIDDEN_STILL_LETS_THROUGH = (
    "nothing on it names the",
    "the reason the run stopped still reaches the client",
)


def test_every_account_of_the_hidden_visibility_says_the_reason_the_run_stopped_still_reaches_the_client():
    """Hidden withholds a failing member's identity, not the reason the run ended.

    A member's terminal can be the only account the stream carries of how the
    run ended, and is then read as the run's own, so the failure text reaches
    the client as the run's reason with nothing beside it naming the member.
    Every description of the setting has to say both halves: one that says only
    that the failure is withheld describes an interface that stops the operator
    finding out why their run died, which this is not.
    """
    for where, prose in _accounts_of_hidden().items():
        missing = [claim for claim in _WHAT_HIDDEN_STILL_LETS_THROUGH if claim not in prose]
        assert not missing, f"{where} does not say, of a member's failure, that {missing}"


# The single-Agent guarantee is that the setting changes nothing for a run with
# no member on the wire, and a pause is where it is easiest to lose: a paused
# run's terminal carries several lists of pending calls, one call can sit on
# more than one of them, and it goes out once per listing. An account that
# states the guarantee without that case reads as a promise that every setting
# sends the well-formed stream, which none of them does.
_WHAT_THE_SINGLE_AGENT_GUARANTEE_COVERS = ("once per listing", "duplicate tool call id and all")


def test_every_account_of_the_single_agent_guarantee_covers_a_pending_call_listed_twice():
    """The guarantee is stated with the case it is hardest to keep, in all three places."""
    constructor_doc = inspect.getdoc(AGUI.__init__)
    assert constructor_doc, "the AGUI constructor carries no docstring, so nothing here can check what it claims"
    documented = {
        "the AGUI constructor docstring": constructor_doc,
        "the README's attribution section": _attribution_section(),
        "the TEST_LOG's lineage entry": _doc(_TEST_LOG),
    }

    for where, text in documented.items():
        prose = _unwrapped(text)
        missing = [claim for claim in _WHAT_THE_SINGLE_AGENT_GUARANTEE_COVERS if claim not in prose]
        assert not missing, f"{where} states the single-Agent guarantee without saying {missing}"


def test_the_documented_keyword_is_the_one_the_interface_takes():
    assert "subagent_visibility" in inspect.signature(AGUI.__init__).parameters
    assert "subagent_visibility" in _doc(_README)
    assert "subagent_visibility" in _doc(_EXAMPLE)


# --- The interrupt round trip ------------------------------------------------

# Every place the README accounts for a paused run's terminal and the answers
# that continue it. Three sections, because the claims are spread across them:
# the option's own section describes the terminal, the subsection below it the
# pause nothing can answer, and the resuming subsection the channel the answers
# arrive in. A census that read one of them calls a claim documented elsewhere
# undocumented, and a claim check that read one is satisfied by a sentence in
# whichever section was handy.
_INTERRUPT_HEADINGS = (
    "## The interrupt round trip",
    "### A pause no client could answer",
    "### Resuming",
)

_INTERRUPT_OPTION = "emit_interrupt_outcome"

needs_interrupt_outcome = pytest.mark.skipif(
    not agui_interrupts.INTERRUPT_OUTCOME_AVAILABLE,
    reason="the installed ag_ui.core has no interrupt-aware run lifecycle",
)


def _interrupt_documentation() -> str:
    readme = _doc(_README)
    return "\n\n".join(_section(readme, heading) for heading in _INTERRUPT_HEADINGS)


def _interrupt_prose() -> str:
    """The same account with its line wrapping taken out, for a claim to be read from."""
    return _unwrapped(_interrupt_documentation())


def _tables_in(section: str) -> List[str]:
    """Each table of one section, as the block of data rows it is written as.

    A section can hold more than one, and a claim about one must not be
    satisfied by a row of another: the option's two values and Agno's four pause
    kinds are both tables whose rows open with a backticked cell. They are told
    apart by the prose between them, which no data row of either can look like.
    """
    tables: List[List[str]] = []
    rows: List[str] = []
    for line in section.splitlines():
        if line.startswith("| `"):
            rows.append(line)
            continue
        if rows:
            tables.append(rows)
            rows = []
    if rows:
        tables.append(rows)
    return ["\n".join(table) for table in tables]


def _interrupt_section_tables() -> List[str]:
    tables = _tables_in(_section(_doc(_README), _INTERRUPT_HEADINGS[0]))
    assert len(tables) >= 2, (
        f"the interrupt section holds {len(tables)} tables, and this module reads two of them: "
        "the option's values, and Agno's pause kinds against the reasons they carry"
    )
    return tables


def _the_interrupt_option() -> inspect.Parameter:
    parameters = inspect.signature(AGUI.__init__).parameters
    assert _INTERRUPT_OPTION in parameters, (
        f"the interface no longer takes {_INTERRUPT_OPTION!r}, which the README documents as one of its options"
    )
    return parameters[_INTERRUPT_OPTION]


def test_the_documented_interrupt_option_is_the_one_the_interface_takes():
    _the_interrupt_option()
    assert _INTERRUPT_OPTION in _doc(_README)
    assert _INTERRUPT_OPTION in _doc(_INTERRUPT_EXAMPLE)


def test_the_documented_values_of_the_interrupt_option_are_the_ones_it_takes():
    """The option is a boolean, so its table states those two values and no others.

    Recomputed from the signature rather than left as prose: what a reader is
    told to pass has to be what the constructor takes, and a table that grew a
    third row, or wrote the setting as though it took a list of them, would
    document an option this interface does not have. The default is read from
    the same signature, so the row carrying the mark cannot drift off it either.
    """
    option = _the_interrupt_option()
    assert option.annotation is bool, (
        f"{_INTERRUPT_OPTION} is annotated {option.annotation!r}, and the README documents the two values of a boolean"
    )
    rows = _table_rows(_interrupt_section_tables()[0])
    assert {value for value, _ in rows} == {str(True), str(False)}, (
        f"the README states the values {sorted(value for value, _ in rows)} for {_INTERRUPT_OPTION}, "
        f"which takes {str(False)} and {str(True)}"
    )
    marked = [value for value, rest in rows if "(default)" in rest]
    assert marked == [str(option.default)], (
        f"the README marks {marked} as the default of {_INTERRUPT_OPTION}, which defaults to {option.default}"
    )


def _documented_pause_kinds() -> Dict[str, str]:
    """Per Agno pause kind, the ``reason`` the README says its interrupt carries.

    The kind is matched as a whole token, so ``user_input`` is not found inside
    ``requires_user_input`` and every row is credited to the kind it names
    rather than to the one its decorator's keyword happens to spell.
    """
    documented: Dict[str, str] = {}
    for row in _interrupt_section_tables()[1].splitlines():
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        assert len(cells) >= 2, f"this pause row states no reason: {row}"
        named = [
            pause_type
            for pause_type in agui_interrupts._PAUSE_TYPE_REASONS
            if re.search(rf"(?<![a-z_]){pause_type}(?![a-z_])", cells[0])
        ]
        assert len(named) == 1, f"this pause row names {named} of Agno's pause kinds, and has to name one: {row}"
        reasons = _backticked(cells[1])
        assert len(reasons) == 1, f"this pause row names {reasons} as its reason, and has to name one: {row}"
        documented[named[0]] = reasons[0]
    return documented


def test_the_documented_pause_kinds_carry_the_reasons_the_interface_sends():
    """All four kinds, each against the protocol reason the interface maps it to."""
    assert _documented_pause_kinds() == dict(agui_interrupts._PAUSE_TYPE_REASONS), (
        "the README's table of Agno's pause kinds no longer matches _PAUSE_TYPE_REASONS in "
        "agno/os/interfaces/agui/interrupts.py"
    )


class _ATypeWithNoJsonEquivalent:
    """A declared input field type this interface maps to no JSON type."""


def _waiting_on(**flags: Any) -> RunRequirement:
    return RunRequirement(
        tool_execution=ToolExecution(tool_call_id="tc-advertised", tool_name="advertised", tool_args={}, **flags)
    )


def _a_requirement_per_pause_kind() -> Dict[str, RunRequirement]:
    """One open requirement of each of Agno's pause kinds, shaped to say everything.

    The structured kinds are built to reach every constraint their schema can
    state: a field whose declared type this maps and one whose type it does not,
    a field the model already filled, a single-select question and a multi-select
    one. A schema gathered from anything less states fewer keywords than a client
    is really sent, and the document would be checked against the smaller set.

    Every kind the interface maps is here, checked against its own table, so a
    kind added to the interface is one the checks below read rather than one they
    quietly skip.
    """
    waiting = {
        "external_execution": _waiting_on(external_execution_required=True),
        "confirmation": _waiting_on(requires_confirmation=True),
        "user_input": _waiting_on(
            requires_user_input=True,
            user_input_schema=[
                UserInputField(name="topic", field_type=str, description="What to write about"),
                UserInputField(name="unmapped", field_type=_ATypeWithNoJsonEquivalent),
                UserInputField(name="filled", field_type=str, value="already there"),
            ],
        ),
        "user_feedback": _waiting_on(
            requires_user_input=True,
            user_feedback_schema=[
                UserFeedbackQuestion(
                    question="Which budget?",
                    header="Budget",
                    options=[UserFeedbackOption(label="low"), UserFeedbackOption(label="high")],
                    multi_select=False,
                ),
                UserFeedbackQuestion(
                    question="Which regions?",
                    options=[UserFeedbackOption(label="emea")],
                    multi_select=True,
                ),
            ],
        ),
    }
    assert set(waiting) == set(agui_interrupts._PAUSE_TYPE_REASONS), (
        f"this builds requirements for {sorted(waiting)} and the interface maps "
        f"{sorted(agui_interrupts._PAUSE_TYPE_REASONS)}"
    )
    misread = {kind: requirement.pause_type for kind, requirement in waiting.items() if requirement.pause_type != kind}
    assert not misread, f"these requirements report a pause kind other than the one they were built for: {misread}"
    return waiting


def _schemas_the_interface_advertises() -> Dict[str, Dict[str, Any]]:
    """The advertised answer schema of every pause kind that describes one.

    The external execution describes none, because a client hands back whatever
    its tool returned, so it is the one kind left out here rather than a kind
    this fails over.
    """
    advertised = {
        kind: requirement
        for kind, requirement in _a_requirement_per_pause_kind().items()
        if kind != "external_execution"
    }
    schemas = {kind: agui_interrupts.advertised_answer_schema(requirement) for kind, requirement in advertised.items()}
    unadvertised = sorted(kind for kind, schema in schemas.items() if not schema)
    assert not unadvertised, (
        f"these pause kinds advertise no schema for the document to be checked against: {unadvertised}"
    )
    return schemas  # type: ignore[return-value]


def _keywords_in(schema: Any) -> Set[str]:
    """Every JSON Schema keyword one advertised schema states, at any depth.

    A schema's ``properties`` are keyed by the field or question they describe,
    which are names off the pause rather than keywords, so the walk goes through
    them without counting them.
    """
    found: Set[str] = set()
    if not isinstance(schema, dict):
        return found
    for keyword, constraint in schema.items():
        found.add(keyword)
        described = (
            list(constraint.values()) if keyword == "properties" and isinstance(constraint, dict) else [constraint]
        )
        for value in described:
            found |= _keywords_in(value)
    return found


def _keywords_the_schemas_state() -> Set[str]:
    stated: Set[str] = set()
    for schema in _schemas_the_interface_advertises().values():
        stated |= _keywords_in(schema)
    assert stated, "the advertised schemas state no constraint at all, so nothing here checks the document"
    return stated


def test_every_constraint_the_advertised_schemas_state_is_documented():
    """A constraint a client is held to has to be one the document names.

    The schemas grew constraints the document did not have: a client reading it
    would send an answer the interface then refuses, and nothing said which
    keyword refused it.
    """
    documented = _documented_field_names(_interrupt_documentation())
    missing = sorted(keyword for keyword in _keywords_the_schemas_state() if keyword not in documented)
    assert not missing, (
        f"the advertised answer schemas state {missing}, which the README's account of the interrupt "
        "round trip does not name"
    )


# The sentence that splits the advertised keywords into the ones this interface
# holds an answer to and the ones it deliberately does not. Both halves are
# recomputed, because either one going stale is the same wrong in a different
# direction: a keyword claimed as checked and enforced nowhere, or one claimed
# unenforced that a client is in fact refused over.
_KEYWORDS_LEFT_UNENFORCED = "left to somebody else"


def _left_to_somebody_else() -> Tuple[str, str, str]:
    """The claim about the split, as the count and the two halves it separates."""
    stated = [sentence for sentence in _sentences(_interrupt_prose()) if _KEYWORDS_LEFT_UNENFORCED in sentence]
    assert len(stated) == 1, (
        f"{len(stated)} sentences of the interrupt account say what is {_KEYWORDS_LEFT_UNENFORCED!r}, and this "
        "check reads one"
    )
    counted = re.search(r"(\w+) are deliberately " + re.escape(_KEYWORDS_LEFT_UNENFORCED), stated[0])
    assert counted is not None, f"nothing in that sentence counts what is {_KEYWORDS_LEFT_UNENFORCED!r}"
    checked, unenforced = stated[0].split(_KEYWORDS_LEFT_UNENFORCED)
    return counted.group(1).lower(), checked, unenforced


def test_the_documented_split_of_schema_keywords_is_the_one_the_resume_side_reads():
    """Which advertised keywords are enforced, and which are somebody else's.

    Recomputed against the resume side's own tables and restricted to what the
    schemas really state, so a keyword the builders stop stating does not have
    to stay in the prose, and one they start stating cannot arrive unaccounted
    for on either side of the split.
    """
    stated = _keywords_the_schemas_state()
    somebody_elses = (set(SCHEMA_ANNOTATIONS) | set(SCHEMA_COMPLETENESS)) & stated
    enforced = (set(ADVERTISED_KEYWORDS_READ) - somebody_elses) & stated

    word, checked, unenforced = _left_to_somebody_else()
    assert set(_backticked(checked)) == enforced, (
        f"the README names {sorted(set(_backticked(checked)))} as the constraints an answer is checked against, "
        f"and the resume side checks {sorted(enforced)}"
    )
    assert set(_backticked(unenforced)) == somebody_elses, (
        f"the README leaves {sorted(set(_backticked(unenforced)))} to somebody else, and the resume side "
        f"leaves {sorted(somebody_elses)}"
    )
    assert word in _SPELLED_COUNTS, f"what is left to somebody else is counted as {word!r}, not a spelled number"
    assert _SPELLED_COUNTS[word] == len(somebody_elses), (
        f"the README counts {word} keywords left to somebody else and the resume side leaves {sorted(somebody_elses)}"
    )


def _pause_reporting(*tools: ToolExecution, requirements: Optional[List[RunRequirement]] = None) -> RunPausedEvent:
    """A pause the way a run reports one: pending calls, and a requirement per call.

    ``requirements`` is passed only where the two lists are the subject, which is
    what every check below is about: a pause whose prompt and whose open
    requirements are the same list cannot tell which of the two the terminal is
    built from.
    """
    return RunPausedEvent(
        tools=list(tools),
        requirements=[RunRequirement(tool_execution=tool) for tool in tools] if requirements is None else requirements,
    )


def _terminal_of(chunk: RunPausedEvent, **settings: Any) -> List[Any]:
    """What this interface sends for one pause, held to the shared stream definition."""
    events = on_run_completed(chunk, StreamState(**settings))
    assert_well_formed_stream(events)
    return events


def _run_terminal(events: List[Any]) -> Any:
    terminals = [event for event in events if type(event).__name__ in ("RunFinishedEvent", "RunErrorEvent")]
    assert len(terminals) == 1, f"expected one run terminal, got {[type(event).__name__ for event in events]}"
    return terminals[0]


def _interrupts_carried(events: List[Any]) -> List[Any]:
    outcome = getattr(_run_terminal(events), "outcome", None)
    return list(getattr(outcome, "interrupts", None) or [])


def _prompted_calls(events: List[Any]) -> List[str]:
    return [event.tool_call_id for event in events if type(event).__name__ == "ToolCallStartEvent"]


def _a_decision(tool_call_id: str = "tc-decide", tool_name: Optional[str] = "send_email") -> ToolExecution:
    return ToolExecution(
        tool_call_id=tool_call_id, tool_name=tool_name, tool_args={"to": "ops@example.com"}, requires_confirmation=True
    )


# What every account of the outcome has to say about what its entries are
# counted by. The two lists the terminal could be built from differ, and a
# reader told the wrong one writes a client that answers the prompt and leaves
# the run unresumable, which is the failure this whole round trip is for.
_WHAT_THE_OUTCOME_IS_COUNTED_BY = (
    "one entry per requirement the pause left open",
    "and not one per pending call",
)


def test_the_outcome_is_documented_as_counted_by_requirement():
    prose = _interrupt_prose()
    missing = [claim for claim in _WHAT_THE_OUTCOME_IS_COUNTED_BY if claim not in prose]
    assert not missing, f"the README's account of the interrupt outcome does not say {missing}"


@needs_interrupt_outcome
def test_the_outcome_carries_one_entry_per_open_requirement_and_not_per_prompted_call():
    """A pause whose prompt lists a call with nothing open behind it.

    The prompt shows both calls, because its lists are the record of what the
    client is shown, and only one of them is still waiting for an answer. Built
    from the prompt, the terminal would hand a client an id the resume channel
    refuses.
    """
    still_open = _a_decision("tc-open")
    already_decided = _a_decision("tc-decided", "archive_email")
    already_decided.confirmed = True
    events = _terminal_of(_pause_reporting(still_open, already_decided), emit_interrupt_outcome=True)

    assert _prompted_calls(events) == ["tc-open", "tc-decided"]
    assert [interrupt.tool_call_id for interrupt in _interrupts_carried(events)] == ["tc-open"]


@needs_interrupt_outcome
def test_a_pending_call_the_client_cannot_be_shown_still_carries_its_entry():
    """A call with no tool name is dropped from the prompt and still advertised.

    Its requirement is open whether or not anything can be rendered for it, and
    a resume has to answer every open requirement, so an outcome that left it
    out would advertise a set no client could complete.
    """
    events = _terminal_of(_pause_reporting(_a_decision("tc-nameless", None)), emit_interrupt_outcome=True)

    assert _prompted_calls(events) == []
    assert [interrupt.tool_call_id for interrupt in _interrupts_carried(events)] == ["tc-nameless"]


@needs_interrupt_outcome
def test_a_pause_reported_only_through_requirements_is_carried_under_the_default_visibility():
    """The pause the default prompts nothing for is still reported as an interrupt.

    The prompt reads such a call on a Team's pause only, so under the default an
    Agent's reaches the client with nothing to act on. The terminal is built
    from the run's own open requirements under every visibility, so with the
    outcome on the client is still told the run is waiting; with it off this is
    the plain finished run the visibility table describes.
    """
    reported_by_an_inner_run = RunRequirement(tool_execution=_a_decision("tc-inner"))
    reported_by_an_inner_run.member_agent_id = "inner"
    reported_by_an_inner_run.member_agent_name = "Inner"
    reported_by_an_inner_run.member_run_id = "inner-run"
    chunk = _pause_reporting(requirements=[reported_by_an_inner_run])

    carried = _terminal_of(chunk, emit_interrupt_outcome=True)
    assert _prompted_calls(carried) == []
    assert [interrupt.tool_call_id for interrupt in _interrupts_carried(carried)] == ["tc-inner"]

    quiet = _terminal_of(chunk)
    assert type(_run_terminal(quiet)).__name__ == "RunFinishedEvent"
    assert _interrupts_carried(quiet) == []


@needs_interrupt_outcome
def test_a_pause_no_client_could_answer_ends_the_run_under_the_documented_code():
    """The code the README names, recomputed from the constant and from a real pause.

    A call flagged for two pause kinds at once is the pause nothing resolves:
    whichever resolver its kind picks leaves the other kind open, and the guard
    on the resume stops the run over it. The terminal says so instead of
    advertising the rest, and it says it under a code of its own.
    """
    assert agui_interrupts.PAUSE_NOT_CONTINUABLE_CODE in _interrupt_documentation(), (
        "the README no longer names PAUSE_NOT_CONTINUABLE_CODE, which is the code a client tells this case by"
    )
    two_kinds_at_once = ToolExecution(
        tool_call_id="tc-both",
        tool_name="send_email",
        tool_args={},
        requires_confirmation=True,
        requires_user_input=True,
        user_input_schema=[UserInputField(name="body", field_type=str)],
    )
    events = _terminal_of(_pause_reporting(two_kinds_at_once), emit_interrupt_outcome=True)

    terminal = _run_terminal(events)
    assert type(terminal).__name__ == "RunErrorEvent"
    assert terminal.code == agui_interrupts.PAUSE_NOT_CONTINUABLE_CODE
    assert _prompted_calls(events) == [], "the pause was prompted as something a client could act on"


def _requests_the_readme_shows() -> List[Dict[str, Any]]:
    """Every request body the README hands a reader to paste, as parsed JSON.

    Read out of the shell blocks rather than described, because what a reader
    pastes is exactly this text: a body that is not valid JSON, or that leaves
    out a field the protocol requires, is a copy-paste the server refuses before
    it reads anything the document was teaching.
    """
    shown: List[Dict[str, Any]] = []
    for fence in re.findall(r"```bash\n(.*?)```", _doc(_README), re.DOTALL):
        if "-d '" not in fence:
            continue
        body = fence[fence.index("-d '") + len("-d '") : fence.rindex("'")]
        try:
            shown.append(json.loads(body))
        except json.JSONDecodeError as unreadable:
            raise AssertionError(f"a request body the README shows is not valid JSON: {unreadable}") from None
    assert shown, "the README shows no request body, so nothing here checks what a reader would paste"
    return shown


def test_every_request_the_readme_shows_is_one_the_protocol_accepts():
    """Each pasted body against the protocol's own model, the resume one included.

    A field left out of the resume example is the failure this guards: the
    request is refused for the missing field, and a reader is left debugging the
    part of it the document was not about.
    """
    for shown in _requests_the_readme_shows():
        try:
            RunAgentInput.model_validate(shown)
        except Exception as refused:
            raise AssertionError(
                f"the README shows a request carrying {sorted(shown)}, which the protocol refuses: {refused}"
            ) from None


def test_the_readme_shows_a_request_that_carries_the_answers():
    """One of those bodies is the resume, or the round trip is documented half way."""
    resuming = [shown for shown in _requests_the_readme_shows() if shown.get("resume")]
    assert len(resuming) == 1, (
        f"{len(resuming)} of the requests the README shows carry a resume array, and the resuming section shows one"
    )
    answered = resuming[0]["resume"]
    assert [entry.get("status") for entry in answered] == [RESUME_RESOLVED], (
        f"the resume the README shows carries the statuses {[entry.get('status') for entry in answered]}, "
        f"and an answered interrupt is {RESUME_RESOLVED!r}"
    )


def _reported_failure_path() -> List[str]:
    """Where a client says its own tool failed, built from the constants both sides read."""
    return ["metadata", agui_interrupts.RESUME_METADATA_NAMESPACE, agui_interrupts.RESUME_ERROR_KEY]


@needs_interrupt_outcome
def test_the_documented_failure_report_path_is_the_one_the_interrupt_advertises():
    """The path is documented as the code writes it, and only for the kind that has one.

    Nothing else on the wire says the convention exists, so a client-run tool
    that raised has this path or has nowhere to say so, and the document is the
    only other place it is written down.
    """
    documented = _interrupt_documentation()
    path = _reported_failure_path()
    namespace = agui_interrupts.RESUME_METADATA_NAMESPACE
    advertised_under = ".".join([*path[:-1], agui_interrupts.ERROR_REPORT_PATH_KEY])
    assert advertised_under in documented, (
        f"the README does not say the interrupt for a client-run tool advertises {advertised_under}"
    )
    assert f'"{namespace}": {{"{agui_interrupts.RESUME_ERROR_KEY}"' in documented, (
        f"the README does not show a resume entry reporting a failure under {'.'.join(path)}"
    )

    client_runs_it = ToolExecution(
        tool_call_id="tc-external",
        tool_name="change_background",
        tool_args={},
        external_execution_required=True,
    )
    ran_it_itself = _interrupts_carried(_terminal_of(_pause_reporting(_a_decision()), emit_interrupt_outcome=True))
    advertised = _interrupts_carried(_terminal_of(_pause_reporting(client_runs_it), emit_interrupt_outcome=True))

    assert advertised[0].metadata[namespace][agui_interrupts.ERROR_REPORT_PATH_KEY] == path
    assert agui_interrupts.ERROR_REPORT_PATH_KEY not in ran_it_itself[0].metadata[namespace], (
        "a pause the server runs the tool for advertises a path for a failure only the client could report"
    )

    # All four kinds, because the README names this as the one of them that
    # advertises the path: read off two, a third kind growing one would go
    # undocumented while the row still called the external execution the only one.
    carrying_it = sorted(
        kind
        for kind, requirement in _a_requirement_per_pause_kind().items()
        if agui_interrupts.ERROR_REPORT_PATH_KEY
        in _interrupts_carried(
            _terminal_of(
                _pause_reporting(requirement.tool_execution, requirements=[requirement]), emit_interrupt_outcome=True
            )
        )[0].metadata[namespace]
    )
    assert carrying_it == ["external_execution"], (
        f"the pause kinds advertising {agui_interrupts.ERROR_REPORT_PATH_KEY} are {carrying_it}, and the README "
        "names the external execution as the one of the four that does"
    )


def _a_pause_whose_every_pending_call_was_dropped() -> RunPausedEvent:
    """A pause whose one call has no tool name, so nothing of it can be rendered."""
    return _pause_reporting(_a_decision("tc-nameless", None))


def _a_pause_no_pending_call_is_read_from() -> RunPausedEvent:
    """An Agent's pause whose one call arrives through the run's requirements.

    The default reads that list on a Team's pause only, so under it nothing of
    this pause reaches the prompt, the run's own words included.
    """
    through_an_inner_run = RunRequirement(tool_execution=_a_decision("tc-inner"))
    through_an_inner_run.member_agent_id = "inner"
    through_an_inner_run.member_agent_name = "Inner"
    through_an_inner_run.member_run_id = "inner-run"
    return _pause_reporting(requirements=[through_an_inner_run])


def _a_pause_nothing_can_answer() -> RunPausedEvent:
    """Two open requirements sharing one id, which one answer could only half resolve.

    Two calls rather than one flagged for two kinds at once, so the pause the
    outcome prompts nothing for is one an ordinary prompt sends two distinct
    calls for: a call the pause lists twice is prompted once per listing, and the
    duplicate would be the subject rather than the pause being.
    """
    both = [RunRequirement(tool_execution=_a_decision("tc-a")), RunRequirement(tool_execution=_a_decision("tc-b"))]
    for requirement in both:
        requirement.id = "the-same-id"
    return _pause_reporting(*(requirement.tool_execution for requirement in both), requirements=both)


# Every pause this interface sends with no pending call for a client to act on,
# against the setting of the outcome that sends it that way. Two documents count
# these and they counted different populations: the README counts all of them,
# the constructor's docstring counts the ones the outcome-off stream has. Both
# numbers are recomputed from this list rather than from each other, which is
# how they came to disagree, and each entry is driven so a shape that stopped
# happening fails here rather than staying documented.
_NO_CALL_TO_ACT_ON = (
    ("every pending call dropped", _a_pause_whose_every_pending_call_was_dropped, False),
    ("no pending call read at all", _a_pause_no_pending_call_is_read_from, False),
    ("nothing can answer it", _a_pause_nothing_can_answer, True),
)

_COUNTS_THE_NO_CALL_PAUSES = re.compile(r"(\w+) pauses reach (?:the client|it) with no call to act on")


@needs_interrupt_outcome
def test_each_pause_documented_as_reaching_a_client_with_nothing_to_act_on_reaches_it_that_way():
    """Driven, so the enumeration is of shapes this interface still sends.

    A prompted call is what a client acts on, so a shape that prompts one is not
    one of these however it is described, and a shape that stopped being
    reachable is an enumeration nobody can check against anything.
    """
    for name, build, needs_the_outcome in _NO_CALL_TO_ACT_ON:
        events = _terminal_of(build(), emit_interrupt_outcome=needs_the_outcome)
        assert _prompted_calls(events) == [], f"the pause {name!r} prompted a call for the client to act on"


@needs_interrupt_outcome
def test_every_account_of_a_pause_with_nothing_to_act_on_counts_the_ones_the_interface_sends():
    """The README counts all of them; the constructor's docstring counts the quiet ones.

    Counted off the same list the check above drives, so neither document can be
    right only because the other says the same number.
    """
    quiet = sum(1 for _, _, needs_the_outcome in _NO_CALL_TO_ACT_ON if not needs_the_outcome)
    counted = {
        "the README": (_unwrapped(_interrupt_documentation()), len(_NO_CALL_TO_ACT_ON)),
        f"the {AGUI.__name__} constructor": (_unwrapped(inspect.getdoc(AGUI.__init__) or ""), quiet),
    }
    for where, (prose, expected) in counted.items():
        stated = _COUNTS_THE_NO_CALL_PAUSES.findall(prose)
        assert len(stated) == 1, (
            f"{where} counts the pauses with no call to act on {len(stated)} times, and this reads one count"
        )
        word = stated[0].lower()
        assert word in _SPELLED_COUNTS, f"{where} counts those pauses as {word!r}, which is not a spelled number"
        assert _SPELLED_COUNTS[word] == expected, (
            f"{where} counts {word} pauses with no call to act on, and the interface sends {expected}"
        )


# The two headings the README describes the rest of the option under. The value
# table says what the option does to a pause a client can answer, and these two
# are the things it does that no row of that table mentions, so a document that
# calls the rows the whole of it sends a reader looking for neither.
_WHAT_THE_OPTION_ALSO_DECIDES = (
    "### A pause no client could answer",
    "### A member the run paused inside",
)


@needs_interrupt_outcome
def test_the_option_decides_the_two_things_the_value_table_does_not_state():
    """Both driven off the flag, and both pointed at from where the option is introduced.

    Each is a run the client sees differently depending on this one boolean, and
    neither is a row of the table beside it, so the table is not the whole of the
    option and the section that introduces it has to say where the rest is.
    """
    stranded_on = _terminal_of(_a_pause_nothing_can_answer(), emit_interrupt_outcome=True)
    stranded_off = _terminal_of(_a_pause_nothing_can_answer())
    assert type(_run_terminal(stranded_on)).__name__ == "RunErrorEvent"
    assert type(_run_terminal(stranded_off)).__name__ == "RunFinishedEvent", (
        "the option no longer decides whether a pause nothing can answer ends the run"
    )
    assert _prompted_calls(stranded_off) == ["tc-a", "tc-b"], (
        "with the outcome off that pause is prompted like any other"
    )

    paused_inside = RunRequirement(tool_execution=_a_decision("tc-member"))
    paused_inside.member_agent_id = "member"
    paused_inside.member_agent_name = "Member"
    paused_inside.member_run_id = "member-run"
    suspended = {}
    for on in (True, False):
        state = StreamState(subagent_visibility=agui_state.SUBAGENT_VISIBILITY_ATTRIBUTED, emit_interrupt_outcome=on)
        assert_well_formed_stream(on_run_completed(_pause_reporting(requirements=[paused_inside]), state))
        suspended[on] = dict(state.suspended_lane_interrupts)
    if agui_interrupts.subagent_suspension_available():
        assert suspended[True], "the outcome no longer closes the lane of a member the run paused inside"
    assert not suspended[False], "a lane is closed as suspended with the outcome off"

    introduces = _section(_doc(_README), _INTERRUPT_HEADINGS[0])
    unmentioned = [
        heading for heading in _WHAT_THE_OPTION_ALSO_DECIDES if heading.lstrip("# ").lower() not in introduces.lower()
    ]
    assert not unmentioned, (
        f"the section introducing {_INTERRUPT_OPTION} points at neither of {unmentioned}, which it also decides"
    )


# What the README has to say about the entries of a pause that reports no
# requirement to key them by. The kind is what a client switches on to tell
# "approve this call" from "run it yourself", so a document that lets a reader
# expect one on every entry sends a client to run a tool the server runs itself,
# and one that leaves the absent report path unsaid leaves the row above it
# reading as though some other entry carries one. Both halves are stated, and
# then what such an entry does carry, so the account is what it advertises and
# not only what it does not.
_WHAT_THE_FALLBACK_ADVERTISES = (
    "no `pause_type` is written and no `error_report_path` with it",
    "the `tool_call` reason such a call is shown under",
    "the tool's name as the whole of its `metadata.agno`",
    "no `responseSchema`",
)


@needs_interrupt_outcome
def test_the_kind_an_interrupt_advertises_is_the_one_its_own_requirement_declares():
    """One call, keyed by its requirement and keyed by the fallback, side by side.

    The entries of a pause reporting no requirement at all are keyed by the
    pending calls instead, and a pending call declares no pause kind, so no kind
    is advertised for them and no report path either, that being carried by one
    kind alone. What such an entry carries is what the pause did report: a
    proposed call, keyed and reasoned as one, with the tool's name and nothing
    else beside it.
    """
    namespace = agui_interrupts.RESUME_METADATA_NAMESPACE
    decision = _a_decision("call-1")
    borne = _interrupts_carried(_terminal_of(_pause_reporting(decision), emit_interrupt_outcome=True))
    fell_back = _interrupts_carried(
        _terminal_of(_pause_reporting(decision, requirements=[]), emit_interrupt_outcome=True)
    )

    assert [interrupt.metadata[namespace]["pause_type"] for interrupt in borne] == ["confirmation"]
    keyed_by_the_call = fell_back[0]
    assert "pause_type" not in keyed_by_the_call.metadata[namespace], (
        "an entry keyed by a pending call now reads a kind off something, so the README should say which kind "
        "and where it is read from rather than that none is written"
    )
    assert agui_interrupts.ERROR_REPORT_PATH_KEY not in keyed_by_the_call.metadata[namespace], (
        "an entry with no kind behind it now carries the path only the external execution carries, so the pause "
        "table should stop saying no such entry does"
    )
    assert set(keyed_by_the_call.metadata[namespace]) == {"tool_name"}
    assert keyed_by_the_call.reason == agui_interrupts.REASON_TOOL_CALL
    assert keyed_by_the_call.id == decision.tool_call_id
    assert keyed_by_the_call.tool_call_id == decision.tool_call_id
    assert keyed_by_the_call.response_schema is None

    prose = _interrupt_prose()
    missing = [claim for claim in _WHAT_THE_FALLBACK_ADVERTISES if claim not in prose]
    assert not missing, f"the README's account of the interrupt outcome does not say {missing}"


def _a_feedback_pause(*questions: UserFeedbackQuestion) -> RunRequirement:
    return _waiting_on(requires_user_input=True, user_feedback_schema=list(questions))


def _what_a_question_advertises(schema: Optional[Dict[str, Any]], question: str) -> Dict[str, Any]:
    """The array one question is described as, whose ``items`` carry the labels."""
    assert schema, "a pause waiting on feedback advertised no schema at all"
    return schema["properties"]["selections"]["properties"][question]


def test_the_enum_a_feedback_question_advertises_is_documented_as_the_conditional_it_is():
    """A question declaring no label is advertised without one.

    The README stated the ``enum`` the way it states ``minItems``, which every
    question carries, so a client holding itself to the document would refuse an
    answer to a question that listed nothing to choose from.
    """
    labelled = agui_interrupts.advertised_answer_schema(
        _a_feedback_pause(UserFeedbackQuestion(question="Pick", options=[UserFeedbackOption(label="a")]))
    )
    label_less = agui_interrupts.advertised_answer_schema(_a_feedback_pause(UserFeedbackQuestion(question="Pick")))

    assert "enum" in _what_a_question_advertises(labelled, "Pick")["items"]
    assert "enum" not in _what_a_question_advertises(label_less, "Pick")["items"], (
        "a question declaring no label now advertises an enum, so the README can state it without a qualifier"
    )
    assert "minItems" in _what_a_question_advertises(label_less, "Pick"), (
        "the README states minItems for every question, and this one carries none"
    )

    feedback_row = [row for row in _interrupt_section_tables()[1].splitlines() if "user_feedback" in row]
    assert len(feedback_row) == 1, f"the pause table states {len(feedback_row)} rows for the feedback pause"
    stated = _unwrapped(feedback_row[0])
    assert "where it declares any" in stated, (
        "the README's feedback row states the enum without saying a question declaring no label carries none"
    )


def _an_entry_from_before_the_envelope_was_declared(**carried: Any) -> Any:
    """A resume entry shaped as the release below the one that declared ``metadata``.

    The protocol's own model is the installed one, which declares the field, so
    the older shape is built here: the same undeclared-key handling the released
    model has, and no ``metadata`` among its fields.
    """
    from pydantic import BaseModel, ConfigDict

    class _OlderResumeEntry(BaseModel):
        model_config = ConfigDict(extra="allow", populate_by_name=True)

        interrupt_id: str
        status: str
        payload: Any = None

    declared = set(_OlderResumeEntry.model_fields)
    assert agui_interrupts.ERROR_REPORT_PATH[0] not in declared, (
        "this stand-in declares the envelope, so it says nothing about a release that did not"
    )
    return _OlderResumeEntry.model_validate(carried)


def test_a_failure_is_reported_through_an_entry_that_never_declared_the_envelope():
    """The README says the envelope works below the release that declared it.

    It works because a resume entry keeps a key it does not declare and this side
    reads the report off the entry rather than off a declared field. Driven
    against an entry with no such field, so the claim rests on the reading rather
    than on the installed model happening to declare one.
    """
    from agno.os.interfaces.agui.resume import resolve_requirements_from_resume_entries

    client_ran_it = ToolExecution(
        tool_call_id="tc-extern", tool_name="change_background", tool_args={}, external_execution_required=True
    )
    waiting = RunRequirement(tool_execution=client_ran_it)
    waiting.id = "the-interrupt"
    envelope, namespace, key = agui_interrupts.ERROR_REPORT_PATH
    reported = "the browser refused"

    resolve_requirements_from_resume_entries(
        [waiting],
        [
            _an_entry_from_before_the_envelope_was_declared(
                interrupt_id=waiting.id, status=RESUME_RESOLVED, payload="", **{envelope: {namespace: {key: reported}}}
            )
        ],
    )

    assert waiting.is_resolved()
    assert client_ran_it.result == reported
    assert client_ran_it.tool_call_error is True, "the report resolved the call as a success rather than a failure"


def _statuses_the_protocol_declares() -> Tuple[str, ...]:
    """The two the resume entry's own field is typed as, read off that field."""
    from ag_ui.core import ResumeEntry

    declared = ResumeEntry.model_fields["status"].annotation
    return tuple(getattr(declared, "__args__", ()))


@needs_interrupt_outcome
def test_a_resume_status_the_protocol_does_not_declare_is_refused_before_any_stream_opens():
    """Refused by the route's own validation, so no run terminal reports it.

    The README described this as a run that stops, which is what the in-band
    guard would do. Over HTTP the body is validated against ``RunAgentInput``
    first, so a client waiting to read the reason off the stream is waiting for a
    stream that never opens.
    """
    from fastapi.testclient import TestClient

    from agno.agent import Agent
    from agno.db.in_memory import InMemoryDb
    from agno.os import AgentOS

    from .agui_stream_invariants import ScriptedModel

    declared = _statuses_the_protocol_declares()
    assert RESUME_RESOLVED in declared and len(declared) == 2, (
        f"the protocol declares the resume statuses {declared}, and the README states two"
    )
    undeclared = "skipped"
    assert undeclared not in declared

    agent = Agent(id="a", name="A", db=InMemoryDb(), model=ScriptedModel("m", [("content", "never asked")]))
    served = AgentOS(id="os", agents=[agent], interfaces=[AGUI(agent=agent)], telemetry=False)
    refused = TestClient(served.get_app()).post(
        "/agui",
        json={
            "threadId": "t",
            "runId": "r",
            "state": {},
            "messages": [],
            "tools": [],
            "context": [],
            "forwardedProps": {},
            "resume": [{"interruptId": "whatever", "status": undeclared, "payload": {}}],
        },
    )

    assert refused.status_code == 422, f"a third resume status was answered {refused.status_code}: {refused.text}"
    assert "data:" not in refused.text, f"the refusal carried a stream after all: {refused.text}"
    assert str(refused.status_code) in _interrupt_prose(), (
        f"the README does not say an entry carrying a third status is refused as an HTTP {refused.status_code}"
    )


# How every account of the outcome qualifies the tool call id it names. An
# interrupt is keyed by its requirement and carries the call only where the call
# had an id of its own, so an account that promises one unconditionally has a
# client indexing the outcome by a field that is sometimes absent.
_THE_TOOL_CALL_ID_IS_CONDITIONAL = "where that call had an id of its own"


def _accounts_of_what_an_interrupt_names() -> Dict[str, str]:
    """Every document that says what one interrupt of the outcome names.

    Three of them say it, and the one that promised the call unconditionally was
    the example a reader runs, so this is pinned over all three rather than over
    the README alone.
    """
    return {
        "the README": _interrupt_prose(),
        _INTERRUPT_EXAMPLE.name: _unwrapped(_doc(_INTERRUPT_EXAMPLE)),
        f"the {AGUI.__name__} constructor": _unwrapped(inspect.getdoc(AGUI.__init__) or ""),
    }


@needs_interrupt_outcome
def test_every_account_of_the_outcome_says_the_tool_call_id_is_the_conditional_it_is():
    """Driven from a requirement whose pending call carries no id of its own."""
    nameless = RunRequirement(
        tool_execution=ToolExecution(
            tool_call_id=None, tool_name="send_email", tool_args={}, requires_confirmation=True
        )
    )
    carried = _interrupts_carried(_terminal_of(_pause_reporting(requirements=[nameless]), emit_interrupt_outcome=True))

    assert len(carried) == 1, "a requirement whose call carries no id is still open and still advertised"
    assert carried[0].tool_call_id is None, (
        "an interrupt now carries a tool call id for a call that had none, so the documents can promise one"
    )
    silent = sorted(
        where
        for where, prose in _accounts_of_what_an_interrupt_names().items()
        if _THE_TOOL_CALL_ID_IS_CONDITIONAL not in prose
    )
    assert not silent, f"these accounts promise the tool call id unconditionally: {silent}"


# What the example's resume recipe has to say beyond which fields to send. One
# array answers every interrupt the outcome carried, and a reader following a
# recipe that answers the one id it happened to read is refused by the guard
# below with the run still paused.
_THE_RESUME_IS_ALL_OR_NOTHING = "answering one of them is refused as a partial resume"


class _OneAnswer:
    """A resume entry as the array carries them, for a pause that needs two."""

    status = RESUME_RESOLVED
    payload = {"accepted": True}

    def __init__(self, interrupt_id: Optional[str]) -> None:
        self.interrupt_id = interrupt_id


def test_the_example_recipe_states_the_rule_the_resume_guard_holds_a_client_to():
    """The refusal is driven, so the rule is one the interface really enforces."""
    from agno.os.interfaces.agui.resume import resolve_requirements_from_resume_entries

    answered = RunRequirement(tool_execution=_a_decision("tc-a"))
    left_open = RunRequirement(tool_execution=_a_decision("tc-b", "archive_email"))
    with pytest.raises(ValueError, match="Partial resume"):
        resolve_requirements_from_resume_entries(
            [answered, left_open], [_OneAnswer(agui_interrupts.interrupt_id_of(answered))]
        )

    assert _THE_RESUME_IS_ALL_OR_NOTHING in _unwrapped(_doc(_INTERRUPT_EXAMPLE)), (
        f"{_INTERRUPT_EXAMPLE.name} hands a reader a resume recipe without saying {_THE_RESUME_IS_ALL_OR_NOTHING!r}"
    )


_FIELDS_A_RESUME_MUST_CARRY = re.compile(
    r"Those are (.+?) on every release this file runs on, and (\w+) as well on the releases that still required it"
)


def _field_names_in(listed: str) -> Set[str]:
    return {name.strip() for name in re.split(r",| and ", listed) if name.strip()}


def test_the_fields_the_example_says_a_resume_must_carry_are_the_ones_the_protocol_requires():
    """The list is stated over a range of releases, and the range is what it got wrong.

    ``state`` is required at the floor the example names and optional from 0.1.21
    on, so a list asserting all seven as required is false on the newer half,
    which includes the release the README's own upgrade command installs. What is
    checked holds on either half: every field the example calls always required
    is required on the installed release, and every field the installed release
    requires is one the example either calls always required or names as the one
    that moved.
    """
    stated = _FIELDS_A_RESUME_MUST_CARRY.findall(_unwrapped(_doc(_INTERRUPT_EXAMPLE)))
    assert len(stated) == 1, (
        f"{_INTERRUPT_EXAMPLE.name} states the fields a resume must carry {len(stated)} times, and this reads one"
    )
    always, moved = _field_names_in(stated[0][0]), {stated[0][1]}

    required = {field.alias or name for name, field in RunAgentInput.model_fields.items() if field.is_required()}
    assert always <= required, (
        f"{_INTERRUPT_EXAMPLE.name} calls {sorted(always - required)} required on every release, and the installed "
        "protocol does not require them"
    )
    assert required <= always | moved, (
        f"the installed protocol requires {sorted(required - always - moved)}, which {_INTERRUPT_EXAMPLE.name} "
        "neither calls always required nor names as having become optional"
    )


def _documented_field_names(text: str) -> Set[str]:
    """Every field name a piece of the README names, however it writes the field.

    Backticked tokens are read paragraph by paragraph with the line wrapping
    inside each one taken out, so a token that wraps mid-phrase is still one
    token, while a fenced block stays a paragraph of its own rather than being
    run into the prose around it and pairing every backtick after it wrongly. A
    token written as a field and the shape it carries, ``outcome: {...}``,
    counts under the field it opens with.
    """
    documented: Set[str] = set()
    for paragraph in _paragraphs(text):
        for token in _backticked(paragraph):
            documented.add(token)
            carries_a_shape = re.match(r"([A-Za-z_][A-Za-z0-9_]*):", token)
            if carries_a_shape is not None:
                documented.add(carries_a_shape.group(1))
    return documented


def _fields_every_subagent_event_carries() -> Set[str]:
    """The own fields all three lineage events share.

    One account documents such a field for all three, because it means the same
    thing on each. A field only one of them carries does not: it has to be
    documented under the name of the event that carries it.
    """
    carried = [_own_field_aliases(event_class) for event_class in _subagent_event_classes().values()]
    return set.intersection(*carried) if carried else set()


@needs_lineage_events
def test_every_field_of_every_subagent_event_is_documented():
    """Every field of all three lineage events, not the announcement's alone.

    A field added to a terminal is as undocumented as one added to the
    announcement, and read for ``SUBAGENT_STARTED`` by itself this census had
    nothing to say about either terminal.

    A field is documented by the qualified ``EVENT.field``, and by the bare name
    only where every one of the three carries it. Any bare token counted before,
    which let one event's field be documented by an account of another's:
    ``outcome`` written for the terminal that has one also passed for the two
    that do not, so a field added to either would have read as documented.
    """
    # Matched against the backticked tokens rather than the raw text: a field
    # named "name" or "description" occurs in ordinary prose, so a substring
    # search finds those two whether or not anything documents them.
    documented = _documented_field_names(_member_surface_documentation())
    shared = _fields_every_subagent_event_carries()
    missing = {
        event_name: sorted(
            alias
            for alias in _own_field_aliases(event_class)
            if f"{event_name}.{alias}" not in documented and not (alias in shared and alias in documented)
        )
        for event_name, event_class in _subagent_event_classes().items()
    }
    undocumented = {event_name: fields for event_name, fields in missing.items() if fields}
    assert not undocumented, (
        "the README's account of the member surface does not describe "
        f"{undocumented}, either under the event that carries it or, for a field all three carry, by name"
    )


# A field documented under the event that carries it. The field name is read
# whole, underscores included: stopping at the first non-letter let a documented
# field validate as its own prefix, so SUBAGENT_ERROR.message_id passed on the
# strength of the message field.
#
# The single space is the one unwrapping a document leaves behind when the name
# wrapped after the dot, and it is allowed only before a name written the way
# the protocol writes its fields. Allowed before anything, the full stop ending
# a sentence with an event name in it would read as a field whose name is the
# next sentence's first word.
_A_DOCUMENTED_FIELD = re.compile(r"(SUBAGENT_[A-Z]+)\.(?: (?=[a-z_]))?([A-Za-z_][A-Za-z0-9_]*)")


def _documented_qualified_fields(text: str) -> List[Tuple[str, str]]:
    """Every ``EVENT.field`` a piece of the README names, wrapped or not."""
    return [named for paragraph in _paragraphs(text) for named in _A_DOCUMENTED_FIELD.findall(paragraph)]


def test_a_documented_field_is_read_whether_it_wraps_after_the_dot_or_not():
    """The same field, written both ways, is the same claim.

    Dropped when it wraps, a field the event does not carry is documented by
    reflowing the paragraph that names it.
    """
    assert _documented_qualified_fields("names SUBAGENT_STARTED.\nparentToolCallId here") == [
        ("SUBAGENT_STARTED", "parentToolCallId")
    ]
    assert _documented_qualified_fields("names SUBAGENT_STARTED.parentToolCallId here") == [
        ("SUBAGENT_STARTED", "parentToolCallId")
    ]


def test_a_sentence_that_ends_on_an_event_name_documents_no_field():
    """The other direction: a read loose enough to never miss starts reading prose.

    A sentence ending on an event name and the next one starting below it is the
    shape a wrapped field has once the wrapping is out, so the two are told
    apart by how the name that follows is written.
    """
    assert _documented_qualified_fields("carried on SUBAGENT_FINISHED.\nThe client reads it.") == []


@needs_lineage_events
def test_every_documented_subagent_field_exists_on_its_event():
    classes = _subagent_event_classes()
    named = _documented_qualified_fields(_member_surface_documentation())
    assert named, "the README's account of the member surface names no subagent event fields at all"
    for event_name, field in named:
        assert event_name in classes, f"the README names an unknown event {event_name}"
        assert field in _own_field_aliases(classes[event_name]), (
            f"the README documents {event_name}.{field}, which the protocol event does not carry"
        )


def _root_examples() -> Set[str]:
    """The standalone example files in the folder's own root.

    The nested OpenUI server is a server too, and the log counts it, but it is
    the backend half of one example rather than a standalone one, so it is not
    in here.
    """
    return {path.name for path in _COOKBOOK.glob("*.py")}


def test_the_files_table_lists_every_example_in_the_folder():
    if not _COOKBOOK.exists():
        pytest.skip("cookbook not present in this checkout")
    listed = set(_first_column_entries(_section(_doc(_README), "## Files")))
    present = _root_examples()
    present |= {
        f"{path.name}/"
        for path in _COOKBOOK.iterdir()
        if path.is_dir() and not path.name.startswith((".", "_")) and any(path.rglob("*.py"))
    }
    assert listed == present


def _floors_stated_in(text: str) -> Set[Tuple[int, ...]]:
    """Every protocol floor one document states, as comparable version tuples."""
    return {tuple(int(piece) for piece in version.split(".")) for version in re.findall(_FLOOR, text)}


def _as_written(versions: Set[Tuple[int, ...]]) -> List[str]:
    return [".".join(str(piece) for piece in version) for version in sorted(versions)]


# The package's own ``agui`` extra, as the requirements it declares. Read off
# the assignment rather than off the whole file: a floor gathered from the file
# is stated by whichever extra happens to state one, so the check reported it as
# the release installing this extra leaves a reader on while the extra itself
# required no protocol release at all.
_AGUI_EXTRA = re.compile(r"^agui\s*=\s*\[(.*?)\]", re.MULTILINE | re.DOTALL)


def _agui_extra_in(pyproject: str) -> str:
    declared = _AGUI_EXTRA.findall(pyproject)
    assert len(declared) == 1, (
        f"the package declares {len(declared)} agui extras, and this check reads the one a reader installs"
    )
    return declared[0]


def _agui_extra_requirements() -> str:
    return _agui_extra_in(_PACKAGE_PYPROJECT.read_text(encoding="utf-8"))


def test_the_packaged_extra_is_read_off_the_extra_a_reader_installs():
    """What one extra requires is not what the package requires.

    Read off the whole file, the floor another extra states was reported as the
    release installing this one leaves a reader on, so the extra could stop
    requiring the protocol at all with nothing here saying so.
    """
    pyproject = '[project.optional-dependencies]\nagui = ["ag-ui-protocol>=0.1.15"]\na2a = ["ag-ui-protocol>=0.1.21"]\n'
    assert _floors_stated_in(_agui_extra_in(pyproject)) == {(0, 1, 15)}
    assert _floors_stated_in(_agui_extra_in('agui = ["jsonpatch>=1.33"]\na2a = ["ag-ui-protocol>=0.1.21"]\n')) == set()


def test_the_protocol_floor_is_stated_the_same_way_everywhere():
    """Every optional part of the protocol names one floor, in both places it is named.

    There is more than one such part, and they arrived in different releases, so
    the floors are per example rather than one number for the folder. What has to
    hold is that each example states exactly one, and that the README states the
    same set the examples do: a reader who follows either document has to end up
    on a release that serves what they are being shown, and a document going
    silent is how that stops being true.
    """
    assert _FLOOR_EXAMPLES, "no example is read for a protocol floor, so this check compares two empty sets"
    # Per example, because one set of versions gathered from all of them is
    # satisfied by a single document stating a floor while the rest go silent.
    stated = {path.name: _floors_stated_in(_doc(path)) for path in _FLOOR_EXAMPLES}
    silent = sorted(name for name, versions in stated.items() if not versions)
    assert not silent, f"these examples no longer state the protocol floor they need: {silent}"
    ambiguous = {name: _as_written(versions) for name, versions in stated.items() if len(versions) != 1}
    assert not ambiguous, f"these examples state more than one protocol floor: {ambiguous}"

    # The lineage floor is pinned to the release the invariants recompute
    # against the announcement fields they read, so the documents cannot agree
    # with each other on a release that serves none of what they show. The
    # interrupt round trip has no such constant: what it needs is feature
    # detected on the installed release and nothing recomputes the number, so
    # its floor stays document to document until something does.
    assert stated[_EXAMPLE.name] == {LINEAGE_EVENTS_PROTOCOL_FLOOR}, (
        f"{_EXAMPLE.name} names the protocol floor {_as_written(stated[_EXAMPLE.name])} for the subagent events, "
        f"which arrived in {_as_written({LINEAGE_EVENTS_PROTOCOL_FLOOR})[0]}"
    )

    documented = _floors_stated_in(_doc(_README))
    needed = set().union(*stated.values())
    assert documented == needed, (
        f"the README documents the protocol floors {_as_written(documented)}, and the examples need "
        f"{_as_written(needed)}: {_as_written(needed - documented)} is named by no README and "
        f"{_as_written(documented - needed)} by no example"
    )


def test_the_packaged_extra_still_permits_a_release_below_the_documented_floor():
    """The README tells the reader to upgrade by hand, which the extra must justify.

    Against the lowest floor the README documents, since that is the one the
    extra has to sit below for the instruction to be worth giving: an extra
    above it resolves a release that serves none of what the folder shows.
    Compared with whichever floor the document happened to state first, the
    check moved with the prose, and the README states several.
    """
    # The packaged extra is read straight off the package, which the root check
    # at the top of this module guarantees is there: it is not a cookbook file
    # and a checkout without the cookbook still has it.
    documented = _floors_stated_in(_doc(_README))
    assert documented, "the README states no protocol floor, so nothing here says what the extra sits below"
    packaged = _floors_stated_in(_agui_extra_requirements())
    assert packaged, (
        "the agui extra requires no ag-ui-protocol release at all, so the README's instruction to upgrade it "
        "by hand rests on nothing"
    )
    assert len(packaged) == 1, (
        f"the agui extra requires the protocol floors {_as_written(packaged)}, and this check needs the one "
        "release a reader who installs the extra ends up above"
    )

    assert next(iter(packaged)) < min(documented), (
        "the agui extra now requires the lineage events, so the README should stop "
        "saying it allows older releases and stop teaching a manual upgrade"
    )


def _bullet_naming(log: str, phrase: str) -> str:
    """The one list item that makes a claim, so names are read from that claim alone.

    A bullet ends where its wrapped lines stop being indented, which is the next
    bullet, a blank line, a heading or the end of the document. Cut at the next
    bullet alone, the last bullet of a list swallowed the rest of the log, and
    names from anywhere below it read as names this claim had made.

    The claim is found across the document's own line wrapping, since the bullet
    it opens is what has to be read line by line, not the phrase naming it: a
    claim that wrapped between two of its words was reported as a claim the log
    no longer makes.

    The bullet is then read from its own first line, not from where the phrase
    starts inside it. Read from the phrase, everything the claim wrote before it
    went unread, so a name written ahead of the phrase was excused from both the
    check that the folder holds it and the arithmetic that counts it.
    """
    opens = re.search(r"\s+".join(re.escape(word) for word in phrase.split()), log)
    assert opens is not None, f"the Validation section no longer says {phrase!r}"
    lines = log.splitlines()
    # A wrapped line of a bullet is an indented one, so the bullet opens at the
    # first line at or above the phrase that is not indented.
    first = log.count("\n", 0, opens.start())
    while first > 0 and lines[first].strip() and lines[first].startswith((" ", "\t")):
        first -= 1
    bullet = [lines[first]]
    for line in lines[first + 1 :]:
        if not line.strip() or not line.startswith((" ", "\t")):
            break
        bullet.append(line)
    return "\n".join(bullet)


def test_a_bullet_is_read_to_its_end_and_no_further():
    """The last bullet of a list ends with the list, not with the document.

    Read to the next bullet alone, the last one swallowed everything below it,
    so a name from a later section counted as a name its own claim had made.
    """
    log = "- first, which\n  wraps\n- the claim names `kept.py`\n  and `also_kept.py`\n\n## Later\n\n`elsewhere.py`\n"
    assert re.findall(r"`([^`]+\.py)`", _bullet_naming(log, "the claim names")) == ["kept.py", "also_kept.py"]


def test_a_bullet_is_read_from_its_start_whatever_line_the_claim_opens_on():
    """A name the claim writes before the phrase is a name the claim made.

    Both places it can sit: ahead of the phrase on the bullet's own first line,
    and on a wrapped line above the one the phrase starts on.
    """
    ahead = "- first\n- Except `excused.py`, the claim names `kept.py`\n- last\n"
    assert re.findall(r"`([^`]+\.py)`", _bullet_naming(ahead, "the claim names")) == ["excused.py", "kept.py"]
    above = "- first\n- Except `excused.py`,\n  the claim names `kept.py`\n- last\n"
    assert re.findall(r"`([^`]+\.py)`", _bullet_naming(above, "the claim names")) == ["excused.py", "kept.py"]


def _counted_once(text: str, pattern: str, what: str) -> Tuple[str, ...]:
    """The one set of numbers a document states for something it counts.

    Every statement is read rather than the first. The log restates its counts
    in the entries that re-measured them, and a check reading whichever comes
    first says nothing about the rest: a restatement that drifted from the one
    at the top passed as long as the top one still held.
    """
    stated = set(re.findall(pattern, text))
    assert stated, f"the Validation section no longer counts {what}"
    assert len(stated) == 1, f"the Validation section states {sorted(stated)} for {what}, so it counts it two ways"
    counted = stated.pop()
    return counted if isinstance(counted, tuple) else (counted,)


# Every count in the TEST_LOG that this module recomputes from the folder, as the
# pattern each is read by. The log states how many of its counts are facts about
# the folder rather than records of one run, and that number is read off this
# list: written down twice, the statement outlived the checks it described, which
# is what this whole folder's documented-claim drift keeps being.
_COUNTS_RECOMPUTED_FROM_THE_FOLDER: Dict[str, str] = {
    "how its count is made up": r"the (\d+) in its root plus ((?:`[^`]+\.py`(?:,| and)? ?)+)",
    "the server files it booted": r"All (\d+) server files",
    "the scanned Python files": r"checked exactly (\d+) Python files",
    "the completed POST flows": r"(\d+) of the (\d+) files completed",
    "the status routes it asserted": r"(\d+) status routes in all",
}


def _how_many_counts_the_log_says_are_recomputed() -> str:
    stated = re.findall(r"(\w+) of the counts kept below are facts about this folder", _unwrapped(_doc(_TEST_LOG)))
    assert len(stated) == 1, (
        f"the TEST_LOG says how many of its counts are facts about this folder {len(stated)} times, "
        "and this reads one statement"
    )
    return stated[0].lower()


def _a_recomputed_count(what: str) -> Tuple[str, str]:
    """One recomputed count's pattern and the name a refusal calls it by."""
    return _COUNTS_RECOMPUTED_FROM_THE_FOLDER[what], what


def test_the_log_counts_the_counts_this_suite_recomputes():
    """The claim about the claims, which is the one nothing recomputed.

    The log used to say the only counts it kept were the ones recomputed here,
    while keeping a dozen it does not: the events one stream carried, the files
    one sweep walked, the violations it found. What it may say is how many are
    recomputed, and that number comes off the list the checks below run on.
    """
    word = _how_many_counts_the_log_says_are_recomputed()
    assert word in _SPELLED_COUNTS, f"the TEST_LOG counts those as {word!r}, which is not a spelled number"
    assert _SPELLED_COUNTS[word] == len(_COUNTS_RECOMPUTED_FROM_THE_FOLDER), (
        f"the TEST_LOG says {word} of its counts are recomputed from the folder, and this suite recomputes "
        f"{len(_COUNTS_RECOMPUTED_FROM_THE_FOLDER)}: {sorted(_COUNTS_RECOMPUTED_FROM_THE_FOLDER)}"
    )


def test_the_validation_counts_match_the_folder():
    log = _doc(_TEST_LOG)
    root = _root_examples()
    # Every count is read off the same normalised text. Read off the raw
    # document instead, a claim that happens to wrap between two of its own
    # words stops being found at all, so reflowing a correct paragraph failed
    # the check that it counts something.
    prose = _unwrapped(log)

    # The document states its own breakdown, and the files beyond the root are
    # read from that sentence rather than from a recursive walk: a walk counts
    # anything a nested frontend's installed dependencies bring with them, and
    # would disagree with the non-recursive count the files table is checked
    # against.
    in_root, listing = _counted_once(prose, *_a_recomputed_count("how its count is made up"))
    assert int(in_root) == len(root), (
        f"the Validation section counts {in_root} files in the folder root, which holds {len(root)}"
    )
    nested = set(re.findall(r"`([^`]+\.py)`", listing))
    assert nested, "the Validation section names no file beyond the root, so its total cannot be checked"
    absent = sorted(name for name in nested if not (_COOKBOOK / name).exists())
    assert not absent, f"the Validation section counts files that are gone: {absent}"
    # De-duplicated on both sides of the arithmetic below, since the same file
    # named twice is one file wherever it is named.
    servers = len(root | nested)

    booted = _counted_once(prose, *_a_recomputed_count("the server files it booted"))
    assert int(booted[0]) == servers

    scanned = _counted_once(prose, *_a_recomputed_count("the scanned Python files"))
    assert int(scanned[0]) == servers

    completed, of_files = _counted_once(prose, *_a_recomputed_count("the completed POST flows"))
    assert int(of_files) == servers
    # The shortfall is derived from the files the same claim names as covered
    # elsewhere, rather than from a hard-coded allowance of one.
    # The same pattern the nested files are read with: a name written with a
    # directory in front of it is one of the files this claim can excuse, and a
    # pattern that could not match one reported it as excusing something the
    # folder does not hold.
    uncovered = set(re.findall(r"`([^`]+\.py)`", _bullet_naming(log, "of the {} files completed".format(servers))))
    assert uncovered, "the Validation section no longer names the files whose POST flow it did not run"
    missing = sorted(name for name in uncovered if name not in root and name not in nested)
    assert not missing, f"the Validation section excuses files the folder does not hold: {missing}"
    assert int(completed) == servers - len(uncovered)


def _interfaces_mounted_by(source: str) -> int:
    """How many AG-UI interfaces one example mounts, read off its own source.

    Counted by construction rather than from the prefixes the log lists, because
    the routes an example exposes are one per interface it builds, and an
    example that grows a second mount grows a second status route with it.
    """
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and (_dotted(node.func) or "").split(".")[-1] == AGUI.__name__
    )


def test_the_status_routes_the_log_counts_are_the_ones_the_examples_mount():
    """The one measured count the log still writes down, recomputed from the folder.

    The boot sweep asserts a status route per mounted interface, so the number
    it reports is a fact about these files rather than about the run that day,
    and an example that mounts one more moves it.

    The log is read first, so a checkout shipping no cookbook skips here. Read
    after the folder was walked, this failed for holding no example that mounts
    an interface, which is a report that the folder is wrong rather than absent.
    """
    log = _unwrapped(_doc(_TEST_LOG))
    mounted = sum(_interfaces_mounted_by((_COOKBOOK / name).read_text(encoding="utf-8")) for name in _root_examples())
    assert mounted, "no example in the folder root mounts an AG-UI interface, so the log's count checks nothing"
    counted = _counted_once(log, *_a_recomputed_count("the status routes it asserted"))
    assert int(counted[0]) == mounted, (
        f"the log counts {counted[0]} status routes and this folder's root examples mount {mounted} interfaces"
    )


def test_the_test_log_cites_suites_that_exist():
    cited = re.findall(r"`(libs/agno/tests/[^`\n]+\.py)`", _doc(_TEST_LOG))
    assert cited, "the test log cites no unit suite for the payloads it does not run itself"
    missing = sorted(path for path in cited if not (_REPO_ROOT / path).exists())
    assert not missing, f"the test log cites suites that are gone: {missing}"
