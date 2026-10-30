"""Build a Pydantic model from a JSON Schema, refusing what it cannot represent faithfully.

Models receive inline output schemas through the same Pydantic path as a hand-written
class, so every provider applies them the way it applies any other output_schema.
"""

import re
import warnings
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Type, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model
from pydantic_core import SchemaError as PydanticSchemaError

from agno.utils.models.schema_utils import json_schema_response_format, unwrap_json_schema_response_format

try:
    from typing import Annotated
except ImportError:  # pragma: no cover
    from typing_extensions import Annotated  # type: ignore


class UnsupportedJsonSchemaError(ValueError):
    """The JSON Schema uses a construct that json_schema_to_model cannot represent faithfully."""


# Attribute on a built model holding the dict it was built from, so it serializes back unchanged
SOURCE_SCHEMA_ATTR = "__agno_source_json_schema__"

_ANNOTATION_KEYWORDS = {
    "title",
    "description",
    "default",
    "examples",
    "$schema",
    "$id",
    "$comment",
    "deprecated",
    "readOnly",
    "writeOnly",
}
_STRUCTURAL_KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "anyOf",
    "oneOf",
    "allOf",
    "$ref",
    "$defs",
    "definitions",
    "nullable",
    "format",
}
# JSON Schema keyword -> pydantic Field argument
_CONSTRAINTS = {
    "minLength": "min_length",
    "maxLength": "max_length",
    "pattern": "pattern",
    "minimum": "ge",
    "maximum": "le",
    "exclusiveMinimum": "gt",
    "exclusiveMaximum": "lt",
    "multipleOf": "multiple_of",
    "minItems": "min_length",
    "maxItems": "max_length",
}
_SUPPORTED_KEYWORDS = _ANNOTATION_KEYWORDS | _STRUCTURAL_KEYWORDS | set(_CONSTRAINTS)
# Keywords that never constrain the value on their own, so they combine with any shape
_PASSIVE_KEYWORDS = _ANNOTATION_KEYWORDS | {"nullable", "$defs", "definitions"}
# Keywords that each define a node's whole shape; the converter handles one per node
_SHAPE_KEYWORDS = ("$ref", "allOf", "anyOf", "oneOf", "enum", "const")
_OBJECT_KEYWORDS = {"properties", "required", "additionalProperties"}
_PRIMITIVES: Dict[str, Any] = {"string": str, "integer": int, "number": float, "boolean": bool, "null": type(None)}


def json_schema_to_model(schema: Dict[str, Any], name: Optional[str] = None) -> Type[BaseModel]:
    """Build a Pydantic model equivalent to ``schema``, whose root must be an object with properties.

    Supports types (including type lists), properties and required, nested objects, maps
    (additionalProperties as a schema), arrays, enum and const, anyOf, oneOf over distinct
    types, local $ref into $defs/definitions (recursion included), descriptions and the
    string, number and array constraints. Anything else raises UnsupportedJsonSchemaError
    instead of being dropped.
    """
    if not isinstance(schema, dict):
        raise UnsupportedJsonSchemaError("the schema must be a JSON object")
    builder = _ModelBuilder(schema)
    root_name = name or schema.get("title") or "OutputSchema"
    model = builder.build_root(schema, str(root_name))
    # Recorded as a response format, the shape rehydrate_inline_output_schema loads back
    setattr(model, SOURCE_SCHEMA_ATTR, json_schema_response_format(schema, name=model.__name__))
    return model


def source_json_schema(model: Any) -> Optional[Dict[str, Any]]:
    """The dict a model was built from by json_schema_to_model, or None for any other model."""
    source = getattr(model, SOURCE_SCHEMA_ATTR, None) if isinstance(model, type) else None
    return source if isinstance(source, dict) else None


def serialize_output_schema(output_schema: Any) -> Any:
    """The stored form of an agent or team output_schema.

    A model built from an inline schema is stored as the dict it came from; any other model
    by its class name, resolved through the registry on load; a dict as is.
    """
    if isinstance(output_schema, type) and issubclass(output_schema, BaseModel):
        source = source_json_schema(output_schema)
        return source if source is not None else output_schema.__name__
    if isinstance(output_schema, dict):
        return output_schema
    return None


