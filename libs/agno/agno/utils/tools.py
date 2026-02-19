from typing import Any, Dict, List, Optional

from agno.models.response import ToolExecution
from agno.tools.function import Function, FunctionCall
from agno.utils.functions import get_function_call
from agno.utils.log import log_warning

# Maximum allowed length for tool function names (Azure OpenAI limit)
MAX_FUNCTION_NAME_LENGTH = 64


def _detect_repeating_pattern(name: str) -> Optional[str]:
    """Detect if a string is formed by repeating a shorter substring.

    For example:
        "SearchAgnoSearchAgnoSearchAgno" -> "SearchAgno"
        "abcabc" -> "abc"
        "hello" -> None (no repetition)

    Returns the base pattern if found, otherwise None.
    """
    length = len(name)
    # Try pattern lengths from 1 to half the string length
    for pattern_len in range(1, length // 2 + 1):
        pattern = name[:pattern_len]
        # Check if the entire string is composed of this pattern repeated
        if pattern_len > 0 and length % pattern_len == 0:
            repetitions = length // pattern_len
            if pattern * repetitions == name:
                return pattern
        # Also check if the string starts with the pattern repeated at least twice
        # (handles cases where the repetition is truncated, e.g. "SearchAgnoSearchAgnoSear")
        elif length > pattern_len * 2:
            if name[: pattern_len * 2] == pattern * 2:
                return pattern
    return None


def sanitize_function_name(name: str) -> str:
    """Sanitize a tool function name to comply with API constraints.

    When models enter a repetition loop during tool calling, the function name
    can become extremely long (e.g., "SearchAgnoSearchAgno..." repeated many
    times). Azure OpenAI enforces a maximum function name length of 64 characters,
    which causes a 400 Bad Request error.

    This function:
    1. Detects repetition patterns and extracts the base name
    2. Truncates to MAX_FUNCTION_NAME_LENGTH (64) characters if still too long

    Args:
        name: The function name to sanitize.

    Returns:
        The sanitized function name, guaranteed to be <= 64 characters.
    """
    if len(name) <= MAX_FUNCTION_NAME_LENGTH:
        return name

    original_name = name

    # Try to detect a repeating pattern and extract the base name
    base_pattern = _detect_repeating_pattern(name)
    if base_pattern is not None:
        name = base_pattern

    # Final safety: truncate to max length if still too long
    if len(name) > MAX_FUNCTION_NAME_LENGTH:
        name = name[:MAX_FUNCTION_NAME_LENGTH]

    log_warning(
        f"Tool function name exceeded {MAX_FUNCTION_NAME_LENGTH} chars "
        f"(was {len(original_name)}), sanitized to: '{name}'"
    )
    return name


def sanitize_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sanitize function names in a list of tool call dicts.

    Applies sanitize_function_name to each tool call's function name to guard
    against names that exceed 64 characters (Azure OpenAI limit).

    Args:
        tool_calls: List of tool call dictionaries.

    Returns:
        The same list with function names sanitized in-place.
    """
    for tool_call in tool_calls:
        func = tool_call.get("function")
        if func and isinstance(func, dict):
            func_name = func.get("name")
            if func_name and isinstance(func_name, str):
                func["name"] = sanitize_function_name(func_name)
    return tool_calls


def get_function_call_for_tool_call(
    tool_call: Dict[str, Any], functions: Optional[Dict[str, Function]] = None
) -> Optional[FunctionCall]:
    if tool_call.get("type") == "function":
        _tool_call_id = tool_call.get("id")
        _tool_call_function = tool_call.get("function")
        if _tool_call_function is not None:
            _tool_call_function_name = _tool_call_function.get("name")
            _tool_call_function_arguments_str = _tool_call_function.get("arguments") or "{}"
            if _tool_call_function_name is not None:
                return get_function_call(
                    name=_tool_call_function_name,
                    arguments=_tool_call_function_arguments_str,
                    call_id=_tool_call_id,
                    functions=functions,
                )
    return None


def extract_tool_call_from_string(text: str, start_tag: str = "<tool_call>", end_tag: str = "</tool_call>"):
    start_index = text.find(start_tag) + len(start_tag)
    end_index = text.find(end_tag)

    # Extracting the content between the tags
    return text[start_index:end_index].strip()


def remove_tool_calls_from_string(text: str, start_tag: str = "<tool_call>", end_tag: str = "</tool_call>"):
    """Remove multiple tool calls from a string."""
    while start_tag in text and end_tag in text:
        start_index = text.find(start_tag)
        end_index = text.find(end_tag) + len(end_tag)
        text = text[:start_index] + text[end_index:]
    return text


def extract_tool_from_xml(xml_str):
    # Find tool_name
    tool_name_start = xml_str.find("<tool_name>") + len("<tool_name>")
    tool_name_end = xml_str.find("</tool_name>")
    tool_name = xml_str[tool_name_start:tool_name_end].strip()

    # Find and process parameters block
    params_start = xml_str.find("<parameters>") + len("<parameters>")
    params_end = xml_str.find("</parameters>")
    parameters_block = xml_str[params_start:params_end].strip()

    # Extract individual parameters
    arguments = {}
    while parameters_block:
        # Find the next tag and its closing
        tag_start = parameters_block.find("<") + 1
        tag_end = parameters_block.find(">")
        tag_name = parameters_block[tag_start:tag_end]

        # Find the tag's closing counterpart
        value_start = tag_end + 1
        value_end = parameters_block.find(f"</{tag_name}>")
        value = parameters_block[value_start:value_end].strip()

        # Add to arguments
        arguments[tag_name] = value

        # Move past this tag
        parameters_block = parameters_block[value_end + len(f"</{tag_name}>") :].strip()

    return {"tool_name": tool_name, "parameters": arguments}


def remove_function_calls_from_string(
    text: str, start_tag: str = "<function_calls>", end_tag: str = "</function_calls>"
):
    """Remove multiple function calls from a string."""
    while start_tag in text and end_tag in text:
        start_index = text.find(start_tag)
        end_index = text.find(end_tag) + len(end_tag)
        text = text[:start_index] + text[end_index:]
    return text


def get_function_call_for_tool_execution(
    tool_execution: ToolExecution,
    functions: Optional[Dict[str, Function]] = None,
) -> Optional[FunctionCall]:
    import json

    _tool_call_id = tool_execution.tool_call_id
    _tool_call_function_name = tool_execution.tool_name or ""
    _tool_call_function_arguments_str = json.dumps(tool_execution.tool_args)
    return get_function_call(
        name=_tool_call_function_name,
        arguments=_tool_call_function_arguments_str,
        call_id=_tool_call_id,
        functions=functions,
    )
