import io
import json
from contextlib import redirect_stdout
from inspect import iscoroutinefunction, signature
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, Union

from agno.tools.function import Function, ToolResult
from agno.utils.code_execution import prepare_python_code
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.code_mode.tool import CodeMode


def make_wrapper(
    tool: "CodeMode",
    name: str,
    func: Function,
    media_collector: Optional[Dict[str, List[Any]]] = None,
    caller_loop: Any = None,
) -> Callable:
    from agno.code_mode.tool import FRAMEWORK_PARAMS

    param_names = [p for p in func.parameters.get("properties", {}).keys() if p not in FRAMEWORK_PARAMS]

    def wrapper(*args: Any, **kwargs: Any) -> str:
        entrypoint = func.entrypoint
        if entrypoint is None:
            return f"Error: Tool '{name}' has no entrypoint"

        for i, arg in enumerate(args):
            if i < len(param_names):
                kwargs[param_names[i]] = arg

        framework_args = get_framework_args(tool, entrypoint)

        if iscoroutinefunction(entrypoint):
            result = bridge_async(entrypoint, framework_args, kwargs, caller_loop=caller_loop)
        else:
            result = entrypoint(**framework_args, **kwargs)

        if isinstance(result, ToolResult):
            if media_collector is not None:
                collect_media(media_collector, result)
            return result.content
        if isinstance(result, (dict, list)):
            try:
                return json.dumps(result)
            except (TypeError, ValueError):
                return str(result)
        return str(result) if result is not None else ""

    wrapper.__name__ = name
    wrapper.__doc__ = func.description
    return wrapper


def get_framework_args(tool: "CodeMode", entrypoint: Callable) -> Dict[str, Any]:
    args: Dict[str, Any] = {}
    run_code_func = tool.functions.get("run_code")
    if run_code_func is None:
        return args

    try:
        sig = signature(entrypoint)
    except (ValueError, TypeError):
        return args

    param_names = set(sig.parameters.keys())
    from agno.code_mode.tool import FRAMEWORK_ARG_ATTRS

    for param, attr in FRAMEWORK_ARG_ATTRS.items():
        if param in param_names:
            args[param] = getattr(run_code_func, attr)
    return args


def bridge_async(
    entrypoint: Callable,
    framework_args: Dict[str, Any],
    user_kwargs: Dict[str, Any],
    caller_loop: Any = None,
) -> Any:
    import asyncio
    import concurrent.futures

    coro = entrypoint(**framework_args, **user_kwargs)

    if caller_loop is not None and caller_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, caller_loop)
        return future.result()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


def build_namespace(
    tool: "CodeMode",
    use_async: bool = False,
    media_collector: Optional[Dict[str, List[Any]]] = None,
    caller_loop: Any = None,
) -> Tuple[Dict[str, Any], Set[str]]:
    preapproved = dict(tool.PREAPPROVED_MODULES)
    preapproved.update(tool.additional_modules)

    _real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _restricted_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in preapproved:
            return preapproved[name]
        top_level = name.split(".")[0]
        if top_level in tool.BLOCKED_MODULES:
            raise ImportError(f"Import of '{name}' is not allowed.")
        return _real_import(name, *args, **kwargs)

    builtins_dict = dict(tool.safe_builtins)
    builtins_dict["__import__"] = _restricted_import
    # Required for class definitions inside exec()
    builtins_dict["__build_class__"] = (
        __builtins__["__build_class__"] if isinstance(__builtins__, dict) else __builtins__.__build_class__
    )

    namespace: Dict[str, Any] = {"__builtins__": builtins_dict, "__name__": "__sandbox__"}
    namespace.update(preapproved)

    functions = tool.sandbox_async_functions if use_async else tool.sandbox_functions
    for name, func in functions.items():
        if name in preapproved:
            log_warning(f"CodeMode: Tool '{name}' shadows pre-imported module '{name}'")
        wrapper = make_wrapper(tool, name, func, media_collector=media_collector, caller_loop=caller_loop)
        namespace[name] = wrapper

    base_keys = set(namespace.keys())
    return namespace, base_keys


def _unwrap_tool_result(value: Any, media_collector: Optional[Dict[str, List[Any]]]) -> Optional[str]:
    if isinstance(value, ToolResult):
        if media_collector is not None:
            collect_media(media_collector, value)
        return value.content
    return None


def extract_result(
    namespace: Dict[str, Any],
    stdout: str,
    base_keys: Set[str],
    return_variable: str,
    media_collector: Optional[Dict[str, List[Any]]] = None,
) -> str:
    result = namespace.get(return_variable)
    output_parts: List[str] = []
    unwrapped = _unwrap_tool_result(result, media_collector)
    if unwrapped is not None:
        output_parts.append(unwrapped)
    elif result is not None:
        output_parts.append(str(result))
    if stdout:
        output_parts.append(stdout.strip())
    if output_parts:
        return "\n".join(output_parts)

    user_vars = {k: v for k, v in namespace.items() if k not in base_keys and not k.startswith("_")}
    if user_vars:
        last_value = list(user_vars.values())[-1]
        unwrapped = _unwrap_tool_result(last_value, media_collector)
        if unwrapped is not None:
            return unwrapped
        return str(last_value)

    return f"Code executed successfully but produced no output. Set a `{return_variable}` variable or use print()."


def execute_code(
    tool: "CodeMode",
    code: str,
    use_async: bool = False,
    caller_loop: Any = None,
) -> Union[str, ToolResult]:
    try:
        if len(code) > tool.max_code_length:
            return f"{tool.EXEC_ERROR_PREFIX}Code exceeds maximum length of {tool.max_code_length} characters."

        code = prepare_python_code(code)
        log_debug(f"CodeMode executing:\n{code}")

        media_collector: Dict[str, List[Any]] = {"images": [], "videos": [], "audios": [], "files": []}
        namespace, base_keys = build_namespace(
            tool, use_async=use_async, media_collector=media_collector, caller_loop=caller_loop
        )

        stdout_buf = io.StringIO()
        with redirect_stdout(stdout_buf):
            exec(code, namespace)

        output = extract_result(
            namespace, stdout_buf.getvalue(), base_keys, tool.return_variable, media_collector=media_collector
        )
        if any(media_collector.values()):
            return ToolResult(
                content=output,
                images=media_collector["images"] or None,
                videos=media_collector["videos"] or None,
                audios=media_collector["audios"] or None,
                files=media_collector["files"] or None,
            )
        return output
    except SyntaxError as e:
        return f"{tool.EXEC_ERROR_PREFIX}SyntaxError: {e}"
    except Exception as e:
        return f"{tool.EXEC_ERROR_PREFIX}{type(e).__name__}: {e}"


def collect_media(collector: Dict[str, List[Any]], tool_result: ToolResult) -> None:
    if tool_result.images:
        collector["images"].extend(tool_result.images)
    if tool_result.videos:
        collector["videos"].extend(tool_result.videos)
    if tool_result.audios:
        collector["audios"].extend(tool_result.audios)
    if tool_result.files:
        collector["files"].extend(tool_result.files)
