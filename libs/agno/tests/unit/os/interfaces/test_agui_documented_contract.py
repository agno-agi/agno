"""The AG-UI cookbook's documented contract, read out of the document and checked.

The 16_agui README and TEST_LOG restate facts that live in the interface: which
events carry a member's ``subagentRunId``, which visibility values exist and
which one is the default, what an announcement's parent links are called, which
files the folder holds. A restatement that nothing recomputes drifts silently,
so every enumerable claim is parsed out of the document here and compared with
the implementation's own constants rather than with a second copy of them.
Adding an event type to the interface, or a visibility value, or a field to an
announcement, without saying so in the README fails one of these tests.

Genuine prose is left alone. Only claims that enumerate something the code
already enumerates are pinned.
"""

import ast
import importlib
import inspect
import re
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Set, Tuple

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import BaseEvent

from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.agui import handlers as agui_handlers
from agno.os.interfaces.agui import state as agui_state
from agno.os.interfaces.agui.handlers import validate_subagent_visibility
from agno.os.interfaces.agui.state import SUBAGENT_VISIBILITY_VALUES

from .agui_stream_invariants import needs_lineage_events, require_lineage_events

_REPO_ROOT = Path(__file__).resolve().parents[6]
_COOKBOOK = _REPO_ROOT / "cookbook" / "05_agent_os" / "16_agui"
_README = _COOKBOOK / "README.md"
_TEST_LOG = _COOKBOOK / "TEST_LOG.md"
_EXAMPLE = _COOKBOOK / "team_subagent_lineage.py"
_PACKAGE_PYPROJECT = _REPO_ROOT / "libs" / "agno" / "pyproject.toml"

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
    """One `##` section of a markdown document, heading excluded.

    Anchored at the start of a line, so a heading named in a sentence somewhere
    above cannot be mistaken for the section itself, and reported rather than
    raised bare, so a renamed heading says which one went missing.
    """
    found = re.search(rf"^{re.escape(heading)}$", text, re.MULTILINE)
    assert found is not None, f"the document no longer has a {heading!r} section, so nothing here can read it"
    rest = text[found.end() :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _attribution_section() -> str:
    return _section(_doc(_README), "## Team member attribution")


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
        elif isinstance(node, ast.ImportFrom) and node.module == _AG_UI:
            for alias in node.names:
                if alias.name == _CORE:
                    aliases[alias.asname or _CORE] = _AG_UI_CORE
    return aliases


def _constructed_event_class(func: ast.expr, classes: Dict[str, type], aliases: Dict[str, str]) -> Optional[type]:
    """The AG-UI event class a call constructs, or None when it constructs none."""
    if isinstance(func, ast.Name):
        return classes.get(func.id)
    if isinstance(func, ast.Attribute):
        prefix = _dotted(func.value)
        module = aliases.get(prefix) if prefix is not None else None
        if module is not None:
            return _event_class_named(func.attr, module)
    return None


def _event_type_default(event_class: type) -> str:
    """The event type a protocol class declares, reported rather than raised for.

    A class with no concrete default has nothing to name it by. Read straight
    through, that arrives as an attribute error from inside the scan, which
    takes down this module and the hostile-content suite whose census rests on
    it instead of saying which class is unreadable.
    """
    declared = event_class.model_fields["type"].default  # type: ignore[attr-defined]
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
        _scan_node(node.body, f"{scope}.<lambda>", classes, aliases, built)
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
        "scanned.outer.<lambda>",
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
    """Only ``ag_ui.core`` itself is the protocol.

    Reading any attribute call by its last segment would credit a scope with an
    event it never built, which is the other way this census can go wrong.
    """
    source = "from ag_ui.core import RawEvent\n\ndef builds(registry):\n    registry.RawEvent()\n"
    assert event_constructions_in("scanned", source) == {}


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
    """The paragraph that accounts for the events carrying no ``subagentRunId``."""
    section = _attribution_section()
    assert _UNATTRIBUTED_MARKER in section, f"the attribution section no longer contains {_UNATTRIBUTED_MARKER!r}"
    return section[section.index(_UNATTRIBUTED_MARKER) :].split("\n\n")[0]


def _documented_unattributed_events() -> Set[str]:
    """The event families the README says carry no ``subagentRunId``."""
    paragraph = _unattributed_paragraph()
    documented: Set[str] = set()
    for token in _backticked(paragraph):
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
    """The count one word ahead of the marker, against the families the paragraph names.

    Recomputed from the same paragraph, so the sentence cannot keep saying
    "three" while naming a fourth family underneath it. A family is an event
    name prefix: the two state events are one kind, which is how the paragraph
    itself accounts for them.
    """
    paragraph = _unattributed_paragraph()
    section = _attribution_section()
    counted = re.search(r"(\w+) " + re.escape(_UNATTRIBUTED_MARKER), section)
    assert counted is not None, f"nothing in the attribution section counts the {_UNATTRIBUTED_MARKER!r}"
    word = counted.group(1).lower()
    assert word in _SPELLED_COUNTS, f"the unattributed kinds are counted as {word!r}, which is not a spelled number"

    families = {token.split("_")[0] for token in _backticked(paragraph)}
    assert families, "the paragraph counting the unattributed kinds then names none of them"
    assert _SPELLED_COUNTS[word] == len(families), (
        f"the README counts {word} kinds of unattributed event and then names {sorted(families)}"
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
        where: " ".join(text.replace("#", " ").split())
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
        prose = " ".join(text.split())
        missing = [claim for claim in _WHAT_THE_SINGLE_AGENT_GUARANTEE_COVERS if claim not in prose]
        assert not missing, f"{where} states the single-Agent guarantee without saying {missing}"


def test_the_documented_keyword_is_the_one_the_interface_takes():
    assert "subagent_visibility" in inspect.signature(AGUI.__init__).parameters
    assert "subagent_visibility" in _doc(_README)
    assert "subagent_visibility" in _doc(_EXAMPLE)


@needs_lineage_events
def test_every_field_of_an_announcement_is_documented():
    # Matched against the section's backticked tokens rather than its raw text:
    # a field named "name" or "description" occurs in ordinary prose, so a
    # substring search finds those two whether or not anything documents them.
    documented = set(_backticked(_attribution_section()))
    started = _subagent_event_classes()["SUBAGENT_STARTED"]
    missing = sorted(
        alias
        for alias in _own_field_aliases(started)
        if alias not in documented and f"SUBAGENT_STARTED.{alias}" not in documented
    )
    assert not missing, f"the attribution section does not describe SUBAGENT_STARTED fields {missing}"


@needs_lineage_events
def test_every_documented_subagent_field_exists_on_its_event():
    classes = _subagent_event_classes()
    # The field name is read whole, underscores included. Stopping at the first
    # non-letter let a documented field validate as its own prefix, so
    # SUBAGENT_ERROR.message_id passed on the strength of the message field.
    named = re.findall(r"(SUBAGENT_[A-Z]+)\.([A-Za-z_][A-Za-z0-9_]*)", _attribution_section())
    assert named, "the attribution section names no subagent event fields at all"
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


def test_the_protocol_floor_is_stated_the_same_way_everywhere():
    pattern = r"ag-ui-protocol[`'\s>=]{1,4}(\d+\.\d+\.\d+)"
    # Per document, because one set of versions gathered from all of them is
    # satisfied by a single document stating the floor while the rest go silent.
    stated = {
        name: set(re.findall(pattern, text)) for name, text in (("README", _doc(_README)), ("example", _doc(_EXAMPLE)))
    }
    silent = sorted(name for name, versions in stated.items() if not versions)
    assert not silent, f"these documents no longer state the lineage protocol floor: {silent}"
    versions = set().union(*stated.values())
    assert len(versions) == 1, f"the lineage protocol floor is documented as {sorted(versions)}"


def test_the_packaged_extra_still_permits_a_release_below_the_documented_floor():
    """The README tells the reader to upgrade by hand, which the extra must justify."""
    # The packaged extra is read straight off the package, which the root check
    # at the top of this module guarantees is there: it is not a cookbook file
    # and a checkout without the cookbook still has it.
    documented = re.search(r"ag-ui-protocol>=(\d+\.\d+\.\d+)", _doc(_README))
    packaged = re.search(r"ag-ui-protocol>=(\d+\.\d+\.\d+)", _PACKAGE_PYPROJECT.read_text(encoding="utf-8"))
    assert documented is not None and packaged is not None

    def parts(match: re.Match) -> tuple:
        return tuple(int(piece) for piece in match.group(1).split("."))

    assert parts(packaged) < parts(documented), (
        "the agui extra now requires the lineage events, so the README should stop "
        "saying it allows older releases and stop teaching a manual upgrade"
    )


def _bullet_naming(log: str, phrase: str) -> str:
    """The one list item that makes a claim, so names are read from that claim alone."""
    assert phrase in log, f"the Validation section no longer says {phrase!r}"
    return log[log.index(phrase) :].split("\n- ")[0]


def test_the_validation_counts_match_the_folder():
    log = _doc(_TEST_LOG)
    if not _COOKBOOK.exists():
        pytest.skip("cookbook not present in this checkout")
    root = _root_examples()

    # The document states its own breakdown, and the files beyond the root are
    # read from that sentence rather than from a recursive walk: a walk counts
    # anything a nested frontend's installed dependencies bring with them, and
    # would disagree with the non-recursive count the files table is checked
    # against.
    breakdown = re.search(r"the (\d+) in its root plus ((?:`[^`]+\.py`(?:,| and)? ?)+)", " ".join(log.split()))
    assert breakdown is not None, "the Validation section no longer states how its count is made up"
    assert int(breakdown.group(1)) == len(root), (
        f"the Validation section counts {breakdown.group(1)} files in the folder root, which holds {len(root)}"
    )
    nested = re.findall(r"`([^`]+\.py)`", breakdown.group(2))
    assert nested, "the Validation section names no file beyond the root, so its total cannot be checked"
    absent = sorted(name for name in nested if not (_COOKBOOK / name).exists())
    assert not absent, f"the Validation section counts files that are gone: {absent}"
    servers = len(root) + len(nested)

    booted = re.search(r"All (\d+) server files", log)
    assert booted is not None, "the Validation section no longer counts the server files it booted"
    assert int(booted.group(1)) == servers

    scanned = re.search(r"checked exactly (\d+) Python files", log)
    assert scanned is not None, "the Validation section no longer counts the scanned Python files"
    assert int(scanned.group(1)) == servers

    posted = re.search(r"(\d+) of the (\d+) files completed", log)
    assert posted is not None, "the Validation section no longer counts the completed POST flows"
    assert int(posted.group(2)) == servers
    # The shortfall is derived from the files the same claim names as covered
    # elsewhere, rather than from a hard-coded allowance of one.
    # The same pattern the nested files are read with: a name written with a
    # directory in front of it is one of the files this claim can excuse, and a
    # pattern that could not match one reported it as excusing something the
    # folder does not hold.
    uncovered = re.findall(r"`([^`]+\.py)`", _bullet_naming(log, "of the {} files completed".format(servers)))
    assert uncovered, "the Validation section no longer names the files whose POST flow it did not run"
    missing = sorted(name for name in uncovered if name not in root and name not in nested)
    assert not missing, f"the Validation section excuses files the folder does not hold: {missing}"
    assert int(posted.group(1)) == servers - len(set(uncovered))


def test_the_test_log_cites_suites_that_exist():
    cited = re.findall(r"`(libs/agno/tests/[^`\n]+\.py)`", _doc(_TEST_LOG))
    assert cited, "the test log cites no unit suite for the payloads it does not run itself"
    missing = sorted(path for path in cited if not (_REPO_ROOT / path).exists())
    assert not missing, f"the test log cites suites that are gone: {missing}"
