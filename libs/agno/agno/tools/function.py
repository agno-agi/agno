import types
from dataclasses import dataclass
from functools import lru_cache, partial, wraps
from importlib.metadata import version
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from docstring_parser import parse
from packaging.version import Version
from pydantic import BaseModel, Field, validate_call

from agno.exceptions import AgentRunException, RunCancelledException
from agno.media import Audio, File, Image, Video
from agno.run import RunContext
from agno.utils.log import log_debug, log_exception, log_warning

T = TypeVar("T")

# The media the caller attached to the run. Unlike the other injected names these
# carry the call's input rather than framework plumbing, so they decide whether a
# call can be cached at all (see _has_injected_media).
MEDIA_INJECTED_PARAMS = ("images", "videos", "audios", "files")

# Parameter names the framework fills in itself (see FunctionCall._build_entrypoint_args).
# They are kept out of the model-facing schema, and a model-supplied value for one of
# them is discarded in favour of the injected object.
FRAMEWORK_INJECTED_PARAMS = ("agent", "team", "run_context", *MEDIA_INJECTED_PARAMS)

# The `_agno_`-prefixed channels, used by wrappers whose tools may have arguments
# legitimately named "agent", "team" or "run_context" (e.g. MCP tools).
AGNO_INJECTED_PARAMS = ("_agno_agent", "_agno_team", "_agno_run_context")

# The subset carrying the caller's identity or a live framework object. A schema may
# claim a media name -- a wrapper can expose the wrapped tool's own `files` argument --
# but never these: a model-supplied value here would choose whose data the tool reads.
IDENTITY_INJECTED_PARAMS = ("agent", "team", "run_context", *AGNO_INJECTED_PARAMS)


def _identity_injected_types() -> tuple:
    """The identity-bearing types: a model-supplied value for a parameter of
    one of these types would choose the framework object a tool receives.

    An identity-typed parameter is hidden from the model and bound by
    FunctionCall._build_entrypoint_args, whatever its name. Bare media
    annotations are hidden too (_is_bare_media_typed) but are filled by the
    reserved parameter names alone, never by type."""
    from agno.agent.agent import Agent
    from agno.team.team import Team

    return (Agent, Team, RunContext)


# What a cache entry holds. Bump this whenever the meaning of a stored value
# changes: entries written under any other version are discarded unread, which
# costs one re-execution and keeps a stale reading from reaching a model.
# Version 2 stores the entrypoint's own return, where version 1 stored whatever
# the tool_hook chain made of it.
CACHE_FORMAT = 2


class _StaleCacheEntry(Exception):
    """A cache entry that no longer matches what the code returns."""


def _make_private_dir(directory: Any) -> None:
    """Create the cache directory, and refuse one somebody else can write.

    The default location is a shared temporary directory under a predictable
    name, so a directory already there may not be ours. Raising leaves the tool
    call itself alone: the caller treats an unusable cache directory as a
    reason to stop caching, not a reason to fail."""
    import os
    import stat

    missing = []
    probe = directory
    while not probe.exists():
        missing.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent
    for level in reversed(missing):
        try:
            level.mkdir(mode=0o700)
        except FileExistsError:
            pass

    if not hasattr(os, "geteuid"):
        # Ownership and permission bits mean nothing here: every directory
        # reports the same mode, so there is nothing to read them for.
        return

    owner = os.geteuid()
    for level in (directory, directory.parent, directory.parent.parent):
        info = level.stat()
        if info.st_uid != owner:
            raise PermissionError(f"Refusing a cache directory owned by another user: {level}")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            # These three levels are ours to keep, and an earlier release made
            # them with whatever the umask allowed. Close them rather than
            # refuse them, so upgrading does not cost a caller its caching.
            level.chmod(info.st_mode & ~(stat.S_IWGRP | stat.S_IWOTH))


def _has_injected_media(entrypoint_args: Dict[str, Any]) -> bool:
    """True when the call carries attached media.

    Media is the input the tool computes over, and it contributes nothing to
    the cache key, so two calls over different documents look identical to it.
    Such a call is neither served from the cache nor written to it."""
    return any(entrypoint_args.get(name) for name in MEDIA_INJECTED_PARAMS)


# Stands in for an entrypoint call that left no value the cache can keep: one
# that raised, and one whose return could not be copied. Recording it keeps the
# count of entrypoint calls honest while making the call uncacheable.
_NO_RESULT = object()


def _start_entrypoint_call(raw_results: List[Any]) -> int:
    """Count an entrypoint call that is about to run, and return its slot.

    The slot is claimed before the call, so a call that raises still counts. A
    hook that retried past a failure ran the tool twice, and what the retry
    returned does not stand for the call."""
    raw_results.append(_NO_RESULT)
    return len(raw_results) - 1


def _detached(value: Any) -> Any:
    """A copy of a cached value for one entrypoint call to keep.

    A hook may call the entrypoint more than once, and on a miss each call
    returns its own object. Handing every call the same stored object would let
    one call's edits show up in the next."""
    from copy import deepcopy

    try:
        return deepcopy(value)
    except Exception:
        return value


def _carries_media(value: Any, depth: int = 0) -> bool:
    """Whether a ToolResult holding media sits anywhere inside this value.

    Media never reaches a cache file, so a stored value that holds some did not
    come from here, and one about to be stored would lose it. The walk follows
    types rather than names, so an ordinary dict with an "images" key is not
    mistaken for one."""
    if depth > 32:
        return False
    if isinstance(value, ToolResult):
        if value.images or value.videos or value.audios or value.files:
            return True
    if isinstance(value, BaseModel):
        parts: Any = list(value.__dict__.values()) + list((value.__pydantic_extra__ or {}).values())
    elif isinstance(value, dict):
        parts = list(value.values())
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return False
    return any(_carries_media(part, depth + 1) for part in parts)


def _shares_a_reference(value: Any, seen: Optional[List[int]] = None, depth: int = 0) -> bool:
    """Whether one object sits in more than one place inside this value.

    JSON keeps no record of that sharing, so a value written with it comes back
    with as many separate objects as it had places."""
    if depth > 32:
        return False
    if isinstance(value, BaseModel):
        parts: Any = list(value.__dict__.values())
    elif isinstance(value, dict):
        parts = list(value.values())
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return False
    seen = [] if seen is None else seen
    if id(value) in seen:
        return True
    seen.append(id(value))
    return any(_shares_a_reference(part, seen, depth + 1) for part in parts)


def _faithful(original: Any, rebuilt: Any, depth: int = 0) -> bool:
    """Whether a value read back from the cache is the value that was stored.

    Equality alone is too weak: an IntEnum member equals the plain integer it
    was written as, and a hook that reads .name off it would work on the miss
    and fail on the hit. Every node has to come back as its own type."""
    if depth > 32:
        return original == rebuilt
    if type(original) is not type(rebuilt):
        return False
    if isinstance(original, BaseModel):
        return all(
            key in rebuilt.__dict__ and _faithful(value, rebuilt.__dict__[key], depth + 1)
            for key, value in original.__dict__.items()
        )
    if isinstance(original, dict):
        if set(map(type, original)) != set(map(type, rebuilt)) or original.keys() != rebuilt.keys():
            return False
        return all(_faithful(value, rebuilt[key], depth + 1) for key, value in original.items())
    if isinstance(original, (list, tuple)):
        if len(original) != len(rebuilt):
            return False
        return all(_faithful(a, b, depth + 1) for a, b in zip(original, rebuilt))
    return bool(original == rebuilt)


def _record_entrypoint_result(raw_results: List[Any], slot: int, result: Any) -> None:
    """Record what the entrypoint returned, detached from the caller.

    The hooks run after this and may edit the result in place, so the cache
    must keep a copy rather than the object itself."""
    from copy import deepcopy

    try:
        snapshot = deepcopy(result)
    except Exception as e:
        log_debug(f"Result could not be copied for the cache, so this call is not cacheable: {e}")
        return
    if snapshot is result and isinstance(result, (dict, list, set, BaseModel)):
        # A value may answer deepcopy with itself. The hooks run next and may
        # edit it, and those edits would reach what the cache keeps.
        log_debug(f"Result did not detach from a copy, so this call is not cacheable: {type(result).__name__}")
        return
    if _shares_a_reference(result):
        # Two fields backed by one object come back as two on the far side of a
        # JSON round trip, and a hook that edits one would then see a different
        # value from the one the miss gave it.
        log_debug("Result holds the same object in more than one place, so this call is not cacheable")
        return
    raw_results[slot] = snapshot


def _unwrap_annotation(hint: Any) -> Any:
    """The annotation a type alias stands for (PEP 695 ``type X = ...``), else
    the annotation itself. get_type_hints leaves an alias unresolved.

    Aliases chain (``type A = RunContext; type B = A``), so unwrapping repeats
    to a fixpoint: any depth left unresolved is an identity annotation the model
    can still fill. The seen list holds strong references, so a self-referential
    alias terminates without relying on ids that a collected object could
    reuse."""
    seen: List[Any] = []
    while True:
        if isinstance(hint, types.GenericAlias) and hasattr(get_origin(hint), "__value__"):
            # A subscripted generic alias (``Maybe[Weather]``) keeps what it was
            # given only while it stays subscripted. Its __value__ is the body
            # with the parameter still loose, so following it loses the Weather.
            return hint
        # A PEP 695 alias carries __value__; typing.NewType carries
        # __supertype__ and is just as transparent to pydantic, which builds
        # the supertype from a model-supplied dict either way.
        unwrapped = getattr(hint, "__value__", None)
        if unwrapped is None:
            unwrapped = getattr(hint, "__supertype__", hint)
        if unwrapped is hint or any(unwrapped is s for s in seen):
            return hint
        seen.append(hint)
        hint = unwrapped


def _mentions_base_model(hint: Any, seen: Optional[List[Any]] = None) -> bool:
    """True when the annotation is a BaseModel or holds one, at any depth.

    Cached results are only rebuilt into a declared type when the code says it
    returns a model. A tool annotated str or dict keeps handing back exactly
    what the cache file holds, so an annotation the tool does not honour costs
    nothing.

    An alias may name itself (``type JSON = str | list[JSON]``), so the seen
    list stops the walk from following one round and round."""
    hint = _unwrap_annotation(hint)
    if isinstance(hint, type):
        try:
            return issubclass(hint, BaseModel)
        except TypeError:
            return False
    seen = [] if seen is None else seen
    if any(hint is s for s in seen):
        return False
    seen.append(hint)
    return any(_mentions_base_model(arg, seen) for arg in get_args(hint))


def _dump_for_cache(model: BaseModel) -> Any:
    """What _save_to_cache writes for this model, as JSON gives it back.

    A round trip turns tuples into lists and dates into strings, so a rebuilt
    value can only be compared with a stored one on the far side of one."""
    import json

    return json.loads(json.dumps(model.model_dump(), default=str))


def _validate_by_field_name(adapter: Any, payload: Any) -> Any:
    """Rebuild a value this cache wrote.

    Entries are written with model_dump(), which emits field names, so a model
    whose fields carry aliases has to be validated by name or it would never be
    readable. Older pydantic releases take no such argument and accept field
    names anyway."""
    try:
        return adapter.validate_python(payload, by_name=True)
    except TypeError:
        return adapter.validate_python(payload)


@lru_cache(maxsize=256)
def _return_type_adapter(hint: Any) -> Any:
    """A validator for a return annotation, or None when one cannot be built."""
    from pydantic import TypeAdapter

    try:
        return TypeAdapter(hint)
    except Exception:
        return None