def rehydrate_inline_output_schema(config: Dict[str, Any], strict: bool, component_label: str) -> None:
    """Replace a stored JSON Schema response format in config["output_schema"] with the model it describes.

    Other dicts (provider-specific response formats) are left for the model to pass through.
    """
    from agno.exceptions import ComponentRehydrationError
    from agno.utils.log import log_warning

    stored = config.get("output_schema")
    inline = unwrap_json_schema_response_format(stored)
    if inline is None:
        return
    try:
        model = json_schema_to_model(inline.schema, name=inline.name)
    except UnsupportedJsonSchemaError as e:
        if strict:
            raise ComponentRehydrationError(
                f"{component_label} has an output schema that cannot be loaded: {e}. Fix the schema, "
                "or pass strict=False to load the component without it."
            ) from e
        log_warning(f"{component_label} output schema cannot be loaded, skipping: {e}")
        del config["output_schema"]
        return
    setattr(model, SOURCE_SCHEMA_ATTR, stored)
    config["output_schema"] = model


class _ModelBuilder:
    def __init__(self, root: Dict[str, Any]):
        self.root = root
        self.used_names: Set[str] = set()
        self.ref_models: Dict[str, Any] = {}
        self.building: Dict[str, str] = {}
        self.models: List[Type[BaseModel]] = []

    def build_root(self, schema: Dict[str, Any], name: str) -> Type[BaseModel]:
        _check_keywords(schema, "")
        root_types = _types_of(schema)
        if (root_types and root_types != {"object"}) or schema.get("nullable") is True:
            raise UnsupportedJsonSchemaError(
                "the root must be an object schema with properties, not null or another type"
            )
        if "$ref" in schema:
            model = self._ref_annotation(schema["$ref"], "")
        elif _declares_properties(schema):
            model = self._object_model(schema, name, "")
        else:
            model = None
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise UnsupportedJsonSchemaError(
                "the root must be an object schema with properties, not null or another type"
            )
        namespace = {m.__name__: m for m in self.models}
        for built in self.models:
            try:
                built.model_rebuild(_types_namespace=namespace)
            except (PydanticSchemaError, TypeError, ValueError) as e:
                raise UnsupportedJsonSchemaError(f"cannot build a model: {e}") from e
        return model

    # Names -------------------------------------------------------------

    def _model_name(self, base: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_]", "_", base).strip("_") or "Model"
        if cleaned[0].isdigit():
            cleaned = f"M{cleaned}"
        candidate = cleaned[:60]
        suffix = 2
        while candidate in self.used_names:
            candidate = f"{cleaned[:56]}{suffix}"
            suffix += 1
        self.used_names.add(candidate)
        return candidate

    # Refs --------------------------------------------------------------

    def _lookup_ref(self, ref: Any, path: str) -> Dict[str, Any]:
        match = re.fullmatch(r"#/(\$defs|definitions)/([^/]+)", ref) if isinstance(ref, str) else None
        if match is None:
            raise UnsupportedJsonSchemaError(f"{_at(path)}only local refs into $defs or definitions are supported")
        defs = self.root.get(match.group(1))
        target = defs.get(match.group(2)) if isinstance(defs, dict) else None
        if not isinstance(target, dict):
            raise UnsupportedJsonSchemaError(f"{_at(path)}{ref} does not resolve")
        return target

    def _ref_annotation(self, ref: str, path: str) -> Any:
        if ref in self.ref_models:
            return self.ref_models[ref]
        if ref in self.building:
            if not self.building[ref]:
                raise UnsupportedJsonSchemaError(f"{_at(path)}{ref} refers to itself without an object in between")
            # A recursive ref: a forward reference resolved by model_rebuild
            return self.building[ref]
        target = self._lookup_ref(ref, path)
        def_name = ref.rsplit("/", 1)[-1]
        if not _declares_properties(target):
            self.building[ref] = ""
            annotation = self._annotation(target, def_name, f"{ref}")
            del self.building[ref]
            self.ref_models[ref] = annotation
            return annotation
        # The definition's other types and nullable wrap the object model, here and in recursive refs
        alternatives = sorted(_types_of(target) - {"object"})
        if any(t not in _PRIMITIVES for t in alternatives):
            raise UnsupportedJsonSchemaError(
                f"{_at(ref)}a referenced object can only also allow primitive types, not {alternatives}"
            )
        constraints = self._constraint_kwargs(target, ref)

        def wrap(inner: Any) -> Any:
            members = [inner, *(_PRIMITIVES[t] for t in alternatives)]
            annotation = members[0] if len(members) == 1 else Union[tuple(members)]
            if target.get("nullable") is True:
                annotation = Optional[annotation]
            return Annotated[annotation, Field(**constraints)] if constraints else annotation

        model_name = self._model_name(str(target.get("title") or def_name))
        self.building[ref] = wrap(model_name)
        model = self._object_model(target, model_name, ref, reserved=True)
        del self.building[ref]
        self.ref_models[ref] = wrap(model)
        return self.ref_models[ref]

    # Annotations -------------------------------------------------------

    def _annotation(self, schema: Any, hint: str, path: str, with_docs: bool = True) -> Any:
        """The type for a schema, wrapped in Annotated when it carries constraints or (with_docs) a description.

        Properties pass with_docs=False and put the description on the field itself, so an
        optional property documents the field rather than its non-null branch.
        """
        if schema is True or schema == {}:
            return Any
        if not isinstance(schema, dict):
            raise UnsupportedJsonSchemaError(f"{_at(path)}expected a schema object")
        _check_keywords(schema, path)

        base = self._base_type(schema, hint, path)
        if schema.get("nullable") is True:
            base = Optional[base]
        field_kwargs = self._constraint_kwargs(schema, path)
        if with_docs:
            field_kwargs.update(_doc_kwargs(schema))
        if field_kwargs:
            return Annotated[base, Field(**field_kwargs)]
        return base

    def _constraint_kwargs(self, schema: Dict[str, Any], path: str) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {}
        types = _types_of(schema)
        for keyword, argument in _CONSTRAINTS.items():
            if keyword not in schema:
                continue
            value = schema[keyword]
            if keyword in ("minItems", "maxItems") and "array" not in types:
                raise UnsupportedJsonSchemaError(f"{_at(path)}{keyword} needs type array")
            if keyword in ("minLength", "maxLength", "pattern") and "string" not in types:
                raise UnsupportedJsonSchemaError(f"{_at(path)}{keyword} needs type string")
            if argument in ("ge", "le", "gt", "lt", "multiple_of") and not types & {"integer", "number"}:
                raise UnsupportedJsonSchemaError(f"{_at(path)}{keyword} needs type integer or number")
            if len(types - {"null"}) > 1:
                raise UnsupportedJsonSchemaError(f"{_at(path)}{keyword} on a multi-type field is not supported")
            if keyword == "pattern":
                _check_pattern(value, path)
            kwargs[argument] = value
        if isinstance(schema.get("format"), str):
            kwargs["json_schema_extra"] = {"format": schema["format"]}
        return kwargs

    def _base_type(self, schema: Dict[str, Any], hint: str, path: str) -> Any:
        if "allOf" in schema:
            members = schema["allOf"]
            if not isinstance(members, list) or len(members) != 1:
                raise UnsupportedJsonSchemaError(f"{_at(path)}allOf is only supported with a single member")
            return self._annotation(members[0], hint, f"{path}/allOf/0")
        if "$ref" in schema:
            return self._ref_annotation(schema["$ref"], path)
        if "const" in schema:
            return Literal[_literal_value(schema["const"], path)]  # type: ignore[valid-type]
        if "enum" in schema:
            values = schema["enum"]
            if not isinstance(values, list) or not values:
                raise UnsupportedJsonSchemaError(f"{_at(path)}enum must be a non-empty list")
            return Literal[tuple(_literal_value(v, path) for v in values)]  # type: ignore[valid-type]
        if "anyOf" in schema:
            return self._union(schema["anyOf"], hint, f"{path}/anyOf", disjoint=False)
        if "oneOf" in schema:
            return self._union(schema["oneOf"], hint, f"{path}/oneOf", disjoint=True)

        json_type = schema.get("type")
        if isinstance(json_type, list):
            if not json_type or not all(isinstance(t, str) for t in json_type):
                raise UnsupportedJsonSchemaError(f"{_at(path)}type must be a string or a list of strings")
            members = [self._single_type(schema, t, hint, path) for t in json_type]
            return members[0] if len(members) == 1 else Union[tuple(members)]  # type: ignore[return-value]
        if json_type is None:
            if "properties" in schema or "additionalProperties" in schema:
                json_type = "object"
            elif "items" in schema:
                json_type = "array"
            else:
                return Any
        return self._single_type(schema, json_type, hint, path)

    def _single_type(self, schema: Dict[str, Any], json_type: Any, hint: str, path: str) -> Any:
        if json_type in _PRIMITIVES:
            return _PRIMITIVES[json_type]
        if json_type == "array":
            items = schema.get("items")
            if items is None:
                return List[Any]
            if isinstance(items, list):
                raise UnsupportedJsonSchemaError(f"{_at(path)}tuple-style items are not supported")
            return List[self._annotation(items, f"{hint}Item", f"{path}/items")]  # type: ignore[misc]
        if json_type == "object":
            return self._object_type(schema, hint, path)
        raise UnsupportedJsonSchemaError(f"{_at(path)}unknown type {json_type!r}")

    def _union(self, members: Any, hint: str, path: str, disjoint: bool) -> Any:
        if not isinstance(members, list) or not members:
            raise UnsupportedJsonSchemaError(f"{_at(path)}must be a non-empty list")
        if disjoint:
            # oneOf means exactly one; a Union is equivalent only when no value can match two members
            member_types = [m.get("type") if isinstance(m, dict) else None for m in members]
            distinct = all(isinstance(t, str) for t in member_types) and len(set(member_types)) == len(member_types)
            if not distinct or {"integer", "number"} <= set(member_types):
                raise UnsupportedJsonSchemaError(
                    f"{_at(path)}oneOf is only supported when its members' types cannot overlap"
                )
        annotations = [self._annotation(m, f"{hint}Option{i + 1}", f"{path}/{i}") for i, m in enumerate(members)]
        return annotations[0] if len(annotations) == 1 else Union[tuple(annotations)]  # type: ignore[return-value]

    # Objects -----------------------------------------------------------

    def _object_type(self, schema: Dict[str, Any], hint: str, path: str) -> Any:
        additional = schema.get("additionalProperties")
        if not _declares_properties(schema):
            if "properties" in schema and not isinstance(schema["properties"], dict):
                raise UnsupportedJsonSchemaError(f"{_at(path)}properties must be an object")
            if isinstance(additional, dict):
                return Dict[str, self._annotation(additional, f"{hint}Value", f"{path}/additionalProperties")]  # type: ignore[misc]
            if additional is False:
                raise UnsupportedJsonSchemaError(f"{_at(path)}an object with no properties cannot forbid all keys")
            return Dict[str, Any]
        return self._object_model(schema, self._model_name(str(schema.get("title") or hint)), path, reserved=True)

    def _object_model(self, schema: Dict[str, Any], name: str, path: str, reserved: bool = False) -> Type[BaseModel]:
        if not reserved:
            name = self._model_name(name)
        _check_keywords(schema, path)
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise UnsupportedJsonSchemaError(f"{_at(path)}properties must be an object")
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            raise UnsupportedJsonSchemaError(
                f"{_at(path)}properties together with a schema-valued additionalProperties is not supported"
            )
        required = schema.get("required") or []
        if not isinstance(required, list):
            raise UnsupportedJsonSchemaError(f"{_at(path)}required must be a list")
        missing = [r for r in required if r not in properties]
        if missing:
            raise UnsupportedJsonSchemaError(f"{_at(path)}required lists {missing} which are not in properties")

        fields: Dict[str, Tuple[Any, Any]] = {}
        for prop_name, prop_schema in properties.items():
            prop_path = f"{path}/properties/{prop_name}"
            if not isinstance(prop_name, str) or prop_name.startswith("_") or prop_name.startswith("model_"):
                raise UnsupportedJsonSchemaError(
                    f"{_at(prop_path)}property names starting with '_' or 'model_' are not supported"
                )
            annotation = self._annotation(prop_schema, _pascal(prop_name), prop_path, with_docs=False)
            docs = _doc_kwargs(prop_schema) if isinstance(prop_schema, dict) else {}
            if prop_name in required:
                fields[prop_name] = (annotation, Field(..., **docs))
            elif isinstance(prop_schema, dict) and "default" in prop_schema:
                fields[prop_name] = (annotation, Field(prop_schema["default"], **docs))
            else:
                # Not required means it may be absent, not that it may be null: keep the type,
                # and keep the placeholder default out of the schema the model sees
                fields[prop_name] = (annotation, Field(None, json_schema_extra=_drop_default, **docs))

        # JSON Schema allows undeclared keys unless additionalProperties is false: keep them rather than drop them
        config = ConfigDict(extra="forbid" if additional is False else "allow")
        if isinstance(schema.get("title"), str):
            config["title"] = schema["title"]
        with warnings.catch_warnings():
            # A property named like a BaseModel attribute (json, copy, schema) only shadows it
            warnings.filterwarnings("ignore", message=".*shadows an attribute in parent.*")
            try:
                model = create_model(name, __config__=config or None, **fields)  # type: ignore[call-overload]
            except UnsupportedJsonSchemaError:
                raise
            except (PydanticSchemaError, TypeError, ValueError) as e:
                raise UnsupportedJsonSchemaError(f"{_at(path)}cannot build a model: {e}") from e
        if isinstance(schema.get("description"), str):
            model.__doc__ = schema["description"]
        self.models.append(model)
        return model


