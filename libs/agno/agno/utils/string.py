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


def _parse_individual_json(content: str, response_model: Type[BaseModel]) -> Optional[BaseModel]:
    candidate_jsons = _extract_json_objects(content)
    merged_steps: list[dict] = []

    for candidate in candidate_jsons:
        try:
            candidate_obj = json.loads(candidate)
        except json.JSONDecodeError:
            # Try again after stripping newlines / carriage returns
            cleaned = candidate.replace("\n", " ").replace("\r", "")
            try:
                candidate_obj = json.loads(cleaned)
            except json.JSONDecodeError:
                continue

        if (
            isinstance(candidate_obj, dict)
            and "reasoning_steps" in candidate_obj
            and isinstance(candidate_obj["reasoning_steps"], list)
        ):
            merged_steps.extend(candidate_obj["reasoning_steps"])

    if not merged_steps:
        return None

    try:
        aggregate_obj = {"reasoning_steps": merged_steps}
        return response_model.model_validate(aggregate_obj)
    except ValidationError as e:
        logger.warning("Validation failed on merged ReasoningSteps: %s", e)
        return None


def parse_response_model_str(content: str, response_model: Type[BaseModel]) -> Optional[BaseModel]:
    logger.debug(f"Parsing response model: {content}")
    structured_output = None
    try:
        # First attempt: direct JSON validation
        structured_output = response_model.model_validate_json(content)
    except (ValidationError, json.JSONDecodeError):
        # Second attempt: Extract JSON from markdown code blocks and clean
        content = content

        # Handle code blocks
        if "```json" in content:
            content = content.split("```json")[-1].strip()
            parts = content.split("```")
            parts.pop(-1)
            content = "".join(parts)
        elif "```" in content:
            content = content.split("```")[1].strip()

        # Clean the JSON string
        # Remove markdown formatting
        content = re.sub(r"[*`#]", "", content)

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

            return f'"{key.lower()}": "{escaped_value}'

        # Find and escape quotes in field values
        content = re.sub(r'"(?P<key>[^"]+)"\s*:\s*"(?P<value>.*?)(?="\s*(?:,|\}))', escape_quotes_in_values, content)

        try:
            # Try parsing the cleaned JSON
            structured_output = response_model.model_validate_json(content)
        except (ValidationError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse cleaned JSON: {e}")

            try:
                # Final attempt: Try parsing as Python dict
                data = json.loads(content)
                structured_output = response_model.model_validate(data)
            except (ValidationError, json.JSONDecodeError) as e:
                logger.warning(f"Failed to parse as Python dict: {e}")

                try:
                    start = content.find("{")
                    end = content.rfind("}") + 1
                    if start != -1 and end != -1 and end > start:
                        trimmed = content[start:end]
                        data = json.loads(trimmed)
                        structured_output = response_model.model_validate(data)
                    else:
                        logger.warning("Unable to locate JSON object boundaries for fallback parsing.")
                except (ValidationError, json.JSONDecodeError) as e2:
                    logger.warning(f"Failed to parse after trimming: {e2}")
                    # Handle concatenated JSON objects (missing commas)
                    structured_output = _parse_individual_json(content, response_model)
                    if structured_output is None:
                        logger.warning("Multiple-object fallback parsing failed.")

    return structured_output
