import io
import json
from contextlib import redirect_stdout
from inspect import iscoroutinefunction, signature
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, Union

from agno.tools.function import Function, ToolResult
from agno.utils.code_execution import prepare_python_code
from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.code_mode.tool import CodeModeTool


class SafeCallable:
    __slots__ = ("_fn", "__name__", "__doc__")

    def __init__(self, fn: Callable, name: str, doc: Optional[str]):
        self._fn = fn
        self.__name__ = name
        self.__doc__ = doc or ""

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        return self._fn(*args, **kwargs)

    def __repr__(self) -> str:
        return f"<tool {self.__name__}>"


def make_wrapper(
    tool: "CodeModeTool",
    name: str,
    func: Function,
    media_collector: Optional[Dict[str, List[Any]]] = None,
) -> Callable:
    param_names = [p for p in func.parameters.get("properties", {}).keys() if p not in tool.framework_params]

    def wrapper(*args: Any, **kwargs: Any) -> str:
        entrypoint = func.entrypoint
        if entrypoint is None:
            return f"Error: Tool '{name}' has no entrypoint"

        for i, arg in enumerate(args):
            if i < len(param_names):
                kwargs[param_names[i]] = arg

        framework_args = get_framework_args(tool, entrypoint)

        if iscoroutinefunction(entrypoint):
            result = bridge_async(entrypoint, framework_args, kwargs, caller_loop=tool.caller_loop)
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


def get_framework_args(tool: "CodeModeTool", entrypoint: Callable) -> Dict[str, Any]:
    args: Dict[str, Any] = {}
    run_code_func = tool.functions.get("run_code")
    if run_code_func is None:
        return args

    try:
        sig = signature(entrypoint)
    except (ValueError, TypeError):
        return args

    param_names = set(sig.parameters.keys())
    if "agent" in param_names:
        args["agent"] = run_code_func._agent
    if "team" in param_names:
        args["team"] = run_code_func._team
    if "run_context" in param_names:
        args["run_context"] = run_code_func._run_context
    if "images" in param_names:
        args["images"] = run_code_func._images
    if "videos" in param_names:
        args["videos"] = run_code_func._videos
    if "audios" in param_names:
        args["audios"] = run_code_func._audios
    if "files" in param_names:
        args["files"] = run_code_func._files
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
    tool: "CodeModeTool",
    use_async: bool = False,
    media_collector: Optional[Dict[str, List[Any]]] = None,
) -> Tuple[Dict[str, Any], Set[str]]:
    preapproved = dict(tool.preapproved_modules)
    preapproved.update(tool.additional_modules)

    _real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    blocked_modules = tool.blocked_modules

    def _restricted_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in preapproved:
            return preapproved[name]
        top_level = name.split(".")[0]
        if top_level in blocked_modules:
            raise ImportError(f"Import of '{name}' is not allowed.")
        return _real_import(name, *args, **kwargs)

    builtins_dict = dict(tool.safe_builtins)
    builtins_dict["__import__"] = _restricted_import

    namespace: Dict[str, Any] = {"__builtins__": builtins_dict}
    namespace.update(preapproved)

    functions = tool.sandbox_async_functions if use_async else tool.sandbox_functions
    for name, func in functions.items():
        wrapper = make_wrapper(tool, name, func, media_collector=media_collector)
        namespace[name] = SafeCallable(wrapper, name, func.description)

    base_keys = set(namespace.keys())
    return namespace, base_keys


def extract_result(
    namespace: Dict[str, Any],
    stdout: str,
    base_keys: Set[str],
    return_variable: str,
    media_collector: Optional[Dict[str, List[Any]]] = None,
) -> str:
    result = namespace.get(return_variable)
    output_parts: List[str] = []
    if isinstance(result, ToolResult):
        if media_collector is not None:
            collect_media(media_collector, result)
        output_parts.append(result.content)
    elif result is not None:
        output_parts.append(str(result))
    if stdout:
        output_parts.append(stdout.strip())
    if output_parts:
        return "\n".join(output_parts)

    user_vars = {k: v for k, v in namespace.items() if k not in base_keys and not k.startswith("_")}
    if user_vars:
        last_value = list(user_vars.values())[-1]
        if isinstance(last_value, ToolResult):
            if media_collector is not None:
                collect_media(media_collector, last_value)
            return last_value.content
        return str(last_value)

    return f"Code executed successfully but produced no output. Set a `{return_variable}` variable or use print()."


def execute_code(
    tool: "CodeModeTool",
    code: str,
    use_async: bool = False,
) -> Union[str, ToolResult]:
    try:
        if len(code) > tool.max_code_length:
            return f"{tool.exec_error_prefix}Code exceeds maximum length of {tool.max_code_length} characters."

        code = prepare_python_code(code)
        log_debug(f"CodeModeTool executing:\n{code}")

        media_collector: Dict[str, List[Any]] = {"images": [], "videos": [], "audios": [], "files": []}
        namespace, base_keys = build_namespace(tool, use_async=use_async, media_collector=media_collector)

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
        return f"{tool.exec_error_prefix}SyntaxError: {e}"
    except Exception as e:
        return f"{tool.exec_error_prefix}{type(e).__name__}: {e}"


def collect_media(collector: Dict[str, List[Any]], tool_result: ToolResult) -> None:
    if tool_result.images:
        collector["images"].extend(tool_result.images)
    if tool_result.videos:
        collector["videos"].extend(tool_result.videos)
    if tool_result.audios:
        collector["audios"].extend(tool_result.audios)
    if tool_result.files:
        collector["files"].extend(tool_result.files)
