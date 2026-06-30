from dataclasses import asdict
from typing import Any, List, Optional, Set, Type, Union, get_type_hints


def isinstanceany(obj: Any, class_list: List[Type]) -> bool:
    """Returns True if obj is an instance of the classes in class_list"""
    for cls in class_list:
        if isinstance(obj, cls):
            return True
    return False


def is_empty(val: Any) -> bool:
    """Returns True if val is None or empty"""
    if val is None or len(val) == 0 or val == "":
        return True
    return False


def get_image_str(repo: str, tag: str) -> str:
    return f"{repo}:{tag}"


def dataclass_to_dict(dataclass_object, exclude: Optional[set[str]] = None, exclude_none: bool = False) -> dict:
    final_dict = asdict(dataclass_object)
    if exclude:
        for key in exclude:
            final_dict.pop(key, None)
    if exclude_none:
        final_dict = {k: v for k, v in final_dict.items() if v is not None}
    return final_dict


def nested_model_dump(value):
    from pydantic import BaseModel

    if isinstance(value, BaseModel):
        return value.model_dump()
    elif isinstance(value, dict):
        return {k: nested_model_dump(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [nested_model_dump(item) for item in value]
    return value


def is_typed_dict(cls: Type[Any]) -> bool:
    """Check if a class is a TypedDict"""
    return (
        hasattr(cls, "__annotations__")
        and hasattr(cls, "__total__")
        and hasattr(cls, "__required_keys__")
        and hasattr(cls, "__optional_keys__")
    )


def check_type_compatibility(value: Any, expected_type: Type) -> bool:
    """Basic type compatibility checking."""
    from typing import get_args, get_origin

    # Handle None/Optional types
    if value is None:
        return (
            type(None) in get_args(expected_type) if hasattr(expected_type, "__args__") else expected_type is type(None)
        )

    # Handle Union types (including Optional)
    origin = get_origin(expected_type)
    if origin is Union:
        return any(check_type_compatibility(value, arg) for arg in get_args(expected_type))

    # Handle List types
    if origin is list or expected_type is list:
        if not isinstance(value, list):
            return False
        if origin is list and get_args(expected_type):
            element_type = get_args(expected_type)[0]
            return all(check_type_compatibility(item, element_type) for item in value)
        return True

    if expected_type in (str, int, float, bool):
        return isinstance(value, expected_type)

    if expected_type is Any:
        return True

    try:
        return isinstance(value, expected_type)
    except TypeError:
        return True


def validate_typed_dict(data: dict, schema_cls) -> dict:
    """Validate input data against a TypedDict schema."""
    if not isinstance(data, dict):
        raise ValueError(f"Expected dict for TypedDict {schema_cls.__name__}, got {type(data)}")

    # Get type hints from the TypedDict
    try:
        type_hints = get_type_hints(schema_cls)
    except Exception as e:
        raise ValueError(f"Could not get type hints for TypedDict {schema_cls.__name__}: {e}")

    # Get required and optional keys
    required_keys: Set[str] = getattr(schema_cls, "__required_keys__", set())
    optional_keys: Set[str] = getattr(schema_cls, "__optional_keys__", set())
    all_keys = required_keys | optional_keys

    # Check for missing required fields
    missing_required = required_keys - set(data.keys())
    if missing_required:
        raise ValueError(f"Missing required fields in TypedDict {schema_cls.__name__}: {missing_required}")

    # Check for unexpected fields
    unexpected_fields = set(data.keys()) - all_keys
    if unexpected_fields:
        raise ValueError(f"Unexpected fields in TypedDict {schema_cls.__name__}: {unexpected_fields}")

    # Basic type checking for provided fields
    validated_data = {}
    for field_name, value in data.items():
        if field_name in type_hints:
            expected_type = type_hints[field_name]

            # Handle simple type checking
            if not check_type_compatibility(value, expected_type):
                raise ValueError(
                    f"Field '{field_name}' expected type {expected_type}, got {type(value)} with value {value}"
                )

            validated_data[field_name] = value

    return validated_data
