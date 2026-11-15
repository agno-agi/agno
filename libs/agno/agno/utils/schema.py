"""Schema security utilities for hiding framework-injected parameters.

These utilities determine which parameters should be excluded from model-facing
schemas to prevent identity spoofing (model choosing whose data a tool reads)
and Pydantic serialization crashes (RunContext contains FilterExpr which cannot
be serialized to JSON schema).

Used by:
- agno.tools.function: Toolkit and @tool processing
- agno.os.mcp: MCP tool registration
"""

import types
from typing import Any, List, Optional, Tuple, TypeVar, Union, get_args, get_origin, get_type_hints

from agno.media import Audio, File, Image, Video
from agno.run import RunContext

# The media the caller attached to the run. Unlike the other injected names these
# carry the call's input rather than framework plumbing, so they decide whether a
# call can be cached at all (see _has_injected_media in function.py).
MEDIA_INJECTED_PARAMS: Tuple[str, ...] = ("images", "videos", "audios", "files")

# Parameter names the framework fills in itself (see FunctionCall._build_entrypoint_args).
# They are kept out of the model-facing schema, and a model-supplied value for one of
# them is discarded in favour of the injected object.
FRAMEWORK_INJECTED_PARAMS: Tuple[str, ...] = ("agent", "team", "run_context", *MEDIA_INJECTED_PARAMS)

# The `_agno_`-prefixed channels, used by wrappers whose tools may have arguments
# legitimately named "agent", "team" or "run_context" (e.g. MCP tools).
AGNO_INJECTED_PARAMS: Tuple[str, ...] = ("_agno_agent", "_agno_team", "_agno_run_context")

# The subset carrying the caller's identity or a live framework object. A schema may
# claim a media name -- a wrapper can expose the wrapped tool's own `files` argument --
# but never these: a model-supplied value here would choose whose data the tool reads.
IDENTITY_INJECTED_PARAMS: Tuple[str, ...] = ("agent", "team", "run_context", *AGNO_INJECTED_PARAMS)


def identity_injected_types() -> tuple:
    """The identity-bearing types: a model-supplied value for a parameter of
    one of these types would choose the framework object a tool receives.

    An identity-typed parameter is hidden from the model and bound by
    FunctionCall._build_entrypoint_args, whatever its name. Bare media
    annotations are hidden too (is_bare_media_typed) but are filled by the
    reserved parameter names alone, never by type."""
    from agno.agent.agent import Agent
    from agno.team.team import Team

    return (Agent, Team, RunContext)


ANNOTATION_DEPTH_CAP = 16


def unwrap_annotation(hint: Any) -> Any:
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


def is_union(hint: Any) -> bool:
    """True when the annotation is a Union type."""
    origin = get_origin(hint)
    return origin is Union or origin is getattr(types, "UnionType", None)


def annotation_reaches(hint: Any, targets: tuple, depth: int = 0, seen: Optional[List[Any]] = None) -> bool:
    """Whether any of these types can be reached anywhere inside an annotation.

    A plain structural search, with none of reaches_identity's asymmetry: it
    walks containers, every arm of a union, a TypeVar's bound and constraints,
    and the fields of any structural type -- dataclass, pydantic model,
    TypedDict, NamedTuple -- resolving them with get_type_hints so an
    annotation stored as a string under ``from __future__ import annotations``
    is read rather than skipped.

    Two things fail CLOSED, because a reference this cannot resolve is not one
    to hand the model: a nesting depth no real signature reaches, and a class
    whose own hints will not resolve."""
    from dataclasses import is_dataclass

    if depth > ANNOTATION_DEPTH_CAP:
        return True
    seen = [] if seen is None else seen
    hint = unwrap_annotation(hint)
    if any(hint is s for s in seen):
        return False
    seen = seen + [hint]

    if isinstance(hint, TypeVar):
        # A bound or a constraint is a promise about what will be substituted.
        bound = getattr(hint, "__bound__", None)
        if bound is not None and annotation_reaches(bound, targets, depth + 1, seen):
            return True
        return any(
            annotation_reaches(constraint, targets, depth + 1, seen)
            for constraint in getattr(hint, "__constraints__", ()) or ()
        )

    if isinstance(hint, type):
        if issubclass(hint, targets):
            return True
        if issubclass(hint, identity_injected_types()):
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
        return any(annotation_reaches(field_hint, targets, depth + 1, seen) for field_hint in field_hints.values())

    return any(annotation_reaches(argument, targets, depth + 1, seen) for argument in get_args(hint))


