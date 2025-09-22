from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.media import Image
from agno.utils.log import log_error, log_warning

try:
    from google.genai.types import (
        FunctionDeclaration,
        Schema,
        Tool,
    )
    from google.genai.types import (
        Type as GeminiType,
    )
except ImportError:
    raise ImportError("`google-genai` not installed. Please install it using `pip install google-genai`")


def prepare_response_schema(pydantic_model: Type[BaseModel]) -> Union[Type[BaseModel], Schema]:
    """
    Prepare a Pydantic model for use as Gemini response schema.

    Returns the model directly if Gemini can handle it natively,
    otherwise converts to Gemini's Schema format.

    Args:
        pydantic_model: A Pydantic model class

    Returns:
        Either the original Pydantic model or a converted Schema object
    """
    schema_dict = pydantic_model.model_json_schema()

    # Convert to Gemini Schema if the model has problematic patterns
    if needs_conversion(schema_dict):
        try:
            converted = convert_schema(schema_dict)
        except Exception as e:
            log_warning(f"Failed to convert schema for {pydantic_model}: {e}")
            converted = None

        if converted is None:
            # If conversion fails, let Gemini handle it directly
            return pydantic_model
        return converted

    # Gemini can handle this model directly
    return pydantic_model


def needs_conversion(schema_dict: Dict[str, Any]) -> bool:
    """
    Check if a schema needs conversion for Gemini.

    Returns True if the schema has:
    - Self-references or circular references
    - Dict fields (additionalProperties) that Gemini doesn't handle well
    - Empty object definitions that Gemini rejects
    """
    # Check for dict fields (additionalProperties) anywhere in the schema
    if has_additional_properties(schema_dict):
        return True

    # Check if schema has $defs with circular references
    if "$defs" in schema_dict:
        defs = schema_dict["$defs"]
        for def_name, def_schema in defs.items():
            ref_path = f"#/$defs/{def_name}"
            if has_self_reference(def_schema, ref_path):
                return True

    return False


def has_additional_properties(schema: Any) -> bool:
    """Check if schema has additionalProperties (Dict fields)"""
    if isinstance(schema, dict):
        # Direct check
        if "additionalProperties" in schema:
            return True

        # Check properties recursively
        if "properties" in schema:
            for prop_schema in schema["properties"].values():
                if has_additional_properties(prop_schema):
                    return True

        # Check array items
        if "items" in schema:
            if has_additional_properties(schema["items"]):
                return True

    return False


def has_self_reference(schema: Dict, target_ref: str) -> bool:
    """Check if a schema references itself (directly or indirectly)"""
    if isinstance(schema, dict):
        # Direct self-reference
        if schema.get("$ref") == target_ref:
            return True

        # Check properties
        if "properties" in schema:
            for prop_schema in schema["properties"].values():
                if has_self_reference(prop_schema, target_ref):
                    return True

        # Check array items
        if "items" in schema:
            if has_self_reference(schema["items"], target_ref):
                return True

        # Check anyOf/oneOf/allOf
        for key in ["anyOf", "oneOf", "allOf"]:
            if key in schema:
                for sub_schema in schema[key]:
                    if has_self_reference(sub_schema, target_ref):
                        return True

    return False


def format_image_for_message(image: Image) -> Optional[Dict[str, Any]]:
    # Case 1: Image is a URL
    # Download the image from the URL and add it as base64 encoded data
    if image.url is not None:
        content_bytes = image.get_content_bytes()  # type: ignore
        if content_bytes is not None:
            try:
                import base64

                image_data = {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(content_bytes).decode("utf-8"),
                }
                return image_data
            except Exception as e:
                log_warning(f"Failed to download image from {image}: {e}")
                return None
        else:
            log_warning(f"Unsupported image format: {image}")
            return None

    # Case 2: Image is a local path
    elif image.filepath is not None:
        try:
            image_path = Path(image.filepath)
            if image_path.exists() and image_path.is_file():
                with open(image_path, "rb") as f:
                    content_bytes = f.read()
            else:
                log_error(f"Image file {image_path} does not exist.")
                raise
            return {
                "mime_type": "image/jpeg",
                "data": content_bytes,
            }
        except Exception as e:
            log_warning(f"Failed to load image from {image.filepath}: {e}")
            return None

    # Case 3: Image is a bytes object
    # Add it as base64 encoded data
    elif image.content is not None and isinstance(image.content, bytes):
        import base64

        image_data = {"mime_type": "image/jpeg", "data": base64.b64encode(image.content).decode("utf-8")}
        return image_data
    else:
        log_warning(f"Unknown image type: {type(image)}")
        return None


