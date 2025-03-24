from typing import Any, Dict, Optional, Union, get_args, get_origin

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


def get_json_schema_for_arg(t: Any) -> Optional[Dict[str, Any]]:
    # log_info(f"Getting JSON schema for arg: {t}")
    type_args = get_args(t)
    # log_info(f"Type args: {type_args}")
    type_origin = get_origin(t)
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

    json_schema: Dict[str, Any] = {"type": get_json_type_for_py_type(t.__name__)}
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

    for k, v in type_hints.items():
        # log_info(f"Parsing arg: {k} | {v}")
        if k == "return":
            continue

        try:
            # Check if type is Optional (Union with NoneType)
            type_origin = get_origin(v)
            type_args = get_args(v)
            is_optional = type_origin is Union and len(type_args) == 2 and any(arg is type(None) for arg in type_args)

            # Get the actual type if it's Optional
            if is_optional:
                v = next(arg for arg in type_args if arg is not type(None))

            # Handle cases with no type hint
            if v:
                arg_json_schema = get_json_schema_for_arg(v)
            else:
                arg_json_schema = {}

            if arg_json_schema is not None:
                if is_optional:
                    # Handle null type for optional fields
                    if isinstance(arg_json_schema["type"], list):
                        arg_json_schema["type"].append("null")
                    else:
                        arg_json_schema["type"] = [arg_json_schema["type"], "null"]
                # Add description
                if param_descriptions and k in param_descriptions and param_descriptions[k]:
                    arg_json_schema["description"] = param_descriptions[k]

                json_schema["properties"][k] = arg_json_schema

            else:
                logger.warning(f"Could not parse argument {k} of type {v}")
        except Exception as e:
            logger.error(f"Error processing argument {k}: {str(e)}")
            continue

    return json_schema
