import hashlib
import json
import re
import uuid
from typing import Any, Optional, Type, Union
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from agno.utils.log import logger

POSTGRES_INVALID_CHARS_REGEX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def is_valid_uuid(uuid_str: str) -> bool:
    """
    Check if a string is a valid UUID

    Args:
        uuid_str: String to check

    Returns:
        bool: True if string is a valid UUID, False otherwise
    """
    from uuid import UUID

    try:
        UUID(str(uuid_str))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def url_safe_string(input_string):
    # Replace spaces with dashes
    safe_string = input_string.replace(" ", "-")

    # Convert camelCase to kebab-case
    safe_string = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", safe_string).lower()

    # Convert snake_case to kebab-case
    safe_string = safe_string.replace("_", "-")

    # Remove special characters, keeping alphanumeric, dashes, and dots
    safe_string = re.sub(r"[^\w\-.]", "", safe_string)

    # Ensure no consecutive dashes
    safe_string = re.sub(r"-+", "-", safe_string)

    return safe_string


def hash_string_sha256(input_string):
    # Encode the input string to bytes
    encoded_string = input_string.encode("utf-8")

    # Create a SHA-256 hash object
    sha256_hash = hashlib.sha256()

    # Update the hash object with the encoded string
    sha256_hash.update(encoded_string)

    # Get the hexadecimal digest of the hash
    hex_digest = sha256_hash.hexdigest()

    return hex_digest


def _extract_json_objects(text: str) -> list[str]:
    objs: list[str] = []
    brace_depth = 0
    start_idx: Optional[int] = None
    for idx, ch in enumerate(text):
        if ch == "{" and brace_depth == 0:
            start_idx = idx
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0 and start_idx is not None:
                objs.append(text[start_idx : idx + 1])
                start_idx = None
    return objs


def _clean_json_content(content: str) -> str:
    """Clean and prepare JSON content for parsing."""
    # Handle code blocks
    if "```json" in content:
        content = content.split("```json")[-1].strip()
        parts = content.split("```")
        if len(parts) > 1:
            parts.pop(-1)
        content = "".join(parts)
    elif "```" in content:
        content = content.split("```")[1].strip()

    # Replace markdown formatting like *"name"* or `"name"` with "name"
    content = re.sub(r'[*`#]?"([A-Za-z0-9_]+)"[*`#]?', r'"\1"', content)

    # Handle newlines and control characters
    content = content.replace("\n", " ").replace("\r", "")
    content = re.sub(r"[\x00-\x1F\x7F]", "", content)

    # Escape quotes only in values, not keys
    def escape_quotes_in_values(match):
        key = match.group(1)
        value = match.group(2)

        if '\\"' in value:
            unescaped_value = value.replace('\\"', '"')
            escaped_value = unescaped_value.replace('"', '\\"')
        else:
            escaped_value = value.replace('"', '\\"')

        return f'"{key}": "{escaped_value}'

    # Find and escape quotes in field values
    content = re.sub(r'"(?P<key>[^"]+)"\s*:\s*"(?P<value>.*?)(?="\s*(?:,|\}))', escape_quotes_in_values, content)

    return content


def _parse_individual_json(content: str, output_schema: Type[BaseModel]) -> Optional[BaseModel]:
    """Parse individual JSON objects from content and merge them based on response model fields."""
    candidate_jsons = _extract_json_objects(content)
    merged_data: dict = {}

    # Get the expected fields from the response model
    model_fields = output_schema.model_fields if hasattr(output_schema, "model_fields") else {}

    for candidate in candidate_jsons:
        try:
            candidate_obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        if isinstance(candidate_obj, dict):
            # Merge data based on model fields
            for field_name, field_info in model_fields.items():
                if field_name in candidate_obj:
                    field_value = candidate_obj[field_name]
                    # If field is a list, extend it; otherwise, use the latest value
                    if isinstance(field_value, list):
                        if field_name not in merged_data:
                            merged_data[field_name] = []
                        merged_data[field_name].extend(field_value)
                    else:
                        merged_data[field_name] = field_value

    if not merged_data:
        return None

    try:
        return output_schema.model_validate(merged_data)
    except ValidationError as e:
        logger.warning("Validation failed on merged data: %s", e)
        return None


