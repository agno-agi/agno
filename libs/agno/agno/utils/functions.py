import json
from typing import Any, Callable, Dict, Optional, TypeVar

from agno.tools.function import Function, FunctionCall
from agno.utils.log import log_debug, log_error

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
