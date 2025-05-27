from typing import Any, Dict, Optional, Union, get_args, get_origin

from pydantic import BaseModel

from agno.utils.log import logger


def is_origin_union_type(origin: Any) -> bool:
    import sys

    if sys.version_info.minor >= 10:
        from types import UnionType  # type: ignore

        return origin in [Union, UnionType]

    return origin is Union


def get_json_type_for_py_type(arg: str) -> str:
    """
    Get the JSON schema type for a given type.
    :param arg: The type to get the JSON schema type for.
    :return: The JSON schema type.
    """
    # log_info(f"Getting JSON type for: {arg}")
    if arg in ("int", "float", "complex", "Decimal"):
        return "number"
    elif arg in ("str", "string"):
        return "string"
    elif arg in ("bool", "boolean"):
        return "boolean"
    elif arg in ("NoneType", "None"):
        return "null"
    elif arg in ("list", "tuple", "set", "frozenset"):
        return "array"
    elif arg in ("dict", "mapping"):
        return "object"

    # If the type is not recognized, return "object"
    return "object"


def inline_pydantic_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively inline Pydantic model schemas by replacing $ref with actual schema.
    """
    if not isinstance(schema, dict):
        return schema

    def resolve_ref(ref: str, defs: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve a $ref to its actual schema."""
        if not ref.startswith("#/$defs/"):
            return {"type": "object"}  # Fallback for external refs

        def_name = ref.split("/")[-1]
        if def_name in defs:
            return defs[def_name]
        return {"type": "object"}  # Fallback if definition not found

    def process_schema(s: Dict[str, Any], defs: Dict[str, Any]) -> Dict[str, Any]:
        """Process a schema dictionary, resolving all references."""
        if not isinstance(s, dict):
            return s

        # Handle $ref
        if "$ref" in s:
            return resolve_ref(s["$ref"], defs)

        # Create a new dict to avoid modifying the input
        result = s.copy()

        # Handle arrays
        if "items" in result:
            result["items"] = process_schema(result["items"], defs)

        # Handle object properties
        if "properties" in result:
            for prop_name, prop_schema in result["properties"].items():
                result["properties"][prop_name] = process_schema(prop_schema, defs)

        # Handle anyOf (for Union types)
        if "anyOf" in result:
            result["anyOf"] = [process_schema(sub_schema, defs) for sub_schema in result["anyOf"]]

        # Handle allOf (for inheritance)
        if "allOf" in result:
            result["allOf"] = [process_schema(sub_schema, defs) for sub_schema in result["allOf"]]

        # Handle additionalProperties
        if "additionalProperties" in result:
            result["additionalProperties"] = process_schema(result["additionalProperties"], defs)

        # Handle propertyNames
        if "propertyNames" in result:
            result["propertyNames"] = process_schema(result["propertyNames"], defs)

        return result

    # Store definitions for later use
    definitions = schema.pop("$defs", {})

    # First, resolve any nested references in definitions
    resolved_definitions = {}
    for def_name, def_schema in definitions.items():
        resolved_definitions[def_name] = process_schema(def_schema, definitions)

    # Process the main schema with resolved definitions
    result = process_schema(schema, resolved_definitions)

    # Remove any remaining definitions
    if "$defs" in result:
        del result["$defs"]

    return result


def get_json_schema_for_arg(type_hint: Any) -> Optional[Dict[str, Any]]:
    # log_info(f"Getting JSON schema for arg: {t}")
    type_args = get_args(type_hint)
    # log_info(f"Type args: {type_args}")
    type_origin = get_origin(type_hint)
    # log_info(f"Type origin: {type_origin}")
    if type_origin is not None:
        if type_origin in (list, tuple, set, frozenset):
            json_schema_for_items = get_json_schema_for_arg(type_args[0]) if type_args else {"type": "string"}
            return {"type": "array", "items": json_schema_for_items}
        elif type_origin is dict:
            # Handle both key and value types for dictionaries
            key_schema = get_json_schema_for_arg(type_args[0]) if type_args else {"type": "string"}
            value_schema = get_json_schema_for_arg(type_args[1]) if len(type_args) > 1 else {"type": "string"}
            return {"type": "object", "propertyNames": key_schema, "additionalProperties": value_schema}
        elif is_origin_union_type(type_origin):
            types = []
            for arg in type_args:
                try:
                    schema = get_json_schema_for_arg(arg)
                    if schema:
                        types.append(schema)
                except Exception:
                    continue
            return {"anyOf": types} if types else None

    elif issubclass(type_hint, BaseModel):
        # Get the schema and inline it
        schema = type_hint.model_json_schema()
        return inline_pydantic_schema(schema)  # type: ignore
    elif hasattr(type_hint, "__dataclass_fields__"):
        # Convert dataclass to JSON schema
        properties = {}
        required = []

        for field_name, field in type_hint.__dataclass_fields__.items():
            field_type = field.type
            field_schema = get_json_schema_for_arg(field_type)

            if (
                field_schema
                and "anyOf" in field_schema
                and any(schema["type"] == "null" for schema in field_schema["anyOf"])
            ):
                field_schema["type"] = next(
                    schema["type"] for schema in field_schema["anyOf"] if schema["type"] != "null"
                )
                field_schema.pop("anyOf")
            else:
                required.append(field_name)

            if field_schema:
                properties[field_name] = field_schema

        arg_json_schema = {"type": "object", "properties": properties, "additionalProperties": False}

        if required:
            arg_json_schema["required"] = required
        return arg_json_schema

    json_schema: Dict[str, Any] = {"type": get_json_type_for_py_type(type_hint.__name__)}
    if json_schema["type"] == "object":
        json_schema["properties"] = {}
        json_schema["additionalProperties"] = False
    return json_schema


def get_json_schema(
    type_hints: Dict[str, Any], param_descriptions: Optional[Dict[str, str]] = None, strict: bool = False
) -> Dict[str, Any]:
    json_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {},
    }
    if strict:
        json_schema["additionalProperties"] = False

    # We only include the fields in the type_hints dict
    for parameter_name, type_hint in type_hints.items():
        # log_info(f"Parsing arg: {k} | {v}")
        if parameter_name == "return":
            continue

        try:
            # Check if type is Optional (Union with NoneType)
            type_origin = get_origin(type_hint)
            type_args = get_args(type_hint)
            is_optional = type_origin is Union and len(type_args) == 2 and any(arg is type(None) for arg in type_args)

            # Get the actual type if it's Optional
            if is_optional:
                type_hint = next(arg for arg in type_args if arg is not type(None))

            if type_hint:
                arg_json_schema = get_json_schema_for_arg(type_hint)
            else:
                arg_json_schema = {}

            if arg_json_schema is not None:
                # Add description
                if param_descriptions and parameter_name in param_descriptions and param_descriptions[parameter_name]:
                    arg_json_schema["description"] = param_descriptions[parameter_name]

                json_schema["properties"][parameter_name] = arg_json_schema

            else:
                logger.warning(f"Could not parse argument {parameter_name} of type {type_hint}")
        except Exception as e:
            logger.error(f"Error processing argument {parameter_name}: {str(e)}")
            continue

    return json_schema
