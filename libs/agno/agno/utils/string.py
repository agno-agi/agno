import hashlib
import json
import re
from typing import Optional, Type

from pydantic import BaseModel, ValidationError

from agno.utils.log import logger


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


def safe_content_hash(content: str) -> str:
    """
    Return an MD5 hash of the input string, replacing null bytes and invalid surrogates for safe hashing.
    """
    cleaned_content = content.replace("\x00", "\ufffd")
    try:
        content_hash = hashlib.md5(cleaned_content.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        cleaned_content = "".join("\ufffd" if "\ud800" <= c <= "\udfff" else c for c in cleaned_content)
        content_hash = hashlib.md5(cleaned_content.encode("utf-8")).hexdigest()

    return content_hash


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


def _parse_individual_json(content: str, response_model: Type[BaseModel]) -> Optional[BaseModel]:
    """Parse individual JSON objects from content and merge them based on response model fields."""
    candidate_jsons = _extract_json_objects(content)
    merged_data: dict = {}

    # Get the expected fields from the response model
    model_fields = response_model.model_fields if hasattr(response_model, "model_fields") else {}

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
        return response_model.model_validate(merged_data)
    except ValidationError as e:
        logger.warning("Validation failed on merged data: %s", e)
        return None


def parse_response_model_str(content: str, response_model: Type[BaseModel]) -> Optional[BaseModel]:
    structured_output = None

    # Clean content first to simplify all parsing attempts
    cleaned_content = _clean_json_content(content)

    try:
        # First attempt: direct JSON validation on cleaned content
        structured_output = response_model.model_validate_json(cleaned_content)
    except (ValidationError, json.JSONDecodeError):
        try:
            # Second attempt: Parse as Python dict
            data = json.loads(cleaned_content)
            structured_output = response_model.model_validate(data)
        except (ValidationError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse cleaned JSON: {e}")

            # Third attempt: Extract individual JSON objects
            candidate_jsons = _extract_json_objects(cleaned_content)

            if len(candidate_jsons) == 1:
                # Single JSON object - try to parse it directly
                try:
                    data = json.loads(candidate_jsons[0])
                    structured_output = response_model.model_validate(data)
                except (ValidationError, json.JSONDecodeError):
                    pass

            if structured_output is None:
                # Final attempt: Handle concatenated JSON objects with field merging
                structured_output = _parse_individual_json(cleaned_content, response_model)
                if structured_output is None:
                    logger.warning("All parsing attempts failed.")

    return structured_output