def reaches_identity(hint: Any, depth: int = 0, seen: Optional[List[Any]] = None) -> bool:
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
    if depth > ANNOTATION_DEPTH_CAP:
        return True  # Unreadable is not fillable; fail closed.
    seen = [] if seen is None else seen
    hint = unwrap_annotation(hint)
    if any(hint is s for s in seen):
        return False
    seen = seen + [hint]
    # RunContext anywhere at all, however deeply wrapped.
    if annotation_reaches(hint, (RunContext,)):
        return True
    if isinstance(hint, type):
        return annotation_reaches(hint, identity_injected_types())
    if is_union(hint):
        # A union is the model's to fill as long as one arm is something the
        # model can legitimately send. Only when every arm is identity -- bare
        # Agent, Optional[Agent] -- is there nothing else it could mean.
        arms = [arm for arm in get_args(hint) if arm is not type(None)]
        return bool(arms) and all(reaches_identity(arm, depth + 1, seen) for arm in arms)
    return any(reaches_identity(argument, depth + 1, seen) for argument in get_args(hint))


def annotation_binds(hint: Any, wanted: tuple, depth: int = 0, seen: Optional[List[Any]] = None) -> bool:
    """Whether the framework can put one of these objects INTO this parameter.

    Deliberately narrower than annotation_reaches, and the pair is not a
    contradiction: reaching decides what to keep from the model, binding
    decides what can be handed over. A ``list[RunContext]`` reaches one -- so
    it is not the model's to fill -- but it holds run contexts, it is not one,
    and binding the object there would fail validation on every call.

    Unwraps aliases and NewType, follows a TypeVar's bound and constraints, and
    accepts a union with an arm that binds. A container or a structural wrapper
    does not bind: nothing the framework has is that shape."""
    if depth > ANNOTATION_DEPTH_CAP:
        return False
    seen = [] if seen is None else seen
    hint = unwrap_annotation(hint)
    if any(hint is s for s in seen):
        return False
    seen = seen + [hint]
    if isinstance(hint, type):
        return issubclass(hint, wanted)
    if isinstance(hint, TypeVar):
        bound = getattr(hint, "__bound__", None)
        if bound is not None and annotation_binds(bound, wanted, depth + 1, seen):
            return True
        return any(
            annotation_binds(constraint, wanted, depth + 1, seen)
            for constraint in getattr(hint, "__constraints__", ()) or ()
        )
    if is_union(hint):
        return any(annotation_binds(arm, wanted, depth + 1, seen) for arm in get_args(hint))
    return False


def is_framework_typed(hint: Any) -> bool:
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
        all the same -- see is_bare_media_typed;
      * a union naming Agent or Team beside an ordinary type
        (owner: Union[str, Agent]). The model can only ever send JSON, so such a
        parameter receives a plain dict or string, never a live Agent."""
    return reaches_identity(hint)


def is_bare_media_typed(hint: Any) -> bool:
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
    hint = unwrap_annotation(hint)
    return isinstance(hint, type) and issubclass(hint, (Image, Video, Audio, File))


def is_schema_excluded(hint: Any) -> bool:
    """True when process_entrypoint keeps the parameter out of the model-facing
    schema: the identity types plus bare media types.

    Exclusion only. Framework OWNERSHIP is is_framework_typed, a strictly
    smaller set: an owned parameter is bound by _build_entrypoint_args and a
    value supplied for it is dropped, neither of which is true of media."""
    return is_framework_typed(hint) or is_bare_media_typed(hint)
