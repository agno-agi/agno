import json
from typing import Any, Callable, Dict, Optional, TypeVar

from agno.models.response import ToolExecution
from agno.utils.log import log_debug, log_error

from agno.banavo.tools import Function, FunctionCall

T = TypeVar("T")


def get_function_call(
    name: str,
    arguments: Optional[str] = None,
    call_id: Optional[str] = None,
    functions: Optional[Dict[str, Function]] = None,
) -> Optional[FunctionCall]:
    if functions is None:
        return None

    function_to_call: Optional[Function] = None
    if name in functions:
        function_to_call = functions[name]
    if function_to_call is None:
        log_error(f"Function {name} not found")
        return None

    function_call = FunctionCall(function=function_to_call)
    if call_id is not None:
        function_call.call_id = call_id
    if arguments is not None and arguments != "":
        try:
            try:
                _arguments = json.loads(arguments)
            except Exception:
                import ast

                _arguments = ast.literal_eval(arguments)
        except Exception as e:
            log_error(f"Unable to decode function arguments:\n{arguments}\nError: {e}")
            function_call.error = (
                f"Error while decoding function arguments: {e}\n\n"
                f"Please make sure we can json.loads() the arguments and retry."
            )
            return function_call

        if not isinstance(_arguments, dict):
            log_error(f"Function arguments are not a valid JSON object: {arguments}")
            function_call.error = "Function arguments are not a valid JSON object.\n\n Please fix and retry."
            return function_call

        try:
            clean_arguments: Dict[str, Any] = {}
            for k, v in _arguments.items():
                if isinstance(v, str):
                    _v = v.strip().lower()
                    if _v in ("none", "null"):
                        clean_arguments[k] = None
                    elif _v == "true":
                        clean_arguments[k] = True
                    elif _v == "false":
                        clean_arguments[k] = False
                    else:
                        clean_arguments[k] = v.strip()
                else:
                    clean_arguments[k] = v

            function_call.arguments = clean_arguments
        except Exception as e:
            log_error(f"Unable to parsing function arguments:\n{arguments}\nError: {e}")
            function_call.error = f"Error while parsing function arguments: {e}\n\n Please fix and retry."
            return function_call
    return function_call


def cache_result(enable_cache: bool = True, cache_dir: Optional[str] = None, cache_ttl: int = 3600):
    """
    Decorator factory that creates a file-based caching decorator for function results.

    Args:
        enable_cache (bool): Enable caching of function results.
        cache_dir (Optional[str]): Directory to store cache files. Defaults to system temp dir.
        cache_ttl (int): Time-to-live for cached results in seconds.

    Returns:
        A decorator function that caches results on the filesystem.
    """
    import functools
    import hashlib
    import json
    import os
    import tempfile
    import time

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # First argument might be 'self' but we don't need to handle it specially
            instance = args[0] if args else None

            # Skip caching if cache_results is False (only for class methods)
            if instance and hasattr(instance, "cache_results") and not instance.cache_results:
                return func(*args, **kwargs)

            if not enable_cache:
                return func(*args, **kwargs)

            # Get cache directory
            instance_cache_dir = (
                getattr(instance, "cache_dir", cache_dir) if hasattr(instance, "cache_dir") else cache_dir
            )
            base_cache_dir = instance_cache_dir or os.path.join(tempfile.gettempdir(), "agno_cache")

            # Create cache directory if it doesn't exist
            func_cache_dir = os.path.join(base_cache_dir, func.__module__, func.__qualname__)
            os.makedirs(func_cache_dir, exist_ok=True)

            # Create a cache key using all arguments
            # Convert args and kwargs to strings and join them
            args_str = str(args)
            kwargs_str = str(sorted(kwargs.items()))

            # Create a hash for potentially large input
            key_str = f"{func.__module__}.{func.__qualname__}:{args_str}:{kwargs_str}"
            cache_key = hashlib.md5(key_str.encode()).hexdigest()

            # Define cache file path
            cache_file = os.path.join(func_cache_dir, f"{cache_key}.json")

            # Check for cached result
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r") as f:
                        cache_data = json.load(f)

                    timestamp = cache_data.get("timestamp", 0)
                    result = cache_data.get("result")

                    # Use instance ttl if available, otherwise use decorator ttl
                    effective_ttl = (
                        getattr(instance, "cache_ttl", cache_ttl) if hasattr(instance, "cache_ttl") else cache_ttl
                    )

                    if time.time() - timestamp <= effective_ttl:
                        log_debug(f"Cache hit for: {func.__name__}")
                        return result

                    # Remove expired entry
                    os.remove(cache_file)
                except Exception as e:
                    log_error(f"Error reading cache: {e}")
                    # Continue with function execution if cache read fails

            # Execute the function and cache the result
            result = func(*args, **kwargs)

            try:
                with open(cache_file, "w") as f:
                    json.dump({"timestamp": time.time(), "result": result}, f)
            except Exception as e:
                log_error(f"Error writing cache: {e}")
                # Continue even if cache write fails

            return result

        return wrapper

    return decorator


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


def get_function_call_for_tool_call(
    tool_call: Dict[str, Any], functions: Optional[Dict[str, Function]] = None
) -> Optional[FunctionCall]:
    if tool_call.get("type") == "function":
        _tool_call_id = tool_call.get("id")
        _tool_call_function = tool_call.get("function")
        if _tool_call_function is not None:
            _tool_call_function_name = _tool_call_function.get("name")
            _tool_call_function_arguments_str = _tool_call_function.get("arguments")
            if _tool_call_function_name is not None:
                return get_function_call(
                    name=_tool_call_function_name,
                    arguments=_tool_call_function_arguments_str,
                    call_id=_tool_call_id,
                    functions=functions,
                )
    return None


import json
import re
from typing import Optional, Type

from agno.utils.log import logger
from pydantic import BaseModel, ValidationError


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
            logger.warning(f"Failed to parse cleaned JSON: {e} from content: {content}")

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