def convert_schema(
    schema_dict: Dict[str, Any], root_schema: Optional[Dict[str, Any]] = None, visited_refs: Optional[set] = None
) -> Optional[Schema]:
    """
    Recursively convert a JSON-like schema dictionary to a types.Schema object.

    Parameters:
        schema_dict (dict): The JSON schema dictionary with keys like "type", "description",
                            "properties", and "required".
        root_schema (dict, optional): The root schema containing $defs for resolving $ref
        visited_refs (set, optional): Set of visited $ref paths to detect circular references

    Returns:
        types.Schema: The converted schema.
    """

    # If this is the initial call, set root_schema to self and initialize visited_refs
    if root_schema is None:
        root_schema = schema_dict
    if visited_refs is None:
        visited_refs = set()

    # Handle $ref references with cycle detection
    if "$ref" in schema_dict:
        ref_path = schema_dict["$ref"]

        # Check for circular reference
        if ref_path in visited_refs:
            # Return a basic object schema to break the cycle
            return Schema(
                type=GeminiType.OBJECT,
                description=f"Circular reference to {ref_path}",
            )

        if ref_path.startswith("#/$defs/"):
            def_name = ref_path.split("/")[-1]
            if "$defs" in root_schema and def_name in root_schema["$defs"]:
                # Add to visited set before recursing
                new_visited = visited_refs.copy()
                new_visited.add(ref_path)

                referenced_schema = root_schema["$defs"][def_name]
                return convert_schema(referenced_schema, root_schema, new_visited)
        # If we can't resolve the reference, return None
        return None

    schema_type = schema_dict.get("type", "")
    if schema_type is None or schema_type == "null":
        return None
    description = schema_dict.get("description", None)
    default = schema_dict.get("default", None)

    # Handle enum types
    if "enum" in schema_dict:
        enum_values = schema_dict["enum"]
        return Schema(type=GeminiType.STRING, enum=enum_values, description=description, default=default)

    if schema_type == "object":
        # Handle regular objects with properties
        if "properties" in schema_dict:
            properties = {}
            for key, prop_def in schema_dict["properties"].items():
                # Process nullable types
                prop_type = prop_def.get("type", "")
                is_nullable = False
                if isinstance(prop_type, list) and "null" in prop_type:
                    prop_def["type"] = prop_type[0]
                    is_nullable = True

                # Process property schema (pass root_schema and visited_refs for $ref resolution)
                converted_schema = convert_schema(prop_def, root_schema, visited_refs)
                if converted_schema is not None:
                    if is_nullable:
                        converted_schema.nullable = True
                    properties[key] = converted_schema

            required = schema_dict.get("required", [])

            if properties:
                return Schema(
                    type=GeminiType.OBJECT,
                    properties=properties,
                    required=required,
                    description=description,
                    default=default,
                )
            else:
                return Schema(type=GeminiType.OBJECT, description=description, default=default)

        # Handle Dict types (objects with additionalProperties but no properties)
        elif "additionalProperties" in schema_dict:
            additional_props = schema_dict["additionalProperties"]

            # If additionalProperties is a schema object (Dict[str, T] case)
            if isinstance(additional_props, dict) and "type" in additional_props:
                # For Gemini, we need to represent Dict[str, T] as an object with at least one property
                # to avoid the "properties should be non-empty" error.
                # We'll create a generic property that represents the dictionary structure

                # Handle both single types and union types (arrays) from Zod schemas
                type_value = additional_props.get("type", "string")
                if isinstance(type_value, list):
                    value_type = type_value[0].upper() if type_value else "STRING"
                    union_types = ", ".join(type_value)
                    type_description_suffix = f" (supports union types: {union_types})"
                else:
                    # Single type
                    value_type = type_value.upper()
                    type_description_suffix = ""

                # Create a placeholder property to satisfy Gemini's requirements
                # This is a workaround since Gemini doesn't support additionalProperties directly
                placeholder_properties = {
                    "example_key": Schema(
                        type=value_type,
                        description=f"Example key-value pair. This object can contain any number of keys with {value_type.lower()} values{type_description_suffix}.",
                    )
                }
                if value_type == "ARRAY":
                    placeholder_properties["example_key"].items = {}  # type: ignore

                return Schema(
                    type=GeminiType.OBJECT,
                    properties=placeholder_properties,
                    description=description
                    or f"Dictionary with {value_type.lower()} values{type_description_suffix}. Can contain any number of key-value pairs.",
                    default=default,
                )
            else:
                # additionalProperties is false or true
                return Schema(type=GeminiType.OBJECT, description=description, default=default)

        # Handle empty objects
        else:
            return Schema(type=GeminiType.OBJECT, description=description, default=default)

    elif schema_type == "array" and "items" in schema_dict:
        if not schema_dict["items"]:  # Handle empty {}
            items = Schema(type=GeminiType.STRING)
        else:
            converted_items = convert_schema(schema_dict["items"], root_schema, visited_refs)
            items = converted_items if converted_items is not None else Schema(type=GeminiType.STRING)
        min_items = schema_dict.get("minItems")
        max_items = schema_dict.get("maxItems")
        return Schema(
            type=GeminiType.ARRAY,
            description=description,
            items=items,
            min_items=min_items,
            max_items=max_items,
        )

    elif schema_type == "string":
        schema_kwargs = {
            "type": GeminiType.STRING,
            "description": description,
            "default": default,
        }
        if "format" in schema_dict:
            schema_kwargs["format"] = schema_dict["format"]
        return Schema(**schema_kwargs)

    elif schema_type in ("integer", "number"):
        schema_kwargs = {
            "type": schema_type.upper(),
            "description": description,
            "default": default,
        }
        if "maximum" in schema_dict:
            schema_kwargs["maximum"] = schema_dict["maximum"]
        if "minimum" in schema_dict:
            schema_kwargs["minimum"] = schema_dict["minimum"]
        return Schema(**schema_kwargs)

    elif schema_type == "" and "anyOf" in schema_dict:
        any_of = []
        for sub_schema in schema_dict["anyOf"]:
            sub_schema_converted = convert_schema(sub_schema, root_schema, visited_refs)
            any_of.append(sub_schema_converted)

        is_nullable = False
        filtered_any_of = []

        for schema in any_of:
            if schema is None:
                is_nullable = True
            else:
                filtered_any_of.append(schema)

        any_of = filtered_any_of  # type: ignore
        if len(any_of) == 1 and any_of[0] is not None:
            any_of[0].nullable = is_nullable
            return any_of[0]
        else:
            return Schema(
                any_of=any_of,
                description=description,
                default=default,
            )
    else:
        if isinstance(schema_type, list):
            non_null_types = [t for t in schema_type if t != "null"]
            if non_null_types:
                schema_type = non_null_types[0]
            else:
                schema_type = ""
        # Only convert to uppercase if schema_type is not empty
        if schema_type:
            schema_type = schema_type.upper()
            return Schema(type=schema_type, description=description, default=default)
        else:
            # If we get here with an empty type and no other handlers matched,
            # something is wrong with the schema
            return None


def format_function_definitions(tools_list: List[Dict[str, Any]]) -> Optional[Tool]:
    function_declarations = []

    for tool in tools_list:
        if tool.get("type") == "function":
            func_info = tool.get("function", {})
            name = func_info.get("name")
            description = func_info.get("description", "")
            parameters_dict = func_info.get("parameters", {})

            parameters_schema = convert_schema(parameters_dict)
            # Create a FunctionDeclaration instance
            function_decl = FunctionDeclaration(
                name=name,
                description=description,
                parameters=parameters_schema,
            )

            function_declarations.append(function_decl)
    if function_declarations:
        return Tool(function_declarations=function_declarations)
    else:
        return None