def _declares_properties(schema: Dict[str, Any]) -> bool:
    properties = schema.get("properties")
    return isinstance(properties, dict) and bool(properties)


def _check_keywords(schema: Dict[str, Any], path: str) -> None:
    """Refuse unknown keywords, and any combination the converter would only partly apply.

    Every node is one shape ($ref, a single allOf/anyOf/oneOf, enum or const, or a type with
    its matching keywords) plus passive annotations; anything else would be silently dropped.
    """
    keys = {k for k in schema if not k.startswith("x-")}
    unsupported = sorted(keys - _SUPPORTED_KEYWORDS)
    if unsupported:
        raise UnsupportedJsonSchemaError(f"{_at(path)}unsupported keyword(s): {', '.join(unsupported)}")
    shapes = [k for k in _SHAPE_KEYWORDS if k in keys]
    if shapes:
        allowed = _PASSIVE_KEYWORDS | {shapes[0]} | ({"type"} if shapes[0] in ("enum", "const") else set())
        extra = sorted(keys - allowed)
        if extra:
            raise UnsupportedJsonSchemaError(f"{_at(path)}{shapes[0]} cannot be combined with {', '.join(extra)}")
        types = _types_of(schema)
        values = schema.get("enum") if shapes[0] == "enum" else [schema.get("const")]
        if types and isinstance(values, list):
            # A literal outside the declared type can never match; a Literal would accept it anyway
            mismatched = [v for v in values if not any(_matches_type(v, t) for t in types)]
            if mismatched:
                raise UnsupportedJsonSchemaError(
                    f"{_at(path)}{shapes[0]} value(s) {mismatched!r} do not match type {schema['type']!r}"
                )
        return
    types = _types_of(schema)
    if keys & _OBJECT_KEYWORDS and types and "object" not in types:
        raise UnsupportedJsonSchemaError(f"{_at(path)}properties, required and additionalProperties need type object")
    if "items" in keys and types and "array" not in types:
        raise UnsupportedJsonSchemaError(f"{_at(path)}items needs type array")
    if schema.get("required") and not _declares_properties(schema):
        # Without declared properties the object becomes a map, which cannot require keys
        raise UnsupportedJsonSchemaError(f"{_at(path)}required needs the keys declared in properties")