def _is_union(hint: Any) -> bool:
    origin = get_origin(hint)
    return origin is Union or origin is getattr(types, "UnionType", None)


def _union_names_type(hint: Any, wanted: tuple) -> bool:
    """True when the annotation is a union with a member among the wanted types,
    nested unions and type aliases included. Asks whether the type is mentioned
    at all, unlike _union_is_only.

    Used to decide whether pydantic's validate_call can introspect the
    signature: one Agent/Team member anywhere in a union is enough to break it.
    """
    hint = _unwrap_annotation(hint)
    if not _is_union(hint):
        return False
    return any(_member_names_type(arg, wanted) for arg in get_args(hint) if arg is not type(None))


def _member_names_type(arg: Any, wanted: tuple) -> bool:
    """Whether one union member names a wanted type. The member is unwrapped first:
    a PEP 695 alias nested inside a union (``type C = RunContext; type M = C | None``)
    is a TypeAliasType, not a type, and would otherwise slip past both checks."""
    arg = _unwrap_annotation(arg)
    return (isinstance(arg, type) and issubclass(arg, wanted)) or _union_names_type(arg, wanted)


def _union_is_only(hint: Any, wanted: tuple) -> bool:
    """True when the annotation is a union (Optional[...], X | None) whose every
    non-None member is one of the wanted types, nested unions and type aliases
    included.

    "Only" is the point. A union that also names an ordinary type
    (owner: Union[str, Agent]) keeps a half the model can legitimately fill --
    the model can send a string, never a live Agent -- so it stays in the
    schema. Optional[Agent] has no such half."""
    hint = _unwrap_annotation(hint)
    if not _is_union(hint):
        return False
    members = [arg for arg in get_args(hint) if arg is not type(None)]
    if not members:
        return False
    return all(_member_is_only(arg, wanted) for arg in members)


def _member_is_only(arg: Any, wanted: tuple) -> bool:
    """Whether one union member is a wanted type, unwrapping a nested PEP 695 alias
    first for the same reason as _member_names_type."""
    arg = _unwrap_annotation(arg)
    return (isinstance(arg, type) and issubclass(arg, wanted)) or _union_is_only(arg, wanted)


def _is_framework_typed(hint: Any) -> bool:
    """True when the framework owns the parameter: it is kept out of the
    model-facing schema and filled by _build_entrypoint_args instead.

    Excluded:
      * a bare identity type (owner: Agent, ctx: RunContext);
      * a union of identity types alone (Optional[Agent], RunContext | None),
        which has no half a model could legitimately fill;
      * ANY union naming RunContext (ctx: Union[str, RunContext]). RunContext is
        the one identity type pydantic can build from a model-supplied dict --
        validate_call is skipped for Agent/Team parameters but not for this one,
        so an exposed union coerces {"user_id": ...} into a live RunContext and
        hands the model the caller's identity.

    Model-fillable:
      * media inside a union (Optional[Image], Union[str, File]): media is
        injected by parameter name alone, so hiding the union would leave it
        unfillable by anything. A BARE media annotation (pic: Image) is hidden
        all the same -- see _is_bare_media_typed;
      * a union naming Agent or Team beside an ordinary type
        (owner: Union[str, Agent]). The model can only ever send JSON, so such a
        parameter receives a plain dict or string, never a live Agent."""
    return _reaches_identity(hint)


_ANNOTATION_DEPTH_CAP = 16


def _reaches_identity(hint: Any, depth: int = 0, seen: Optional[List[Any]] = None) -> bool:
    """Whether an annotation can deliver an identity object the model chose.

    Walks the whole annotation -- containers, the container arms of a union,
    and the fields of a dataclass or pydantic model -- because every one of
    those is a place pydantic will happily build a RunContext out of a
    model-supplied dict.

    Two rules that look inconsistent and are not:

      * ANY appearance of RunContext hides the parameter. It is the one
        identity type pydantic constructs from JSON, so wherever it can be
        reached, the model can choose the caller's identity.
      * Agent and Team hide only when the annotation offers no half a model
        could legitimately fill -- bare, or a union of identity alone.
        ``owner: Union[str, Agent]`` stays the model's to fill, at the top
        level and inside a list alike: validate_call is skipped for those
        types, so the tool receives a plain dict or string, never a live
        Agent, and hiding it would leave it fillable by nothing.

    Media never reaches here as identity: it is injected by reserved name
    alone, so hiding a media container would make it unfillable."""
    if depth > _ANNOTATION_DEPTH_CAP:
        return True  # Unreadable is not fillable; fail closed.
    seen = [] if seen is None else seen
    hint = _unwrap_annotation(hint)
    if any(hint is s for s in seen):
        return False
    seen = seen + [hint]
    # RunContext anywhere at all, however deeply wrapped.
    if _annotation_reaches(hint, (RunContext,)):
        return True
    if isinstance(hint, type):
        return _annotation_reaches(hint, _identity_injected_types())
    if _is_union(hint):
        # A union is the model's to fill as long as one arm is something the
        # model can legitimately send. Only when every arm is identity -- bare
        # Agent, Optional[Agent] -- is there nothing else it could mean.
        arms = [arm for arm in get_args(hint) if arm is not type(None)]
        return bool(arms) and all(_reaches_identity(arm, depth + 1, seen) for arm in arms)
    return any(_reaches_identity(argument, depth + 1, seen) for argument in get_args(hint))


def _annotation_binds(hint: Any, wanted: tuple, depth: int = 0, seen: Optional[List[Any]] = None) -> bool:
    """Whether the framework can put one of these objects INTO this parameter.

    Deliberately narrower than _annotation_reaches, and the pair is not a
    contradiction: reaching decides what to keep from the model, binding
    decides what can be handed over. A ``list[RunContext]`` reaches one -- so
    it is not the model's to fill -- but it holds run contexts, it is not one,
    and binding the object there would fail validation on every call.

    Unwraps aliases and NewType, follows a TypeVar's bound and constraints, and
    accepts a union with an arm that binds. A container or a structural wrapper
    does not bind: nothing the framework has is that shape."""
    if depth > _ANNOTATION_DEPTH_CAP:
        return False
    seen = [] if seen is None else seen
    hint = _unwrap_annotation(hint)
    if any(hint is s for s in seen):
        return False
    seen = seen + [hint]
    if isinstance(hint, type):
        return issubclass(hint, wanted)
    if isinstance(hint, TypeVar):
        bound = getattr(hint, "__bound__", None)
        if bound is not None and _annotation_binds(bound, wanted, depth + 1, seen):
            return True
        return any(
            _annotation_binds(constraint, wanted, depth + 1, seen)
            for constraint in getattr(hint, "__constraints__", ()) or ()
        )
    if _is_union(hint):
        return any(_annotation_binds(arm, wanted, depth + 1, seen) for arm in get_args(hint))
    return False


def _annotation_reaches(hint: Any, targets: tuple, depth: int = 0, seen: Optional[List[Any]] = None) -> bool:
    """Whether any of these types can be reached anywhere inside an annotation.

    A plain structural search, with none of _reaches_identity's asymmetry: it
    walks containers, every arm of a union, a TypeVar's bound and constraints,
    and the fields of any structural type -- dataclass, pydantic model,
    TypedDict, NamedTuple -- resolving them with get_type_hints so an
    annotation stored as a string under ``from __future__ import annotations``
    is read rather than skipped.

    Two things fail CLOSED, because a reference this cannot resolve is not one
    to hand the model: a nesting depth no real signature reaches, and a class
    whose own hints will not resolve."""
    from dataclasses import is_dataclass

    if depth > _ANNOTATION_DEPTH_CAP:
        return True
    seen = [] if seen is None else seen
    hint = _unwrap_annotation(hint)
    if any(hint is s for s in seen):
        return False
    seen = seen + [hint]

    if isinstance(hint, TypeVar):
        # A bound or a constraint is a promise about what will be substituted.
        bound = getattr(hint, "__bound__", None)
        if bound is not None and _annotation_reaches(bound, targets, depth + 1, seen):
            return True
        return any(
            _annotation_reaches(constraint, targets, depth + 1, seen)
            for constraint in getattr(hint, "__constraints__", ()) or ()
        )

    if isinstance(hint, type):
        if issubclass(hint, targets):
            return True
        if issubclass(hint, _identity_injected_types()):
            # A framework object is not a user wrapper to search inside. Its own
            # hints do not resolve here (Agent names BaseDb), and descending
            # would fail closed on every annotation that merely mentions one --
            # which would hide `owner: Union[str, Agent]`, the shape the rules
            # above exist to keep fillable.
            return False
        is_structural = (
            isinstance(getattr(hint, "model_fields", None), dict)
            or is_dataclass(hint)
            or hasattr(hint, "__annotations__")
            and (getattr(hint, "__total__", None) is not None or hasattr(hint, "_fields"))
        )
        if not is_structural:
            return False
        try:
            field_hints = get_type_hints(hint)
        except Exception:
            return True  # Cannot read it, so cannot clear it.
        return any(_annotation_reaches(field_hint, targets, depth + 1, seen) for field_hint in field_hints.values())

    return any(_annotation_reaches(argument, targets, depth + 1, seen) for argument in get_args(hint))


def _is_bare_media_typed(hint: Any) -> bool:
    """True for a parameter annotated with a media type itself (pic: Image).

    On the process_entrypoint path (Toolkit methods, @tool) such a parameter is
    hidden from the model, as on v2.8.7: media is injected by the reserved
    parameter names alone (images/videos/audios/files, see
    FunctionCall._build_entrypoint_args), so the framework can never fill it,
    and exposing it would let the model fabricate the object while its pydantic
    schema is invalid under strict mode, failing the whole request rather than
    one call. from_callable does NOT use this predicate -- v2.8.7 never hid
    media on the plain-callable path, where the parameter is the model's to
    fill. Media inside a union (Union[str, Image]) stays model-fillable on
    both paths."""
    hint = _unwrap_annotation(hint)
    return isinstance(hint, type) and issubclass(hint, (Image, Video, Audio, File))


def _is_schema_excluded(hint: Any) -> bool:
    """True when process_entrypoint keeps the parameter out of the model-facing
    schema: the identity types plus bare media types.

    Exclusion only. Framework OWNERSHIP is _is_framework_typed, a strictly
    smaller set: an owned parameter is bound by _build_entrypoint_args and a
    value supplied for it is dropped, neither of which is true of media."""
    return _is_framework_typed(hint) or _is_bare_media_typed(hint)


_hidden_media_warned: Set[Tuple[str, str]] = set()


def _warn_hidden_media(function_name: str, param_name: str) -> None:
    # Schema processing runs on the per-run pipeline, not once at registration;
    # warn once per (function, param) or a long-lived process logs it forever.
    key = (function_name, param_name)
    if key in _hidden_media_warned:
        return
    _hidden_media_warned.add(key)
    log_warning(
        f"Parameter '{param_name}' of function '{function_name}' has a media type but not a "
        "reserved media name: the run's media never lands there, and it is hidden from the "
        "model-facing schema. Rename it to images/videos/audios/files to receive the run's media."
    )


@lru_cache(maxsize=1)
def _get_pydantic_version() -> Version:
    return Version(version("pydantic"))


