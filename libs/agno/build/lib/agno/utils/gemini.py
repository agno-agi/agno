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


def convert_schema(schema_dict: Dict[str, Any]) -> Optional[Schema]:
    """
    Recursively convert a JSON-like schema dictionary to a types.Schema object.

    Parameters:
        schema_dict (dict): The JSON schema dictionary with keys like "type", "description",
                            "properties", and "required".

    Returns:
        types.Schema: The converted schema.
    """

    schema_type = schema_dict.get("type", "")
    if schema_type is None or schema_type == "null":
        return None
    description = schema_dict.get("description", None)
    default = schema_dict.get("default", None)

    if schema_type == "object" and "properties" in schema_dict:
        properties = {}
        for key, prop_def in schema_dict["properties"].items():
            # Process nullable types
            prop_type = prop_def.get("type", "")
            is_nullable = False
            if isinstance(prop_type, list) and "null" in prop_type:
                prop_def["type"] = prop_type[0]
                is_nullable = True

            # Process property schema
            converted_schema = convert_schema(prop_def)
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

    elif schema_type == "array" and "items" in schema_dict:
        items = convert_schema(schema_dict["items"])
        return Schema(type=Type.ARRAY, description=description, items=items)

    elif schema_type == "" and "anyOf" in schema_dict:
        any_of = []
        for sub_schema in schema_dict["anyOf"]:
            sub_schema_converted = convert_schema(sub_schema)
            any_of.append(sub_schema_converted)

        is_nullable = False
        filtered_any_of = []

        for schema in any_of:
            if schema is None:
                is_nullable = True
            else:
                filtered_any_of.append(schema)

        any_of = filtered_any_of
        if len(any_of) == 1:
            any_of[0].nullable = is_nullable
            return any_of[0]
        else:
            return Schema(
                any_of=any_of,
                description=description,
                default=default,
            )
    else:
        schema_type = schema_type.upper()
        return Schema(type=schema_type, description=description, default=default)


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