def parse_response_model_str(content: str, output_schema: Type[BaseModel]) -> Optional[BaseModel]:
    structured_output = None

    # Extract thinking content first to prevent <think> tags from corrupting JSON
    from agno.utils.reasoning import extract_thinking_content

    # handle thinking content b/w <think> tags
    if "</think>" in content:
        reasoning_content, output_content = extract_thinking_content(content)
        if reasoning_content:
            content = output_content

    # Clean content first to simplify all parsing attempts
    cleaned_content = _clean_json_content(content)

    try:
        # First attempt: direct JSON validation on cleaned content
        structured_output = output_schema.model_validate_json(cleaned_content)
    except (ValidationError, json.JSONDecodeError):
        try:
            # Second attempt: Parse as Python dict
            data = json.loads(cleaned_content)
            structured_output = output_schema.model_validate(data)
        except (ValidationError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse cleaned JSON: {e}")

            # Third attempt: Extract individual JSON objects
            candidate_jsons = _extract_json_objects(cleaned_content)

            if len(candidate_jsons) == 1:
                # Single JSON object - try to parse it directly
                try:
                    data = json.loads(candidate_jsons[0])
                    structured_output = output_schema.model_validate(data)
                except (ValidationError, json.JSONDecodeError):
                    pass

            if structured_output is None:
                # Final attempt: Handle concatenated JSON objects with field merging
                structured_output = _parse_individual_json(cleaned_content, output_schema)
                if structured_output is None:
                    logger.warning("All parsing attempts failed.")

    return structured_output


def parse_response_dict_str(content: str) -> Optional[dict]:
    """Parse dict from string content, extracting JSON if needed"""
    from agno.utils.reasoning import extract_thinking_content

    # Handle thinking content b/w <think> tags
    if "</think>" in content:
        reasoning_content, output_content = extract_thinking_content(content)
        if reasoning_content:
            content = output_content

    # Clean content first to simplify all parsing attempts
    cleaned_content = _clean_json_content(content)

    try:
        # First attempt: direct JSON parsing on cleaned content
        return json.loads(cleaned_content)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse cleaned JSON: {e}")

        # Second attempt: Extract individual JSON objects
        candidate_jsons = _extract_json_objects(cleaned_content)

        if len(candidate_jsons) == 1:
            # Single JSON object - try to parse it directly
            try:
                return json.loads(candidate_jsons[0])
            except json.JSONDecodeError:
                pass

        if len(candidate_jsons) > 1:
            # Final attempt: Merge multiple JSON objects
            merged_data: dict = {}
            for candidate in candidate_jsons:
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        merged_data.update(obj)
                except json.JSONDecodeError:
                    continue
            if merged_data:
                return merged_data

        logger.warning("All parsing attempts failed.")
        return None


def generate_id(seed: Optional[str] = None) -> str:
    """
    Generate a deterministic UUID5 based on a seed string.
    If no seed is provided, generate a random UUID4.

    Args:
        seed (str): The seed string to generate the UUID from.

    Returns:
        str: A deterministic UUID5 string.
    """
    if seed is None:
        return str(uuid4())
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, seed))


def generate_id_from_name(name: Optional[str] = None) -> str:
    """
    Generate a deterministic ID from a name string.
    If no name is provided, generate a random UUID4.

    Args:
        name (str): The name string to generate the ID from.
    """
    if name:
        return name.lower().replace(" ", "-").replace("_", "-")
    else:
        return str(uuid4())


def sanitize_postgres_string(value: Optional[str]) -> Optional[str]:
    """Remove illegal chars from string values to prevent PostgreSQL encoding errors.

    This function all chars illegal in Postgres UTF-8 text fields.
    Useful to prevent CharacterNotInRepertoireError when storing strings.

    Args:
        value: The string value to sanitize.

    Returns:
        The sanitized string with illegal chars removed, or None if input was None.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return POSTGRES_INVALID_CHARS_REGEX.sub("", value)


def sanitize_postgres_strings(data: Union[dict, list, str, Any]) -> Union[dict, list, str, Any]:
    """Recursively sanitize all string values in a dictionary or JSON structure.

    This function traverses dictionaries, lists, and nested structures to find
    and sanitize all string values, removing null bytes that PostgreSQL cannot handle.

    Args:
        data: The data structure to sanitize (dict, list, str or any other type).

    Returns:
        The sanitized data structure with all strings cleaned of null bytes.
    """
    if isinstance(data, dict):
        return {key: sanitize_postgres_strings(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [sanitize_postgres_strings(item) for item in data]
    elif isinstance(data, str):
        return sanitize_postgres_string(data)
    else:
        return data
