from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.media import Image
from agno.utils.log import log_error, log_warning

try:
    from google.genai.types import (
        FunctionDeclaration,
        Schema,
        Tool,
        Type,
    )
except ImportError:
    raise ImportError("`google-genai` not installed. Please install it using `pip install google-genai`")


def format_image_for_message(image: Image) -> Optional[Dict[str, Any]]:
    # Case 1: Image is a URL
    # Download the image from the URL and add it as base64 encoded data
    if image.url is not None:
        content_bytes = image.image_url_content
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


def convert_schema(schema_dict: Dict[str, Any], root_schema: Optional[Dict[str, Any]] = None) -> Optional[Schema]:
    """
    Recursively convert a JSON-like schema dictionary to a types.Schema object.

    Parameters:
        schema_dict (dict): The JSON schema dictionary with keys like "type", "description",
                            "properties", and "required".
        root_schema (dict, optional): The root schema containing $defs for resolving $ref

    Returns:
        types.Schema: The converted schema.
    """

    # If this is the initial call, set root_schema to self
    if root_schema is None:
        root_schema = schema_dict

    # Handle $ref references
    if "$ref" in schema_dict:
        ref_path = schema_dict["$ref"]
        if ref_path.startswith("#/$defs/"):
            def_name = ref_path.split("/")[-1]
            if "$defs" in root_schema and def_name in root_schema["$defs"]:
                referenced_schema = root_schema["$defs"][def_name]
                return convert_schema(referenced_schema, root_schema)
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
        return Schema(type=Type.STRING, enum=enum_values, description=description, default=default)

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

                # Process property schema (pass root_schema for $ref resolution)
                converted_schema = convert_schema(prop_def, root_schema)
                if converted_schema is not None:
                    if is_nullable:
                        converted_schema.nullable = True
                    properties[key] = converted_schema

            required = schema_dict.get("required", [])

            if properties:
                return Schema(
                    type=Type.OBJECT,
                    properties=properties,
                    required=required,
                    description=description,
                    default=default,
                )
            else:
                return Schema(type=Type.OBJECT, description=description, default=default)

        # Handle Dict types (objects with additionalProperties but no properties)
        elif "additionalProperties" in schema_dict:
            additional_props = schema_dict["additionalProperties"]

            # If additionalProperties is a schema object (Dict[str, T] case)
            if isinstance(additional_props, dict) and "type" in additional_props:
                # For Gemini, we need to represent Dict[str, T] as an object with at least one property
                # to avoid the "properties should be non-empty" error.
                # We'll create a generic property that represents the dictionary structure
                value_type = additional_props.get("type", "string").upper()
                # Create a placeholder property to satisfy Gemini's requirements
                # This is a workaround since Gemini doesn't support additionalProperties directly
                placeholder_properties = {
                    "example_key": Schema(
                        type=value_type,
                        description=f"Example key-value pair. This object can contain any number of keys with {value_type.lower()} values.",
                    )
                }
                if value_type == "ARRAY":
                    placeholder_properties["example_key"].items = {}

                return Schema(
                    type=Type.OBJECT,
                    properties=placeholder_properties,
                    description=description
                    or f"Dictionary with {value_type.lower()} values. Can contain any number of key-value pairs.",
                    default=default,
                )
            else:
                # additionalProperties is false or true
                return Schema(type=Type.OBJECT, description=description, default=default)

        # Handle empty objects
        else:
            return Schema(type=Type.OBJECT, description=description, default=default)

    elif schema_type == "array" and "items" in schema_dict:
        items = convert_schema(schema_dict["items"], root_schema)
        return Schema(type=Type.ARRAY, description=description, items=items)

    elif schema_type == "" and "anyOf" in schema_dict:
        any_of = []
        for sub_schema in schema_dict["anyOf"]:
            sub_schema_converted = convert_schema(sub_schema, root_schema)
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