def get_entrypoint_docstring(entrypoint: Callable) -> str:
    from inspect import getdoc

    if isinstance(entrypoint, partial):
        return str(entrypoint)

    docstring = getdoc(entrypoint)
    if not docstring:
        return ""

    parsed_doc = parse(docstring)

    # Combine short and long descriptions
    lines = []
    if parsed_doc.short_description:
        lines.append(parsed_doc.short_description)
    if parsed_doc.long_description:
        lines.extend(parsed_doc.long_description.split("\n"))

    return "\n".join(lines)


@dataclass
class UserInputField:
    name: str
    field_type: Type
    description: Optional[str] = None
    value: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "field_type": str(self.field_type.__name__),
            "description": self.description,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserInputField":
        type_mapping = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}
        field_type_raw = data["field_type"]
        if isinstance(field_type_raw, str):
            field_type = type_mapping.get(field_type_raw, str)
        elif isinstance(field_type_raw, type):
            field_type = field_type_raw
        else:
            field_type = str
        return cls(
            name=data["name"],
            field_type=field_type,
            description=data["description"],
            value=data["value"],
        )


@dataclass
class UserFeedbackOption:
    """An option for a user feedback question."""

    label: str
    description: Optional[str] = None
    selected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "description": self.description,
            "selected": self.selected,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserFeedbackOption":
        return cls(
            label=data["label"],
            description=data.get("description"),
            selected=data.get("selected", False),
        )


@dataclass
class UserFeedbackQuestion:
    """A structured question with predefined options for user feedback."""

    question: str
    header: Optional[str] = None
    options: Optional[List["UserFeedbackOption"]] = None
    multi_select: bool = False
    selected_options: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "question": self.question,
            "header": self.header,
            "multi_select": self.multi_select,
            "selected_options": self.selected_options,
        }
        if self.options is not None:
            result["options"] = [opt.to_dict() for opt in self.options]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserFeedbackQuestion":
        options = None
        if data.get("options") is not None:
            options = [UserFeedbackOption.from_dict(opt) if isinstance(opt, dict) else opt for opt in data["options"]]
        return cls(
            question=data["question"],
            header=data.get("header"),
            options=options,
            multi_select=data.get("multi_select", False),
            selected_options=data.get("selected_options"),
        )


# What Function.to_dict() writes and from_dict() reads back: the choices that
# belong to the saved component, so a later registry edit must not rewrite them.
SERIALIZED_FIELDS = (
    "name",
    "description",
    "parameters",
    "strict",
    "requires_confirmation",
    "external_execution",
    "approval_type",
)

# Fields Function.to_dict() deliberately omits and from_dict() cannot rebuild.
# They describe how the tool behaves rather than what the saved component chose,
# and several hold callables that do not serialize at all. Registry rehydration
# copies them back from the live Function, so a reloaded component behaves like
# the tool it was built from and picks up registry-side edits. The fields
# to_dict() *does* carry stay as persisted: the saved config owns those.
# Consumed by Registry._rehydrate_function.
RUNTIME_ONLY_FIELDS = (
    "instructions",
    "add_instructions",
    # Entrypoints built for a fixed schema (e.g. MCP call proxies) must not be
    # re-introspected at run time: processing would rebuild the schema's
    # `required` list from the proxy's signature.
    "skip_entrypoint_processing",
    "show_result",
    "stop_after_tool_call",
    "pre_hook",
    "post_hook",
    "tool_hooks",
    # Without these, process_entrypoint stops excluding the user-supplied
    # fields, so `required` lists a property the schema never defines and the
    # gate that would have collected it is gone.
    "requires_user_input",
    "user_input_fields",
    "user_input_schema",
    "external_execution_silent",
    "cache_results",
    "cache_dir",
    "cache_ttl",
)


def isolated_runtime_value(value: Any) -> Any:
    """A per-component copy of a value restored from a live registry Function.

    Restoring by reference would let every component that loaded the same tool
    share the registry Function's mutable state. ``user_input_schema`` is the
    one that bites: the model layer writes the user's answer straight into its
    ``UserInputField`` objects, so one run's input would be visible to every
    other component holding that tool, and to the registry itself.

    Lists are rebuilt rather than deep-copied, so callables such as tool hooks
    stay the same objects; only dataclass elements are copied, because those
    are the ones written in place. No RUNTIME_ONLY_FIELDS entry holds a dict,
    so lists are the only containers handled.
    """
    from copy import copy
    from dataclasses import is_dataclass

    if isinstance(value, list):
        return [copy(item) if is_dataclass(item) else item for item in value]
    return value