def _matches_type(value: Any, json_type: str) -> bool:
    if json_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "null":
        return value is None
    return False


def _check_pattern(pattern: Any, path: str) -> None:
    """Refuse a pattern Pydantic's regex engine cannot compile (lookarounds, backreferences, bad syntax)."""
    try:
        TypeAdapter(Annotated[str, Field(pattern=pattern)])  # type: ignore[arg-type]
    except (PydanticSchemaError, TypeError, ValueError) as e:
        raise UnsupportedJsonSchemaError(f"{_at(path)}pattern {pattern!r} is not supported by the regex engine") from e


def _drop_default(schema: Dict[str, Any]) -> None:
    schema.pop("default", None)


def _doc_kwargs(schema: Dict[str, Any]) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if isinstance(schema.get("description"), str):
        kwargs["description"] = schema["description"]
    if isinstance(schema.get("examples"), list):
        kwargs["examples"] = schema["examples"]
    return kwargs


def _types_of(schema: Dict[str, Any]) -> Set[str]:
    json_type = schema.get("type")
    if isinstance(json_type, str):
        return {json_type}
    if isinstance(json_type, list):
        return {t for t in json_type if isinstance(t, str)}
    return set()


def _literal_value(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise UnsupportedJsonSchemaError(f"{_at(path)}enum and const values must be strings, numbers, booleans or null")


def _pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", name) if part) or "Field"


def _at(path: str) -> str:
    return f"at {path.lstrip('/')}: " if path.strip("/") else ""