class Function(BaseModel):
    """Model for storing functions that can be called by an agent."""

    # The name of the function to be called.
    # Must be a-z, A-Z, 0-9, or contain underscores and dashes, with a maximum length of 64.
    name: str
    # A description of what the function does, used by the model to choose when and how to call the function.
    description: Optional[str] = None
    # The parameters the functions accepts, described as a JSON Schema object.
    # To describe a function that accepts no parameters, provide the value {"type": "object", "properties": {}}.
    parameters: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []},
        description="JSON Schema object describing function parameters",
    )
    strict: Optional[bool] = None

    instructions: Optional[str] = None
    # If True, add instructions to the Agent's system message
    add_instructions: bool = True

    # The function to be called.
    entrypoint: Optional[Callable] = None
    # If True, the entrypoint processing is skipped and the Function is used as is.
    skip_entrypoint_processing: bool = False
    # If True, the function call will show the result along with sending it to the model.
    show_result: bool = False
    # If True, the agent will stop after the function call.
    stop_after_tool_call: bool = False
    # Hook that runs before the function is executed.
    # If defined, can accept the FunctionCall instance as a parameter.
    pre_hook: Optional[Callable] = None
    # Hook that runs after the function is executed, regardless of success/failure.
    # If defined, can accept the FunctionCall instance as a parameter.
    post_hook: Optional[Callable] = None

    # A list of hooks to run around tool calls.
    tool_hooks: Optional[List[Callable]] = None

    # If True, the function will require confirmation before execution
    requires_confirmation: Optional[bool] = None

    # If True, the function will require user input before execution
    requires_user_input: Optional[bool] = None
    # List of fields that the user will provide as input and that should be ignored by the agent (empty list means all fields are provided by the user)
    user_input_fields: Optional[List[str]] = None
    # This is set during parsing, not by the user
    user_input_schema: Optional[List[UserInputField]] = None

    # If True, the function will be executed outside the agent's control.
    external_execution: Optional[bool] = None

    # If True (and external_execution=True), the function will not produce verbose paused messages (e.g., "I have tools to execute...")
    external_execution_silent: Optional[bool] = None

    # Approval type: "required" (blocking) or "audit" (non-blocking audit trail).
    # Set via the @approval decorator, not directly via @tool().
    approval_type: Optional[str] = None

    # Name of the Toolkit this function was flattened from, if any. Set by
    # Registry.rehydrate_function and read by the agent/team storage serializers
    # so toolkit attribution survives load -> save round trips. Excluded from
    # to_dict: it is persisted via the storage layer's "toolkit" key and never
    # sent to models.
    owning_toolkit: Optional[str] = None
    # Live Toolkit this function was flattened from during registry
    # rehydration. It restores toolkit-level behavior without persisting the
    # Toolkit or its instructions in component configs.
    source_toolkit: Optional[Any] = Field(default=None, exclude=True, repr=False)

    # Caching configuration
    cache_results: bool = False
    cache_dir: Optional[str] = None
    cache_ttl: int = 3600

    # --*-- FOR INTERNAL USE ONLY --*--
    # The agent that the function is associated with
    _agent: Optional[Any] = None
    # The team that the function is associated with
    _team: Optional[Any] = None
    # The run context that the function is associated with
    _run_context: Optional[RunContext] = None

    # Parameters process_entrypoint kept out of the model-facing schema because the
    # framework supplies them, by name or by type annotation (e.g. `ctx: RunContext`).
    _framework_params: Optional[Set[str]] = None

    # Media context that the function is associated with
    _images: Optional[Sequence[Image]] = None
    _videos: Optional[Sequence[Video]] = None
    _audios: Optional[Sequence[Audio]] = None
    _files: Optional[Sequence[File]] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True, include=set(SERIALIZED_FIELDS))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Function":
        """Reconstruct a Function from a dictionary."""

        return cls(
            name=data.get("name"),
            description=data.get("description"),
            parameters=data.get("parameters"),
            strict=data.get("strict"),
            requires_confirmation=data.get("requires_confirmation", False),
            external_execution=data.get("external_execution", False),
            approval_type=data.get("approval_type"),
        )

    def __deepcopy__(self, memo: Optional[Dict[int, Any]] = None) -> "Function":
        """Deep-copy runtime state while retaining the live source Toolkit.

        ``memo`` is optional because ``BaseModel.model_copy(deep=True)`` calls
        ``__deepcopy__()`` with no argument.
        """
        if memo is None:
            memo = {}
        if self.source_toolkit is not None:
            # AgentOS deep-copies each Function independently for request
            # isolation. Sharing the registry Toolkit keeps its connections and
            # current instructions, and keeps the entrypoint bound to the live
            # toolkit rather than to a detached clone of it.
            #
            # setdefault, not assignment: the memo belongs to the in-progress
            # copy. Overwriting an entry it already made would leave one
            # original with two stand-ins in the same object graph.
            memo.setdefault(id(self.source_toolkit), self.source_toolkit)
        return super().__deepcopy__(memo)

    def model_copy(self, *, deep: bool = False) -> "Function":
        """
        Override model_copy to handle callable fields that can't be deep copied (pickled).
        Callables should always be shallow copied (referenced), not deep copied.
        """
        # For deep copy, we need to handle callable fields specially
        if deep:
            # Fields that should NOT be deep copied (callables and complex objects)
            shallow_fields = {
                "entrypoint",
                "pre_hook",
                "post_hook",
                "tool_hooks",
                "_agent",
                "_team",
            }

            # Create a copy with shallow references to callable fields
            copied_data = {}
            for field_name, field_value in self.__dict__.items():
                if field_name in shallow_fields:
                    # Shallow copy - just reference the same object
                    copied_data[field_name] = field_value
                elif field_name in ("parameters", "user_input_schema"):
                    # Deep copy the mutable run state. parse_tools hands the
                    # model a per-run copy of each Function; the model layer
                    # then writes the user's answers into user_input_schema in
                    # place, so an aliased schema carries one run's input into
                    # every later run of the same component.
                    from copy import deepcopy

                    copied_data[field_name] = deepcopy(field_value)
                else:
                    # For simple types, just copy the value
                    copied_data[field_name] = field_value

            # Create new instance with copied data
            new_instance = self.__class__.model_construct(**copied_data)

            # model_construct does not carry private attributes. The per-run ones
            # (_agent, _run_context, media) are reassigned by the caller, but the
            # framework-param set describes the shared entrypoint, and a @tool-decorated
            # Function is copied without being reprocessed -- so carry it across.
            new_instance._framework_params = set(self._framework_params) if self._framework_params is not None else None

            return new_instance
        else:
            # For shallow copy, use the default Pydantic behavior
            return super().model_copy(deep=False)

    @classmethod
    def from_callable(cls, c: Callable, name: Optional[str] = None, strict: bool = False) -> "Function":
        from inspect import getdoc, signature

        from agno.utils.json_schema import get_json_schema

        function_name = name or c.__name__
        parameters = {"type": "object", "properties": {}, "required": []}
        resolved_framework_params: Set[str] = set()
        try:
            sig = signature(c)
            type_hints = get_type_hints(c)

            # Params the framework injects by TYPE, not just by reserved name (e.g.
            # ctx: RunContext, my_agent: Agent). from_callable does not run
            # process_entrypoint, so record them here too: they are excluded from the
            # model schema below and stored on the Function so FunctionCall's injection
            # guard rejects a model-supplied value for them on this path too. See #6344.
            framework_typed_params: Set[str] = set()
            try:
                # Identity only, not _is_schema_excluded: v2.8.7's from_callable never
                # hid media by type, so a bare media param on a plain callable stays
                # the model's to fill (pydantic coerces the dict) -- unlike the
                # process_entrypoint path, which hid it then and hides it now.
                for _pname in sig.parameters:
                    _hint = type_hints.get(_pname)
                    if _hint is not None and _is_framework_typed(_hint):
                        framework_typed_params.add(_pname)
            except Exception:
                pass
            _reserved_names = {"return", "self", *FRAMEWORK_INJECTED_PARAMS, *AGNO_INJECTED_PARAMS}
            resolved_framework_params = {n for n in sig.parameters if n in _reserved_names} | framework_typed_params

            # If function has an the agent argument, remove the agent parameter from the type hints
            if "agent" in sig.parameters and "agent" in type_hints:
                del type_hints["agent"]
            if "team" in sig.parameters and "team" in type_hints:
                del type_hints["team"]
            if "run_context" in sig.parameters and "run_context" in type_hints:
                del type_hints["run_context"]

            # Remove media parameters from type hints as they are injected automatically
            if "images" in sig.parameters and "images" in type_hints:
                del type_hints["images"]
            if "videos" in sig.parameters and "videos" in type_hints:
                del type_hints["videos"]
            if "audios" in sig.parameters and "audios" in type_hints:
                del type_hints["audios"]
            if "files" in sig.parameters and "files" in type_hints:
                del type_hints["files"]
            # log_info(f"Type hints for {function_name}: {type_hints}")

            # Filter out return type and only process parameters
            param_type_hints = {
                name: type_hints.get(name)
                for name in sig.parameters
                if name not in ("return", "self")
                and name not in FRAMEWORK_INJECTED_PARAMS
                and name not in AGNO_INJECTED_PARAMS
                and name not in framework_typed_params
            }

            # Parse docstring for parameters
            param_descriptions: Dict[str, Any] = {}
            if docstring := getdoc(c):
                parsed_doc = parse(docstring)
                param_docs = parsed_doc.params

                if param_docs is not None:
                    for param in param_docs:
                        param_name = param.arg_name
                        param_type = param.type_name
                        if param_type is None:
                            param_descriptions[param_name] = param.description
                        else:
                            param_descriptions[param_name] = f"({param_type}) {param.description}"

            # Get JSON schema for parameters only
            parameters = get_json_schema(
                type_hints=param_type_hints, param_descriptions=param_descriptions, strict=strict
            )

            # If strict=True mark all fields as required
            # See: https://platform.openai.com/docs/guides/structured-outputs/supported-schemas#all-fields-must-be-required
            if strict:
                parameters["required"] = [
                    name
                    for name in parameters["properties"]
                    if name not in ("return", "self")
                    and name not in FRAMEWORK_INJECTED_PARAMS
                    and name not in AGNO_INJECTED_PARAMS
                ]
            else:
                # Mark a field as required if it has no default value (this would include optional fields)
                parameters["required"] = [
                    name
                    for name, param in sig.parameters.items()
                    if param.default == param.empty
                    and name not in ("return", "self")
                    and name not in FRAMEWORK_INJECTED_PARAMS
                    and name not in AGNO_INJECTED_PARAMS
                ]

            # A param whose type has no JSON schema (e.g. `fc: FunctionCall`) is skipped by
            # get_json_schema, so requiring it would describe a property that does not exist.
            parameters["required"] = [name for name in parameters["required"] if name in parameters["properties"]]

            # log_debug(f"JSON schema for {function_name}: {parameters}")
        except Exception as e:
            log_warning(f"Could not parse args for {function_name}: {str(e)}")

        entrypoint = cls._wrap_callable(c)

        func = cls(
            name=function_name,
            description=get_entrypoint_docstring(entrypoint=c),
            parameters=parameters,
            entrypoint=entrypoint,
        )
        # process_entrypoint sets this on the paths that run it; from_callable does not,
        # so set it here or the injection guard is inert for framework-typed params.
        func._framework_params = resolved_framework_params
        return func

    def _resolve_framework_params(self) -> Set[str]:
        """Names in the entrypoint signature that the framework supplies, not the model.

        Read by FunctionCall._drop_injected_overrides to reject model-supplied values for
        them. Covers both rules process_entrypoint uses to hide a parameter from the
        schema: the reserved names, and the framework-typed annotations of issue #6344.
        """
        from inspect import signature

        if self.entrypoint is None:
            return set()
        try:
            sig = signature(self.entrypoint)
        except Exception:
            return set()

        reserved = {"return", "self", *FRAMEWORK_INJECTED_PARAMS, *AGNO_INJECTED_PARAMS}
        found = {name for name in sig.parameters if name in reserved}
        try:
            hints = get_type_hints(self.entrypoint)
        except Exception:
            return found
        for param_name, hint in hints.items():
            if param_name not in sig.parameters:
                continue
            # Per parameter, not per signature. One annotation this walk cannot
            # read used to abort the loop, so a recursive alias sitting BEFORE
            # `ctx: RunContext` left ctx unclassified and model-facing -- the
            # parameter's own protection undone by an unrelated neighbour.
            try:
                # Identity only, not _is_schema_excluded. A bare media parameter is
                # hidden from the schema, but dropping a value supplied for it
                # displaces nothing: media is injected by reserved name alone, so the
                # caller's own media never lands there under any behaviour. Dropping
                # would only make the parameter unfillable by anything, which v2.8.7
                # did not do.
                owned = _is_framework_typed(hint)
            except Exception:
                owned = True  # Cannot classify it, so do not hand it to the model.
            if owned:
                found.add(param_name)
        return found

    def process_entrypoint(self, strict: bool = False):
        """Process the entrypoint and make it ready for use by an agent."""
        from inspect import getdoc, signature

        from agno.utils.json_schema import get_json_schema

        # Record which parameters the framework owns before the early returns below:
        # Toolkit rebuilds each @tool method as a skip_entrypoint_processing Function, and
        # registry rehydration does the same, so this has to run on those paths too.
        self._framework_params = self._resolve_framework_params()

        if self.skip_entrypoint_processing:
            if strict:
                self.process_schema_for_strict()
            return

        if self.entrypoint is None:
            return

        parameters = {"type": "object", "properties": {}, "required": []}

        params_set_by_user = False
        # If the user set the parameters (i.e. they are different from the default), we should keep them
        if self.parameters != parameters:
            params_set_by_user = True

        if self.requires_user_input:
            self.user_input_schema = self.user_input_schema or []

        try:
            sig = signature(self.entrypoint)
            type_hints = get_type_hints(self.entrypoint)

            # If function has an the agent argument, remove the agent parameter from the type hints
            if "agent" in sig.parameters and "agent" in type_hints:
                del type_hints["agent"]
            if "team" in sig.parameters and "team" in type_hints:
                del type_hints["team"]
            if "run_context" in sig.parameters and "run_context" in type_hints:
                del type_hints["run_context"]
            if "images" in sig.parameters and "images" in type_hints:
                del type_hints["images"]
            if "videos" in sig.parameters and "videos" in type_hints:
                del type_hints["videos"]
            if "audios" in sig.parameters and "audios" in type_hints:
                del type_hints["audios"]
            if "files" in sig.parameters and "files" in type_hints:
                del type_hints["files"]

            # Filter out return type and only process parameters
            excluded_params = ["return", "self", *FRAMEWORK_INJECTED_PARAMS]
            excluded_params.extend(name for name in sig.parameters if name in AGNO_INJECTED_PARAMS)

            # Also exclude parameters whose types are framework-injected,
            # even if the parameter name differs (e.g. my_agent: Agent). See issue #6344.
            try:
                for param_name, hint in list(type_hints.items()):
                    # get_type_hints includes the return annotation under
                    # "return"; it is not an injectable parameter.
                    if param_name == "return":
                        continue
                    if _is_schema_excluded(hint):
                        del type_hints[param_name]
                        excluded_params.append(param_name)
                        if _is_bare_media_typed(hint):
                            _warn_hidden_media(self.name, param_name)
            except Exception:
                pass

            # Snapshot excluded_params before user_input_fields are added,
            # so we can use it to filter user_input_schema later.
            if self.requires_user_input:
                _excluded_framework_params = list(excluded_params)

            if self.requires_user_input and self.user_input_fields:
                if len(self.user_input_fields) == 0:
                    excluded_params.extend(list(type_hints.keys()))
                else:
                    excluded_params.extend(self.user_input_fields)

            # Get filtered list of parameter types
            param_type_hints = {name: type_hints.get(name) for name in sig.parameters if name not in excluded_params}

            # Parse docstring for parameters
            param_descriptions = {}
            param_descriptions_clean = {}
            if docstring := getdoc(self.entrypoint):
                parsed_doc = parse(docstring)
                param_docs = parsed_doc.params

                if param_docs is not None:
                    for param in param_docs:
                        param_name = param.arg_name
                        param_type = param.type_name

                        if param_type:
                            param_descriptions[param_name] = f"({param_type}) {param.description or ''}"
                        else:
                            param_descriptions[param_name] = param.description or ""
                        param_descriptions_clean[param_name] = param.description or ""

            # If the function requires user input, set user_input_schema to all parameters
            # except framework-injected ones (using the snapshot taken before user_input_fields
            # were added to excluded_params, since those should remain in the schema).
            if self.requires_user_input:
                self.user_input_schema = [
                    UserInputField(
                        name=name,
                        description=param_descriptions_clean.get(name),
                        field_type=type_hints.get(name, str),
                    )
                    for name in sig.parameters
                    if name not in _excluded_framework_params
                ]

            # Get JSON schema for parameters only
            parameters = get_json_schema(
                type_hints=param_type_hints, param_descriptions=param_descriptions, strict=strict
            )

            # If strict=True mark all fields as required
            # See: https://platform.openai.com/docs/guides/structured-outputs/supported-schemas#all-fields-must-be-required
            if strict:
                parameters["required"] = [name for name in parameters["properties"] if name not in excluded_params]
            else:
                # Mark a field as required if it has no default value
                parameters["required"] = [
                    name
                    for name, param in sig.parameters.items()
                    if param.default == param.empty and name != "self" and name not in excluded_params
                ]

            # A param whose type has no JSON schema (e.g. `fc: FunctionCall`) is skipped by
            # get_json_schema, so requiring it would describe a property that does not exist.
            parameters["required"] = [name for name in parameters["required"] if name in parameters["properties"]]

            if params_set_by_user:
                self.parameters["additionalProperties"] = False
                # `parameters` is user-supplied here and may omit "properties"; read it
                # defensively so a required-list rebuild degrades to empty rather than
                # raising a KeyError that the broad except would swallow (dropping the
                # description with it).
                user_properties = self.parameters.get("properties") or {}
                if strict:
                    self.parameters["required"] = [name for name in user_properties if name not in excluded_params]
                else:
                    # Mark a field as required if it has no default value
                    self.parameters["required"] = [
                        name
                        for name, param in sig.parameters.items()
                        if param.default == param.empty
                        and name != "self"
                        and name not in excluded_params
                        and name in user_properties
                    ]

            self.description = self.description or get_entrypoint_docstring(self.entrypoint)

            # log_debug(f"JSON schema for {self.name}: {parameters}")
        except Exception as e:
            log_warning(f"Could not parse args for {self.name}: {str(e)}")

        if not params_set_by_user:
            self.parameters = parameters

        if strict:
            self.process_schema_for_strict()

        try:
            self.entrypoint = self._wrap_callable(self.entrypoint)
        except Exception as e:
            log_warning(f"Failed to add validate decorator to entrypoint: {str(e)}")

    @staticmethod
    def _wrap_callable(func: Callable) -> Callable:
        """Wrap a callable with Pydantic's validate_call decorator, if relevant"""
        from inspect import isasyncgenfunction, iscoroutinefunction, signature

        pydantic_version = _get_pydantic_version()

        # Async generators need special handling: validate_call turns an `async def ... yield`
        # into a plain function that returns an async_generator, which makes
        # inspect.isasyncgenfunction return False. Downstream dispatch (models/base.py,
        # FunctionCall.aexecute) uses that predicate to route the call, so we wrap the
        # validated callable in an outer `async def ... yield` shim that preserves the
        # async-generator identity while still coercing arguments through Pydantic.
        if isasyncgenfunction(func):
            if getattr(func, "_wrapped_for_validation", False):
                return func
            validated = validate_call(func, config=dict(arbitrary_types_allowed=True))  # type: ignore

            @wraps(func)
            async def async_gen_wrapper(*args, **kwargs):
                inner = validated(*args, **kwargs)
                try:
                    async for item in inner:
                        yield item
                finally:
                    await inner.aclose()

            async_gen_wrapper._wrapped_for_validation = True  # type: ignore[attr-defined]
            return async_gen_wrapper

        # Don't wrap coroutines with validate_call if pydantic version is less than 2.10.0
        if iscoroutinefunction(func) and pydantic_version < Version("2.10.0"):
            log_debug(
                f"Skipping validate_call for {func.__name__} because pydantic version is less than 2.10.0, please consider upgrading to pydantic 2.10.0 or higher"
            )
            return func

        # Don't wrap callables that are already wrapped with validate_call
        elif getattr(func, "_wrapped_for_validation", False):
            return func

        # Don't wrap functions with framework-injected parameters
        # These parameters (agent, team) are
        # injected by the framework at runtime and shouldn't be validated by Pydantic
        sig = signature(func)
        framework_params = {"agent", "team"}
        if framework_params & set(sig.parameters.keys()):
            return func

        # Also skip validation when a PARAMETER's type is Agent or Team, even
        # if the parameter name differs (e.g. my_agent: Agent) or the annotation
        # is a union (owner: Optional[Agent]).
        # validate_call uses get_type_hints() which fails to resolve types
        # from Agent/Team class hierarchies (like BaseDb) in the user's module globals.
        # The return annotation is not a parameter: validate_call is called
        # without validate_return, so it never introspects one.
        try:
            hints = get_type_hints(func)
            from agno.agent.agent import Agent
            from agno.team.team import Team

            framework_types = (Agent, Team)
            for name, hint in hints.items():
                if name == "return" or name not in sig.parameters:
                    continue
                # The same structural search the schema rule uses. Reading only
                # a bare annotation or a direct union left `Union[str,
                # list[Agent]]` to validate_call, which then failed to resolve
                # Agent's own forward references and took registration of the
                # whole tool down.
                if _annotation_reaches(hint, framework_types):
                    return func
        except Exception:
            pass

        # Wrap the callable with validate_call
        wrapped = validate_call(func, config=dict(arbitrary_types_allowed=True))  # type: ignore
        wrapped._wrapped_for_validation = True  # Mark as wrapped to avoid infinite recursion
        return wrapped

    def process_schema_for_strict(self):
        """Process the schema to make it strict mode compliant."""

        def make_nested_strict(schema):
            """Recursively ensure all object schemas have additionalProperties: false"""
            if not isinstance(schema, dict):
                return schema

            # Make a copy to avoid modifying the original
            result = schema.copy()

            # If this is an object schema, ensure additionalProperties: false
            if result.get("type") == "object" or "properties" in result:
                result["additionalProperties"] = False

            # If schema has no type but has other schema properties, give it a type
            if "type" not in result:
                if "properties" in result:
                    result["type"] = "object"
                    result["additionalProperties"] = False
                elif result.get("title") and not any(
                    key in result for key in ["properties", "items", "anyOf", "oneOf", "allOf", "enum"]
                ):
                    result["type"] = "string"

            # Recursively process nested schemas
            for key, value in result.items():
                if key == "properties" and isinstance(value, dict):
                    result[key] = {k: make_nested_strict(v) for k, v in value.items()}
                elif key == "items" and isinstance(value, dict):
                    # This handles array items like List[KnowledgeFilter]
                    result[key] = make_nested_strict(value)
                elif isinstance(value, dict):
                    result[key] = make_nested_strict(value)

            return result

        # Apply strict mode to the entire schema
        self.parameters = make_nested_strict(self.parameters)

        self.parameters["required"] = [
            name
            for name in self.parameters["properties"]
            if name not in ("return", "self")
            and name not in FRAMEWORK_INJECTED_PARAMS
            and name not in AGNO_INJECTED_PARAMS
        ]

    @staticmethod
    def _get_run_context_identity(entrypoint_args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Stable identity fields a run context contributes to the cache key.

        Both injection channels ("run_context" and "_agno_run_context", the
        latter used by internal wrappers such as the MCP entrypoints)
        contribute the same fields. Only user_id and session_id are
        contributed: run_id stays out so a result cached for a user and session
        is reusable across their runs. Returns None when the entrypoint takes
        no run context, so key composition for run-context-free tools is
        unchanged.

        Only those two fields enter the key. A run context also carries
        metadata, dependencies, session_state and knowledge_filters, and none of
        them scope an entry, so two calls that differ only there share one. A
        tool that reads them, rather than taking the same information as an
        argument the model supplies, is not safely cacheable.

        Reuse across runs holds for the "run_context" spelling alone.
        _get_cache_key removes only FRAMEWORK_INJECTED_PARAMS from the key
        material, so an injected "_agno_run_context" object is also serialized
        into the key with run_id and every other live field. Entries on that
        channel are therefore scoped to one run context, not to a user and
        session, until those channels are removed from the key material too.
        """
        run_context = entrypoint_args.get("run_context") or entrypoint_args.get("_agno_run_context")
        if run_context is None:
            return None
        return {
            "user_id": getattr(run_context, "user_id", None),
            "session_id": getattr(run_context, "session_id", None),
        }

    def _get_cache_key(self, entrypoint_args: Dict[str, Any], call_args: Optional[Dict[str, Any]] = None) -> str:
        """Generate a cache key based on function name, caller identity and arguments."""
        import json
        from hashlib import md5

        identity = self._get_run_context_identity(entrypoint_args)

        copy_entrypoint_args = entrypoint_args.copy()
        # Injected framework objects are not part of a call's identity for caching
        # purposes; a run context contributes the caller's identity below. An
        # injected agent or team contributes none, so a cache_results tool that
        # reads agent.user_id still shares entries across users. Tracked as a
        # follow-up.
        for param_name in FRAMEWORK_INJECTED_PARAMS:
            copy_entrypoint_args.pop(param_name, None)
        # Use json.dumps with sort_keys=True to ensure consistent ordering regardless of dict key order
        args_str = json.dumps(copy_entrypoint_args, sort_keys=True, default=str)

        kwargs_str = str(sorted((call_args or {}).items()))
        if identity is not None:
            # A run context contributes the caller's identity instead of being
            # dropped: results cached for one user or session must never be
            # served to another.
            identity_str = json.dumps(identity, sort_keys=True, default=str)
            key_str = f"{self.name}:{identity_str}:{args_str}:{kwargs_str}"
        else:
            key_str = f"{self.name}:{args_str}:{kwargs_str}"
        return md5(key_str.encode()).hexdigest()

    def _get_cache_file_path(self, cache_key: str) -> str:
        """Get the full path for the cache file."""
        from pathlib import Path
        from tempfile import gettempdir

        base_cache_dir = self.cache_dir or Path(gettempdir()) / "agno_cache"
        # The version names the directory, not just the payload. A stored value
        # means different things to different versions of this code, and a
        # reader that predates a change would otherwise find an entry it cannot
        # read correctly and would have no way to tell.
        func_cache_dir = Path(base_cache_dir) / "functions" / f"v{CACHE_FORMAT}" / self.name
        _make_private_dir(func_cache_dir)
        return str(func_cache_dir / f"{cache_key}.json")

    def _get_cached_result(self, cache_file: str) -> Optional[Any]:
        """Retrieve cached result if valid."""
        import json
        import os
        from pathlib import Path
        from time import time

        cache_path = Path(cache_file)
        if not cache_path.exists():
            return None

        try:
            # Never follow a link out of the cache directory. The path is
            # predictable, so a symlink planted there would otherwise choose
            # the file a cache hit reads.
            fd = os.open(cache_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                entry_id = os.fstat(f.fileno()).st_ino
                cache_data = json.load(f)

            timestamp = cache_data.get("timestamp", 0)

            if time() - timestamp <= self.cache_ttl:
                try:
                    if cache_data.get("cache_format") != CACHE_FORMAT:
                        raise _StaleCacheEntry("the entry was written in an earlier cache format")
                    return self._cached_value(cache_data.get("result"), cache_data.get("result_type"))
                except _StaleCacheEntry as e:
                    log_debug(f"Discarding the cache entry for {self.name}: {e}")

            # Remove the entry that was read, not whatever stands at that
            # name now: a writer replaces the file whole, and unlinking by name
            # alone would throw away an entry written since the read.
            if cache_path.stat().st_ino == entry_id:
                cache_path.unlink()
        except Exception:
            log_exception("Error reading cache")

        return None

    def _survives_the_cache(self, cache_data: Dict[str, Any], result: Any) -> bool:
        """Whether reading this entry back gives what the tool just returned."""
        try:
            return _faithful(result, self._cached_value(cache_data.get("result"), cache_data.get("result_type")))
        except Exception:
            return False

    def _cached_value(self, payload: Any, result_type: Optional[str]) -> Any:
        """The cached payload as the type the entrypoint declares it returns.

        The class comes from the code's return annotation, never from the cache
        file, so an entry cannot choose which class gets built. Raises
        _StaleCacheEntry when the payload no longer matches what the code
        returns, so the caller re-executes rather than hand back a value of the
        wrong shape.
        """
        value = payload
        return_type = self._declared_return_type()

        if return_type is not None and _mentions_base_model(return_type):
            try:
                adapter = _return_type_adapter(return_type)
            except TypeError:  # an annotation that cannot be memoised
                adapter = None
            if adapter is not None:
                try:
                    value = _validate_by_field_name(adapter, payload)
                except Exception as e:
                    raise _StaleCacheEntry(f"the payload no longer rebuilds into {return_type}: {e}")
                if isinstance(value, BaseModel) and _dump_for_cache(value) != payload:
                    raise _StaleCacheEntry(
                        f"{return_type} cannot hold everything the entry carries, so the entry no longer stands "
                        "for what the tool returns"
                    )
        elif result_type == "ToolResult":
            if return_type is not None:
                raise _StaleCacheEntry(f"the entry holds a ToolResult but the tool returns {return_type}")
            # Nothing in the code says what this tool returns, so the entry's
            # own tag is the only thing left to go on.
            try:
                value = ToolResult.model_validate(payload)
            except Exception as e:
                raise _StaleCacheEntry(f"the payload is not a valid ToolResult: {e}")

        if _carries_media(value):
            # Media is never written to the cache, so an entry carrying it did
            # not come from here. Rebuilding it would hand the model media that
            # a cache file chose.
            raise _StaleCacheEntry("a cached result must not carry media")

        return value

    def _declared_return_type(self) -> Any:
        """The entrypoint's return annotation, or None when it declares none."""
        if self.entrypoint is None:
            return None
        try:
            hint = get_type_hints(self.entrypoint).get("return")
        except Exception:
            return None
        if hint is None or hint is type(None):
            return None
        return _unwrap_annotation(hint)

    def _save_to_cache(self, cache_file: str, result: Any):
        """Save result to cache."""
        import json
        import os
        from tempfile import mkstemp
        from time import time

        try:
            cache_data: Dict[str, Any] = {"timestamp": time(), "cache_format": CACHE_FORMAT}
            if _carries_media(result):
                # The cache holds JSON, and it excludes media by design: media
                # is forwarded from the live result rather than rebuilt from a
                # file. Skipping the write keeps the media intact on every call
                # at the cost of re-executing.
                log_debug(f"Skipping cache for {self.name}: a result carrying media is not cacheable")
                return
            if isinstance(result, ToolResult):
                # Tag the entry so a cache hit restores a ToolResult instead of
                # handing the model loop a plain dict.
                cache_data["result"] = result.model_dump()
                cache_data["result_type"] = "ToolResult"
            elif isinstance(result, BaseModel):
                cache_data["result"] = result.model_dump()
            else:
                cache_data["result"] = result
            # Serialize before writing anything: a result that cannot be
            # encoded must leave no half-written file for the next call to read.
            payload = json.dumps(cache_data)
            checks_round_trip = bool(self.tool_hooks) or self._declared_return_type() is not None
            if checks_round_trip and not self._survives_the_cache(json.loads(payload), result):
                # A hit hands this value back in the tool's place, so what
                # comes back has to be what the tool returned: a tuple comes
                # back a list, and a union picks its first matching member
                # rather than the one the tool chose. A tool that says nothing
                # about what it returns, and has no hooks to read it, keeps the
                # older behaviour of handing the model whatever was stored.
                log_debug(f"Skipping cache for {self.name}: the result does not survive being stored")
                return
            # Write a new file and move it into place. The cache path is
            # predictable and the default directory is shared, so writing
            # through the target would follow a symlink someone else planted
            # and would keep whatever mode that file already had. mkstemp
            # creates with 0600, and the rename is atomic, so a reader sees
            # either the previous entry or this one.
            fd, tmp_path = mkstemp(dir=os.path.dirname(cache_file), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp_path, cache_file)
            except Exception:
                os.unlink(tmp_path)
                raise
        except Exception:
            log_exception("Error writing cache")


class FunctionExecutionResult(BaseModel):
    status: Literal["success", "failure"]
    result: Optional[Any] = None
    error: Optional[str] = None

    updated_session_state: Optional[Dict[str, Any]] = None

    # New fields for media artifacts
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audios: Optional[List[Audio]] = None
    files: Optional[List[File]] = None


class FunctionCall(BaseModel):
    """Model for Function Calls"""

    # The function to be called.
    function: Function
    # The arguments to call the function with.
    arguments: Optional[Dict[str, Any]] = None
    # The result of the function call.
    result: Optional[Any] = None
    # The ID of the function call.
    call_id: Optional[str] = None

    # Error while parsing arguments or running the function.
    error: Optional[str] = None

    def get_call_str(self) -> str:
        """Returns a string representation of the function call."""
        import shutil

        # Get terminal width, default to 80 if it can't be determined
        term_width = shutil.get_terminal_size().columns or 80
        max_arg_len = max(20, (term_width - len(self.function.name) - 4) // 2)

        if self.arguments is None:
            return f"{self.function.name}()"

        trimmed_arguments = {}
        for k, v in self.arguments.items():
            if isinstance(v, str) and len(str(v)) > max_arg_len:
                trimmed_arguments[k] = "..."
            else:
                trimmed_arguments[k] = v

        call_str = f"{self.function.name}({', '.join([f'{k}={v}' for k, v in trimmed_arguments.items()])})"

        # If call string is too long, truncate arguments
        if len(call_str) > term_width:
            return f"{self.function.name}(...)"

        return call_str

    def _safe_hook_call(self, hook: Callable, hook_args: Dict[str, Any]) -> Any:
        """Call a hook with list-structure-safe messages.

        Temporarily replaces run_context.messages with a shallow copy so the
        hook cannot corrupt the live message list (e.g. .clear(), .append()).
        Individual Message objects are still shared references — this protects
        list structure only, not message contents. The live reference is
        restored after the hook returns (or raises).
        """
        rc = self.function._run_context
        if rc is not None and rc.messages is not None:
            live_ref = rc.messages
            rc.messages = list(live_ref)
            try:
                return hook(**hook_args)
            finally:
                rc.messages = live_ref
        else:
            return hook(**hook_args)

    async def _safe_hook_call_async(self, hook: Callable, hook_args: Dict[str, Any]) -> Any:
        """Async variant of _safe_hook_call."""
        rc = self.function._run_context
        if rc is not None and rc.messages is not None:
            live_ref = rc.messages
            rc.messages = list(live_ref)
            try:
                return await hook(**hook_args)
            finally:
                rc.messages = live_ref
        else:
            return await hook(**hook_args)

    def _handle_pre_hook(self):
        """Handles the pre-hook for the function call."""
        if self.function.pre_hook is not None:
            try:
                from inspect import signature

                pre_hook_args = {}
                # Check if the pre-hook has an agent argument
                if "agent" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["agent"] = self.function._agent
                # Check if the pre-hook has a team argument
                if "team" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["team"] = self.function._team
                # Check if the pre-hook has a run_context argument
                if "run_context" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["run_context"] = self.function._run_context
                # Check if the pre-hook has an fc argument
                if "fc" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["fc"] = self
                self._safe_hook_call(self.function.pre_hook, pre_hook_args)
            except AgentRunException as e:
                log_debug(f"{e.__class__.__name__}: {e}")
                self.error = str(e)
                raise
            except RunCancelledException:
                raise
            except Exception as e:
                log_warning(f"Error in pre-hook callback: {str(e)}")
                log_exception(e)

    def _handle_post_hook(self):
        """Handles the post-hook for the function call."""
        if self.function.post_hook is not None:
            try:
                from inspect import signature

                post_hook_args = {}
                # Check if the post-hook has an agent argument
                if "agent" in signature(self.function.post_hook).parameters:
                    post_hook_args["agent"] = self.function._agent
                # Check if the post-hook has a team argument
                if "team" in signature(self.function.post_hook).parameters:
                    post_hook_args["team"] = self.function._team
                # Check if the post-hook has a run_context argument
                if "run_context" in signature(self.function.post_hook).parameters:
                    post_hook_args["run_context"] = self.function._run_context
                # Check if the post-hook has an fc argument
                if "fc" in signature(self.function.post_hook).parameters:
                    post_hook_args["fc"] = self
                self._safe_hook_call(self.function.post_hook, post_hook_args)
            except AgentRunException as e:
                log_debug(f"{e.__class__.__name__}: {e}")
                self.error = str(e)
                raise
            except RunCancelledException:
                raise
            except Exception as e:
                log_warning(f"Error in post-hook callback: {str(e)}")
                log_exception(e)

    def _build_entrypoint_args(self) -> Dict[str, Any]:
        """Builds the arguments for the entrypoint."""
        from inspect import signature

        sig = signature(self.function.entrypoint)  # type: ignore
        entrypoint_args = {}

        # Check if the entrypoint has an agent argument (by name)
        if "agent" in sig.parameters:
            entrypoint_args["agent"] = self.function._agent
        # Check if the entrypoint has a team argument (by name)
        if "team" in sig.parameters:
            entrypoint_args["team"] = self.function._team
        # Check if the entrypoint has a run_context argument
        if "run_context" in sig.parameters:
            entrypoint_args["run_context"] = self.function._run_context
        # Check if the entrypoint has an fc argument
        if "fc" in sig.parameters:
            entrypoint_args["fc"] = self

        # `_agno_`-prefixed variants are used by internal wrappers so framework
        # objects can be injected without colliding with user-facing tool
        # arguments that happen to be named "agent", "team" and "run_context".
        if "_agno_agent" in sig.parameters:
            entrypoint_args["_agno_agent"] = self.function._agent
        if "_agno_team" in sig.parameters:
            entrypoint_args["_agno_team"] = self.function._team
        if "_agno_run_context" in sig.parameters:
            entrypoint_args["_agno_run_context"] = self.function._run_context

        # Check if the entrypoint has media arguments
        if "images" in sig.parameters:
            entrypoint_args["images"] = self.function._images
        if "videos" in sig.parameters:
            entrypoint_args["videos"] = self.function._videos
        if "audios" in sig.parameters:
            entrypoint_args["audios"] = self.function._audios
        if "files" in sig.parameters:
            entrypoint_args["files"] = self.function._files

        # Also inject the identity objects based on TYPE, not just name, for
        # cases like `my_agent: Agent`, `custom_team: Team` or `ctx: RunContext`.
        # See issue #6344.
        #
        # Every identity annotation _is_framework_typed hides from the model-facing
        # schema is bound here, union spellings included (owner: Optional[Agent],
        # ctx: Union[str, RunContext]). A wielder without the object binds None --
        # a tool registered on a Team has no Agent, and a required `owner: Agent`
        # must not raise a missing-argument error the model can neither see nor
        # fix -- except when the parameter carries its own default, which then
        # stands (an explicit None would stomp it, and validate_call rejects an
        # explicit None for a bare non-Optional annotation). Bare media
        # annotations are hidden too but never filled by type: media arrives
        # through the reserved names alone (images/videos/audios/files).
        try:
            from inspect import Parameter

            from agno.agent.agent import Agent
            from agno.team.team import Team

            hints = get_type_hints(self.function.entrypoint)  # type: ignore
            for param_name, hint in hints.items():
                # get_type_hints reports the return annotation under "return"; it is
                # not a parameter, and passing it as a keyword would raise.
                if param_name not in sig.parameters or param_name in entrypoint_args:
                    continue  # Not a parameter, or already handled by name-based injection
                param = sig.parameters[param_name]
                # A variadic parameter can never take a keyword bind (*rest: Agent
                # binds rest=() by itself; **extra: RunContext binds {}), and a
                # positional-only one cannot be passed by name either.
                if param.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD, Parameter.POSITIONAL_ONLY):
                    continue
                if not _is_framework_typed(hint):
                    continue
                hint = _unwrap_annotation(hint)
                # The same resolver that decided to hide it. Matching only a
                # bare type or a direct union left the shapes the schema rule
                # newly recognised -- a TypeVar bound to RunContext, an aliased
                # or wrapped one -- hidden from the model AND never injected,
                # so the tool failed on a missing argument every call.
                matches = [
                    injected
                    for wanted, injected in (
                        ((Agent,), self.function._agent),
                        ((Team,), self.function._team),
                        ((RunContext,), self.function._run_context),
                    )
                    if _annotation_binds(hint, wanted)
                ]
                if not matches:
                    continue
                # Take the first type the framework can actually supply, not the first
                # one the annotation mentions: `Union[Agent, Team]` on a team names
                # Agent first, and stopping there would leave it unfilled.
                injected = next((m for m in matches if m is not None), None)
                if injected is not None or param.default is Parameter.empty:
                    entrypoint_args[param_name] = injected
        except Exception:
            pass

        return entrypoint_args

    def _identity_owned_params(self) -> Set[str]:
        """Parameter names whose value the model may never choose.

        The reserved identity names, plus every name the framework claimed by
        ANNOTATION. Both paths that populate ``_framework_params``
        (``Function._resolve_framework_params`` and ``from_callable``) add a
        typed parameter only when ``_is_framework_typed`` says it is
        identity-bearing, never for media, so anything there that is not a
        reserved name got there by being identity-typed.

        Media is deliberately not included: it is injected by reserved name
        alone, so a schema that declares ``images`` is the only way such a
        parameter can be filled at all."""
        typed = set(self.function._framework_params or ()) - set(FRAMEWORK_INJECTED_PARAMS) - {"return", "self"}
        return set(IDENTITY_INJECTED_PARAMS) | typed

    def _drop_injected_overrides(self, entrypoint_args: Dict[str, Any]) -> None:
        """Drop tool-call arguments that collide with framework-injected parameters.

        A parameter the framework owns and keeps out of the model-facing schema
        (run_context, agent, team, media, the `_agno_` channels, and params
        excluded by type annotation such as ``ctx: RunContext``) can never
        legitimately be model-supplied -- at worst the value is an attempt to
        override the caller's identity on an identity-threading tool. Without
        this, the tool-hooks execution chain merges model arguments over the
        injected ones. The call runs with the injected object, with the
        parameter's own default when the wielder has no such object, or with
        an explicit None when it has neither.

        A name that does appear in the tool's schema is left alone: an MCP
        server is free to expose an argument called "files", and the schema is
        what says so. Identity is the exception -- no schema can hand the model
        a say over whose data a tool reads -- and identity is decided by the
        annotation as well as the name, so ``ctx: RunContext`` is as protected
        as ``run_context`` is.
        """
        if not self.arguments:
            return
        # A tool's schema is not always framework-built: an MCP server can hand over an
        # arbitrary (even JSON-Schema-invalid) parameters dict verbatim. Coerce a
        # non-dict `properties` to empty so the membership/`set()` uses below cannot
        # raise -- this method runs before execute()'s try block, so a raise here would
        # abort the whole run instead of failing just the tool call.
        schema_properties = (self.function.parameters or {}).get("properties")
        if not isinstance(schema_properties, dict):
            schema_properties = {}
        # A name is framework-owned if this entrypoint declares it as one, or if we injected
        # it. Being in the schema releases it back to the model, except for identity.
        reserved = set(self.function._framework_params or ()) | set(entrypoint_args)
        identity_owned = self._identity_owned_params()
        dropped = {
            key
            for key in self.arguments
            if key in AGNO_INJECTED_PARAMS
            or (key in reserved and (key not in schema_properties or key in identity_owned))
        }
        if dropped:
            # The pre-drop dict is already referenced by the ToolExecution emitted on
            # tool_call_started, which keeps what the model sent; a new dict leaves it intact.
            self.arguments = {key: value for key, value in self.arguments.items() if key not in dropped}
            log_warning(
                f"{self.function.name}: ignored tool-call arguments that name framework-injected "
                f"parameters: {sorted(dropped)}"
            )

        # A name the schema does declare belongs to the model. Withdraw the injected value
        # so the no-hooks call does not receive that parameter twice.
        for key in set(self.arguments) & set(entrypoint_args) & set(schema_properties):
            del entrypoint_args[key]

    def _build_hook_args(self, hook: Callable, name: str, func: Callable, args: Dict[str, Any]) -> Dict[str, Any]:
        """Build the arguments for the hook."""
        from inspect import signature

        hook_args = {}
        # Check if the hook has an agent argument
        if "agent" in signature(hook).parameters:
            hook_args["agent"] = self.function._agent
        # Check if the hook has a team argument
        if "team" in signature(hook).parameters:
            hook_args["team"] = self.function._team
        # Check if the hook has a run_context argument
        if "run_context" in signature(hook).parameters:
            hook_args["run_context"] = self.function._run_context
        if "name" in signature(hook).parameters:
            hook_args["name"] = name
        if "function_name" in signature(hook).parameters:
            hook_args["function_name"] = name
        if "function" in signature(hook).parameters:
            hook_args["function"] = func
        if "func" in signature(hook).parameters:
            hook_args["func"] = func
        if "function_call" in signature(hook).parameters:
            hook_args["function_call"] = func
        if "args" in signature(hook).parameters:
            hook_args["args"] = args
        if "arguments" in signature(hook).parameters:
            hook_args["arguments"] = args
        return hook_args

    def _build_nested_execution_chain(
        self,
        entrypoint_args: Dict[str, Any],
        cached_result: Optional[Any] = None,
        raw_results: Optional[List[Any]] = None,
        cache_key: Optional[str] = None,
    ):
        """Build a nested chain of hook executions with the entrypoint at the center.

        This creates a chain where each hook wraps the next one, with the function call
        at the innermost level. Returns bubble back up through each hook.

        On a cache hit, cached_result stands in for the entrypoint call only
        while the call still asks what the key names: a hook may rewrite an
        argument before the entrypoint is reached, and the stored value answers
        the earlier question. When that happens the tool runs for real, so the
        hooks run over the value the entrypoint gave them on the miss and what
        the caller gets back is what the miss produced. Entrypoint returns are
        recorded in raw_results, detached so a hook that edits one in place
        cannot reach the copy the cache keeps, and the caller stores that value
        rather than the chain's: the hooks run again on a hit, and storing their
        output would apply a result-transforming hook twice.
        """
        from functools import reduce
        from inspect import iscoroutinefunction

        def execute_entrypoint(name, func, args):
            """Execute the entrypoint function."""
            if cached_result is not None and not self._moved_its_key(cache_key, entrypoint_args):
                return _detached(cached_result)
            arguments = entrypoint_args.copy()
            if self.arguments is not None:
                arguments.update(self.arguments)
            slot = _start_entrypoint_call(raw_results) if raw_results is not None else -1
            result = self.function.entrypoint(**arguments)  # type: ignore
            if raw_results is not None:
                _record_entrypoint_result(raw_results, slot, result)
            return result

        # If no hooks, just return the entrypoint execution function
        if not self.function.tool_hooks:
            return execute_entrypoint

        def create_hook_wrapper(inner_func, hook):
            """Create a nested wrapper for the hook."""

            def wrapper(name, func, args):
                # Pass the inner function as next_func to the hook
                # The hook will call next_func to continue the chain
                def next_func(**kwargs):
                    return inner_func(name, func, kwargs)

                hook_args = self._build_hook_args(hook, name, next_func, args)

                return self._safe_hook_call(hook, hook_args)

            return wrapper

        # Remove coroutine hooks
        final_hooks = []
        for hook in self.function.tool_hooks:
            if iscoroutinefunction(hook):
                log_warning(f"Cannot use async hooks with sync function calls. Skipping hook: {hook.__name__}")
            else:
                final_hooks.append(hook)

        # Build the chain from inside out - reverse the hooks to start from the innermost
        hooks = list(reversed(final_hooks))
        chain = reduce(create_hook_wrapper, hooks, execute_entrypoint)
        return chain

    def _moved_its_key(self, cache_key: Optional[str], entrypoint_args: Dict[str, Any]) -> bool:
        """Whether anything the key is built from changed since the lookup.

        Hooks hold the live arguments and the run context, so by the time the
        entrypoint is reached the call may be asking something other than what
        the key names. Such a call is neither answered from the entry under
        that key nor stored under it.
        """
        if cache_key is None:
            return False
        return self.function._get_cache_key(entrypoint_args, self.arguments) != cache_key

    def _save_entrypoint_result(
        self, cache_key: str, cache_file: str, entrypoint_args: Dict[str, Any], raw_results: List[Any]
    ) -> None:
        """Store what the entrypoint returned, so a hit replays the hooks over
        the same value the miss handed them.

        A chain that called the entrypoint anything but once leaves no such
        value: a hook that retried produced several and a hook that answered by
        itself produced none, and replaying over either would not reproduce the
        miss. Those calls stay uncached.

        The caller passes the key and file the lookup used. The tool and its
        hooks can reach the run context and the arguments the key is built
        from, and a hook that rewrites an argument in place changes what the
        tool was actually asked. Storing under the key the lookup used would
        then answer a later call from a different question, and storing under a
        key worked out afterwards would file the result under whatever the call
        left behind. Neither is safe, so a call that moved its own key is not
        cached at all.
        """
        from inspect import isasyncgen, isgenerator

        if self.function.tool_hooks is not None:
            if len(raw_results) != 1:
                log_debug(
                    f"Skipping cache for {self.function.name}: its hooks ran the tool "
                    f"{len(raw_results)} times, so no single result stands for the call"
                )
                return
            result_to_cache = raw_results[0]
            if result_to_cache is _NO_RESULT:
                return
        else:
            result_to_cache = self.result

        if isgenerator(result_to_cache) or isasyncgen(result_to_cache):
            return

        if self._moved_its_key(cache_key, entrypoint_args):
            log_debug(
                f"Skipping cache for {self.function.name}: the call changed what it was asked, "
                "so the result does not answer the question the key names"
            )
            return

        self.function._save_to_cache(cache_file, result_to_cache)

    def execute(self) -> FunctionExecutionResult:
        """Runs the function call."""
        from inspect import isgenerator, isgeneratorfunction

        if self.function.entrypoint is None:
            return FunctionExecutionResult(status="failure", error="Entrypoint is not set")

        log_debug(f"Running: {self.get_call_str()}")

        entrypoint_args = self._build_entrypoint_args()
        # Sanitize before any hook runs, so a hook used as an authorization gate cannot
        # read an identity the call will not actually execute with.
        self._drop_injected_overrides(entrypoint_args)

        # Execute pre-hook if it exists
        self._handle_pre_hook()

        # Check cache if enabled and not a generator function
        cached_result = None
        cacheable = self.function.cache_results and not isgeneratorfunction(self.function.entrypoint)
        if cacheable and _has_injected_media(entrypoint_args):
            log_debug(f"Skipping cache for {self.function.name}: the call carries attached media")
            cacheable = False
        if cacheable:
            try:
                cache_key = self.function._get_cache_key(entrypoint_args, self.arguments)
                cache_file = self.function._get_cache_file_path(cache_key)
                cached_result = self.function._get_cached_result(cache_file)
                if cached_result is not None:
                    log_debug(f"Cache hit for: {self.get_call_str()}")
            except Exception:
                # An unusable cache directory must cost the tool its caching,
                # not the run.
                log_exception("Error reading cache")
                cacheable = False
        # A cache hit still runs tool_hooks and post_hook, so audit hooks see
        # every tool call.
        from_cache = cached_result is not None

        # Execute function
        execution_result: FunctionExecutionResult
        exception_to_raise = None

        raw_results: List[Any] = []
        try:
            # Build and execute the nested chain of hooks
            if self.function.tool_hooks is not None:
                execution_chain = self._build_nested_execution_chain(
                    entrypoint_args=entrypoint_args,
                    cached_result=cached_result,
                    raw_results=raw_results if cacheable else None,
                    cache_key=cache_key if cacheable else None,
                )
                result = execution_chain(self.function.name, self.function.entrypoint, self.arguments or {})
            elif from_cache:
                result = cached_result
            else:
                if self.arguments is None or self.arguments == {}:
                    result = self.function.entrypoint(**entrypoint_args)
                else:
                    result = self.function.entrypoint(**entrypoint_args, **self.arguments)

            # Handle generator case
            if isgenerator(result):
                self.result = result  # Store generator directly, can't cache
                # For generators, don't capture updated_session_state yet -
                # session_state is passed by reference, so mutations made during
                # generator iteration are already reflected in the original dict.
                # Returning None prevents stale state from being merged later.
                execution_result = FunctionExecutionResult(
                    status="success", result=self.result, updated_session_state=None
                )
            else:
                self.result = result
                # Only cache non-generator results, and never re-save a result
                # that was just served from cache
                if cacheable and not from_cache:
                    self._save_entrypoint_result(cache_key, cache_file, entrypoint_args, raw_results)

                updated_session_state = None
                run_context = entrypoint_args.get("run_context") or entrypoint_args.get("_agno_run_context")
                if run_context is not None:
                    session_state = getattr(run_context, "session_state", None)
                    updated_session_state = session_state if isinstance(session_state, dict) else None

                execution_result = FunctionExecutionResult(
                    status="success", result=self.result, updated_session_state=updated_session_state
                )

        except AgentRunException as e:
            log_debug(f"{e.__class__.__name__}: {e}")
            self.error = str(e)
            exception_to_raise = e
            execution_result = FunctionExecutionResult(status="failure", error=str(e))
        except RunCancelledException:
            raise
        except Exception as e:
            log_warning(f"Could not run function {self.get_call_str()}: {str(e)}")
            log_exception(e)
            self.error = str(e)
            execution_result = FunctionExecutionResult(status="failure", error=str(e))

        finally:
            self._handle_post_hook()

        if exception_to_raise is not None:
            raise exception_to_raise

        return execution_result

    async def _handle_pre_hook_async(self):
        """Handles the async pre-hook for the function call."""
        if self.function.pre_hook is not None:
            try:
                from inspect import signature

                pre_hook_args = {}
                # Check if the pre-hook has an agent argument
                if "agent" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["agent"] = self.function._agent
                # Check if the pre-hook has a team argument
                if "team" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["team"] = self.function._team
                # Check if the pre-hook has a run_context argument
                if "run_context" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["run_context"] = self.function._run_context
                # Check if the pre-hook has an fc argument
                if "fc" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["fc"] = self

                await self._safe_hook_call_async(self.function.pre_hook, pre_hook_args)
            except AgentRunException as e:
                log_debug(f"{e.__class__.__name__}: {e}")
                self.error = str(e)
                raise
            except RunCancelledException:
                raise
            except Exception as e:
                log_warning(f"Error in pre-hook callback: {str(e)}")
                log_exception(e)

    async def _handle_post_hook_async(self):
        """Handles the async post-hook for the function call."""
        if self.function.post_hook is not None:
            try:
                from inspect import signature

                post_hook_args = {}
                # Check if the post-hook has an agent argument
                if "agent" in signature(self.function.post_hook).parameters:
                    post_hook_args["agent"] = self.function._agent
                # Check if the post-hook has a team argument
                if "team" in signature(self.function.post_hook).parameters:
                    post_hook_args["team"] = self.function._team
                # Check if the post-hook has a run_context argument
                if "run_context" in signature(self.function.post_hook).parameters:
                    post_hook_args["run_context"] = self.function._run_context
                # Check if the post-hook has an fc argument
                if "fc" in signature(self.function.post_hook).parameters:
                    post_hook_args["fc"] = self

                await self._safe_hook_call_async(self.function.post_hook, post_hook_args)
            except AgentRunException as e:
                log_debug(f"{e.__class__.__name__}: {e}")
                self.error = str(e)
                raise
            except RunCancelledException:
                raise
            except Exception as e:
                log_warning(f"Error in post-hook callback: {str(e)}")
                log_exception(e)

    async def _build_nested_execution_chain_async(
        self,
        entrypoint_args: Dict[str, Any],
        cached_result: Optional[Any] = None,
        raw_results: Optional[List[Any]] = None,
        cache_key: Optional[str] = None,
    ):
        """Build a nested chain of async hook executions with the entrypoint at the center.

        Similar to _build_nested_execution_chain but for async execution, and
        with the same treatment of cached_result and raw_results.
        """
        from functools import reduce
        from inspect import isasyncgenfunction, iscoroutinefunction

        async def execute_entrypoint_async(name, func, args):
            """Execute the entrypoint function asynchronously."""
            if cached_result is not None and not self._moved_its_key(cache_key, entrypoint_args):
                return _detached(cached_result)
            arguments = entrypoint_args.copy()
            if self.arguments is not None:
                arguments.update(self.arguments)

            slot = _start_entrypoint_call(raw_results) if raw_results is not None else -1
            result = self.function.entrypoint(**arguments)  # type: ignore
            if iscoroutinefunction(self.function.entrypoint) and not isasyncgenfunction(self.function.entrypoint):
                result = await result
            if raw_results is not None:
                _record_entrypoint_result(raw_results, slot, result)
            return result

        def execute_entrypoint(name, func, args):
            """Execute the entrypoint function synchronously."""
            if cached_result is not None and not self._moved_its_key(cache_key, entrypoint_args):
                return _detached(cached_result)
            arguments = entrypoint_args.copy()
            if self.arguments is not None:
                arguments.update(self.arguments)
            slot = _start_entrypoint_call(raw_results) if raw_results is not None else -1
            result = self.function.entrypoint(**arguments)  # type: ignore
            if raw_results is not None:
                _record_entrypoint_result(raw_results, slot, result)
            return result

        # If no hooks, just return the async entrypoint execution function
        if not self.function.tool_hooks:
            return execute_entrypoint_async

        def create_hook_wrapper(inner_func, hook):
            """Create a nested wrapper for the hook."""

            async def wrapper(name, func, args):
                """Create a nested wrapper for the hook."""

                # Pass the inner function as next_func to the hook
                # The hook will call next_func to continue the chain
                async def next_func(**kwargs):
                    if iscoroutinefunction(inner_func):
                        return await inner_func(name, func, kwargs)
                    else:
                        return inner_func(name, func, kwargs)

                hook_args = self._build_hook_args(hook, name, next_func, args)

                if iscoroutinefunction(hook):
                    return await self._safe_hook_call_async(hook, hook_args)
                else:
                    return self._safe_hook_call(hook, hook_args)

            return wrapper

        # Build the chain from inside out - reverse the hooks to start from the innermost
        hooks = list(reversed(self.function.tool_hooks))

        # Handle async and sync entrypoints
        if iscoroutinefunction(self.function.entrypoint):
            chain = reduce(create_hook_wrapper, hooks, execute_entrypoint_async)
        else:
            chain = reduce(create_hook_wrapper, hooks, execute_entrypoint)
        return chain

    async def aexecute(self) -> FunctionExecutionResult:
        """Runs the function call asynchronously."""
        from inspect import isasyncgen, isasyncgenfunction, iscoroutinefunction, isgenerator, isgeneratorfunction

        if self.function.entrypoint is None:
            return FunctionExecutionResult(status="failure", error="Entrypoint is not set")

        log_debug(f"Running: {self.get_call_str()}")

        entrypoint_args = self._build_entrypoint_args()
        # Sanitize before any hook runs, so a hook used as an authorization gate cannot
        # read an identity the call will not actually execute with.
        self._drop_injected_overrides(entrypoint_args)

        # Execute pre-hook if it exists
        if iscoroutinefunction(self.function.pre_hook):
            await self._handle_pre_hook_async()
        else:
            self._handle_pre_hook()

        # Check cache if enabled and not a generator function
        cached_result = None
        cacheable = self.function.cache_results and not (
            isasyncgenfunction(self.function.entrypoint) or isgeneratorfunction(self.function.entrypoint)
        )
        if cacheable and _has_injected_media(entrypoint_args):
            log_debug(f"Skipping cache for {self.function.name}: the call carries attached media")
            cacheable = False
        if cacheable:
            try:
                cache_key = self.function._get_cache_key(entrypoint_args, self.arguments)
                cache_file = self.function._get_cache_file_path(cache_key)
                cached_result = self.function._get_cached_result(cache_file)
                if cached_result is not None:
                    log_debug(f"Cache hit for: {self.get_call_str()}")
            except Exception:
                # An unusable cache directory must cost the tool its caching,
                # not the run.
                log_exception("Error reading cache")
                cacheable = False
        # A cache hit still runs tool_hooks and post_hook, so audit hooks see
        # every tool call.
        from_cache = cached_result is not None

        # Execute function
        execution_result: FunctionExecutionResult
        exception_to_raise = None

        raw_results: List[Any] = []
        try:
            # Build and execute the nested chain of hooks
            if self.function.tool_hooks is not None:
                execution_chain = await self._build_nested_execution_chain_async(
                    entrypoint_args,
                    cached_result=cached_result,
                    raw_results=raw_results if cacheable else None,
                    cache_key=cache_key if cacheable else None,
                )
                self.result = await execution_chain(self.function.name, self.function.entrypoint, self.arguments or {})
            elif from_cache:
                self.result = cached_result
            else:
                if self.arguments is None or self.arguments == {}:
                    result = self.function.entrypoint(**entrypoint_args)
                else:
                    result = self.function.entrypoint(**entrypoint_args, **self.arguments)

                # Handle both sync and async entrypoints
                if isasyncgenfunction(self.function.entrypoint):
                    self.result = result  # Store async generator directly
                elif iscoroutinefunction(self.function.entrypoint):
                    self.result = await result  # Await coroutine result
                elif isgeneratorfunction(self.function.entrypoint):
                    self.result = result  # Store sync generator directly
                else:
                    self.result = result  # Sync function, result is already computed

            # Only cache if not a generator, and never re-save a result that
            # was just served from cache
            if cacheable and not from_cache:
                self._save_entrypoint_result(cache_key, cache_file, entrypoint_args, raw_results)

            # For generators, don't capture updated_session_state -
            # session_state is passed by reference, so mutations made during
            # generator iteration are already reflected in the original dict.
            # Returning None prevents stale state from being merged later.
            if isgenerator(self.result) or isasyncgen(self.result):
                updated_session_state = None
            else:
                updated_session_state = None
                run_context = entrypoint_args.get("run_context") or entrypoint_args.get("_agno_run_context")
                if run_context is not None:
                    session_state = getattr(run_context, "session_state", None)
                    updated_session_state = session_state if isinstance(session_state, dict) else None

            execution_result = FunctionExecutionResult(
                status="success", result=self.result, updated_session_state=updated_session_state
            )

        except AgentRunException as e:
            log_debug(f"{e.__class__.__name__}: {e}")
            self.error = str(e)
            exception_to_raise = e
            execution_result = FunctionExecutionResult(status="failure", error=str(e))
        except RunCancelledException:
            raise
        except Exception as e:
            log_warning(f"Could not run function {self.get_call_str()}: {str(e)}")
            log_exception(e)
            self.error = str(e)
            execution_result = FunctionExecutionResult(status="failure", error=str(e))

        finally:
            if iscoroutinefunction(self.function.post_hook):
                await self._handle_post_hook_async()
            else:
                self._handle_post_hook()

        if exception_to_raise is not None:
            raise exception_to_raise

        return execution_result


class ToolResult(BaseModel):
    """Result from a tool that can include media artifacts."""

    content: str
    # Holds extra MCP tool data, stored as "meta" and "structured_content". Can be used for any other provider's extra data.
    metadata: Optional[Dict[str, Any]] = None
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audios: Optional[List[Audio]] = None
    files: Optional[List[File]] = None
