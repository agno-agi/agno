import builtins as _builtins_mod
import collections as _collections_mod
import datetime as _datetime_mod
import io
import json as _json_mod
import math as _math_mod
import re
from collections import OrderedDict
from contextlib import redirect_stdout
from inspect import getdoc, iscoroutinefunction, signature
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, Union

from agno.tools.function import Function, ToolResult
from agno.tools.toolkit import Toolkit
from agno.utils.code_execution import prepare_python_code
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.models.base import Model

_DEFAULT_ALLOWED_BUILTINS: Set[str] = {
    "len",
    "min",
    "max",
    "sum",
    "sorted",
    "reversed",
    "range",
    "enumerate",
    "zip",
    "map",
    "filter",
    "any",
    "all",
    "str",
    "int",
    "float",
    "bool",
    "dict",
    "list",
    "set",
    "tuple",
    "round",
    "abs",
    "print",
    "isinstance",
    "type",
    "format",
    "pow",
    "divmod",
    "ord",
    "chr",
    "hex",
    "bin",
    "oct",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "Exception",
    "True",
    "False",
    "None",
}

_JSON_TYPE_MAP: Dict[str, str] = {
    "string": "str",
    "number": "float",
    "integer": "int",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}

_FRAMEWORK_PARAMS: Set[str] = {
    "self",
    "agent",
    "team",
    "run_context",
    "fc",
    "images",
    "videos",
    "audios",
    "files",
}

_EXEC_ERROR_PREFIX = "[[EXEC_ERROR]] "

_BLOCKED_MODULES: Set[str] = {
    "os",
    "sys",
    "subprocess",
    "shutil",
    "socket",
    "http",
    "urllib",
    "requests",
    "pathlib",
    "io",
    "builtins",
    "importlib",
    "ctypes",
    "multiprocessing",
    "threading",
    "signal",
    "code",
    "codeop",
    "compileall",
    "runpy",
    "inspect",
    "gc",
    "traceback",
}

_CODE_MODEL_SYSTEM = (
    "You are a Python code generator. Write a SINGLE complete Python program "
    "that accomplishes the user's task by calling the provided tool functions.\n\n"
    "RULES:\n"
    "- Call functions DIRECTLY: get_stock_price(symbol='AAPL'), NOT module.func().\n"
    "- `json`, `math`, `datetime`, `re`, and `collections` are pre-imported. Do NOT write import statements.\n"
    "- All tool functions return JSON strings. Use json.loads() to parse them.\n"
    "- Store your final answer in a variable called `result` (as a formatted string).\n"
    "- Handle errors with try/except where appropriate.\n"
    "- Output ONLY the Python code inside a ```python code fence. No explanation.\n\n"
    "AVAILABLE FUNCTIONS:\n\n"
)

_DEFAULT_CODE_MODE_INSTRUCTIONS = (
    "You have access to a code execution environment via the `run_code` tool.\n"
    "Write ONE complete Python program per call that handles the entire task.\n"
    "Call tool functions DIRECTLY by name (e.g., get_stock_price(symbol='AAPL')).\n"
    "`json`, `math`, `datetime`, `re`, and `collections` are pre-imported. Do NOT write import statements.\n"
    "All tool functions return JSON strings — use json.loads() to parse results.\n"
    "Store your final answer in a variable called `result` as a formatted string.\n"
    "Use loops to process multiple items efficiently in a single call."
)

_DEFAULT_CODE_MODEL_INSTRUCTIONS = (
    "You have access to a `run_code` tool that accepts plain English task descriptions.\n"
    "A specialized code model generates and executes the code for you.\n"
    "Describe what data to fetch, what computations to perform, and the desired output format.\n"
    "You do NOT need to write code yourself."
)


class _SafeCallable:
    __slots__ = ("_fn", "__name__", "__doc__")

    def __init__(self, fn: Callable, name: str, doc: Optional[str]):
        self._fn = fn
        self.__name__ = name
        self.__doc__ = doc or ""

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        return self._fn(*args, **kwargs)

    def __repr__(self) -> str:
        return f"<tool {self.__name__}>"


class CodeModeTool(Toolkit):
    def __init__(
        self,
        tools: List[Union["Toolkit", Callable, Function]],
        *,
        code_model: Optional["Model"] = None,
        max_code_retries: int = 3,
        discovery: Union[bool, str] = "auto",
        discovery_threshold: int = 15,
        additional_modules: Optional[Dict[str, Any]] = None,
        return_variable: str = "result",
        max_code_length: int = 10_000,
        allowed_builtins: Optional[Set[str]] = None,
        **kwargs: Any,
    ):
        self._source_tools = tools
        self._code_model = code_model
        self._max_code_retries = max_code_retries
        self._return_variable = return_variable
        self._max_code_length = max_code_length
        self._discovery_threshold = discovery_threshold
        self._additional_modules: Dict[str, Any] = additional_modules or {}

        allowed = allowed_builtins or _DEFAULT_ALLOWED_BUILTINS
        self._safe_builtins: Dict[str, Any] = {
            k: getattr(_builtins_mod, k) for k in allowed if hasattr(_builtins_mod, k)
        }

        self._sync_functions: Dict[str, Function] = self._collect_functions(tools, async_mode=False)
        self._async_functions: Dict[str, Function] = self._collect_functions(tools, async_mode=True)

        self._stub_map: Dict[str, str] = self._generate_stub_map(self._sync_functions)
        self._stubs = "\n\n".join(self._stub_map.values())

        self._discovery_enabled = self._resolve_discovery(discovery)
        self._catalog = self._generate_catalog() if (self._discovery_enabled or self._code_model is not None) else ""
        self._sync_stubs_injected = False
        self._async_stubs_injected = False

        tools_list, async_tools_list = self._build_registration_lists()
        super().__init__(
            name="code_mode",
            tools=tools_list,
            async_tools=async_tools_list,
            **kwargs,
        )

        if self._code_model is not None:
            self.instructions = _DEFAULT_CODE_MODEL_INSTRUCTIONS
        else:
            self.instructions = _DEFAULT_CODE_MODE_INSTRUCTIONS
        self.add_instructions = True

    def _resolve_discovery(self, discovery: Union[bool, str]) -> bool:
        # code_model handles its own dispatch — no discovery needed
        if self._code_model is not None:
            return False
        if discovery == "auto":
            return len(self._sync_functions) > self._discovery_threshold
        if isinstance(discovery, bool):
            return discovery
        raise ValueError(f"discovery must be True, False, or 'auto', got {discovery!r}")

    def _build_registration_lists(self) -> Tuple[list, list]:
        if self._code_model is not None:
            return [self.run_code], [(self.arun_code, "run_code")]
        if self._discovery_enabled:
            return (
                [self.search_tools, self.run_code],
                [(self.asearch_tools, "search_tools"), (self.arun_code, "run_code")],
            )
        return [self.run_code], [(self.arun_code, "run_code")]

    def _collect_functions(
        self,
        tools: List[Union["Toolkit", Callable, Function]],
        async_mode: bool = False,
    ) -> Dict[str, Function]:
        collected: Dict[str, Function] = OrderedDict()
        for tool in tools:
            if isinstance(tool, Toolkit):
                toolkit_funcs = tool.get_async_functions() if async_mode else tool.get_functions()
                for name, func in toolkit_funcs.items():
                    if self._should_include(func):
                        func = func.model_copy(deep=True)
                        if not func.skip_entrypoint_processing:
                            func.process_entrypoint()
                        collected[name] = func
            elif isinstance(tool, Function):
                if self._should_include(tool):
                    tool = tool.model_copy(deep=True)
                    if not tool.skip_entrypoint_processing:
                        tool.process_entrypoint()
                    collected[tool.name] = tool
            elif callable(tool):
                func = Function.from_callable(tool)
                if self._should_include(func):
                    collected[func.name] = func
        return collected

    def _should_include(self, func: Function) -> bool:
        for attr in ("requires_confirmation", "requires_user_input", "external_execution"):
            if getattr(func, attr, None):
                log_warning(f"CodeModeTool: Excluding '{func.name}' ({attr})")
                return False
        return True

    def _generate_stub_map(self, functions: Dict[str, Function]) -> Dict[str, str]:
        stub_map: Dict[str, str] = OrderedDict()
        for name, func in functions.items():
            params = func.parameters.get("properties", {})
            required = set(func.parameters.get("required", []))

            args: List[str] = []
            for pname, schema in params.items():
                if pname in _FRAMEWORK_PARAMS:
                    continue
                py_type = _JSON_TYPE_MAP.get(schema.get("type", "string"), "Any")
                if pname in required:
                    args.append(f"{pname}: {py_type}")
                else:
                    default = schema.get("default")
                    args.append(f"{pname}: {py_type} = {default!r}")

            doc = func.description or "No description"
            if func.entrypoint is not None:
                full_doc = getdoc(func.entrypoint)
                if full_doc:
                    doc = full_doc

            sig = ", ".join(args)
            stub = f"def {name}({sig}) -> str:\n"
            stub += f'    """{doc}\n    """'
            stub_map[name] = stub
        return stub_map

    def _generate_catalog(self) -> str:
        lines = []
        for name, func in self._sync_functions.items():
            desc = func.description or "No description"
            first_line = desc.split("\n")[0][:100]
            lines.append(f"- {name}: {first_line}")
        return "\n".join(lines)

    def _inject_sync_stubs(self, funcs: Dict[str, Function]) -> None:
        if self._sync_stubs_injected:
            return
        self._inject_stubs_into(funcs)
        self._sync_stubs_injected = True

    def _inject_async_stubs(self, funcs: Dict[str, Function]) -> None:
        if self._async_stubs_injected:
            return
        self._inject_stubs_into(funcs)
        self._async_stubs_injected = True

    def _inject_stubs_into(self, funcs: Dict[str, Function]) -> None:
        run_code_func = funcs.get("run_code")
        if run_code_func is None:
            return

        if self._code_model is not None:
            run_code_func.description = (
                "Execute a task by describing what you need done in plain English.\n\n"
                "A specialized code-generation model will write and execute Python code "
                "that calls the available tools. You do NOT need to write code yourself.\n\n"
                "Just describe the task clearly, including:\n"
                "- What data to fetch\n"
                "- What computations to perform\n"
                "- What format you want the result in\n\n"
                "Available tools:\n\n" + self._catalog
            )
        elif self._discovery_enabled:
            base = run_code_func.description or ""
            run_code_func.description = (
                base + "\n\nAvailable tools (use search_tools for full signatures):\n\n" + self._catalog
            )
        else:
            base = run_code_func.description or ""
            run_code_func.description = base + "\n\nAvailable functions:\n\n" + self._stubs

    def get_functions(self) -> Dict[str, Function]:
        funcs = super().get_functions()
        self._inject_sync_stubs(funcs)
        return funcs

    def get_async_functions(self) -> Dict[str, Function]:
        funcs = super().get_async_functions()
        self._inject_async_stubs(funcs)
        return funcs

    def _make_wrapper(
        self,
        name: str,
        func: Function,
        media_collector: Optional[Dict[str, List[Any]]] = None,
    ) -> Callable:
        code_mode_tool = self
        param_names = [p for p in func.parameters.get("properties", {}).keys() if p not in _FRAMEWORK_PARAMS]

        def wrapper(*args: Any, **kwargs: Any) -> str:
            entrypoint = func.entrypoint
            if entrypoint is None:
                return f"Error: Tool '{name}' has no entrypoint"

            for i, arg in enumerate(args):
                if i < len(param_names):
                    kwargs[param_names[i]] = arg

            framework_args = code_mode_tool._get_framework_args(entrypoint)

            if iscoroutinefunction(entrypoint):
                result = code_mode_tool._bridge_async(entrypoint, framework_args, kwargs)
            else:
                result = entrypoint(**framework_args, **kwargs)

            if isinstance(result, ToolResult):
                if media_collector is not None:
                    code_mode_tool._collect_tool_result_media(media_collector, result)
                return result.content
            if isinstance(result, (dict, list)):
                try:
                    return _json_mod.dumps(result)
                except (TypeError, ValueError):
                    return str(result)
            return str(result) if result is not None else ""

        wrapper.__name__ = name
        wrapper.__doc__ = func.description
        return wrapper

    def _get_framework_args(self, entrypoint: Callable) -> Dict[str, Any]:
        args: Dict[str, Any] = {}
        run_code_func = self.functions.get("run_code")
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

    def _bridge_async(self, entrypoint: Callable, framework_args: Dict, user_kwargs: Dict) -> Any:
        import asyncio
        import concurrent.futures

        coro = entrypoint(**framework_args, **user_kwargs)

        # When running inside run_in_executor (from arun_code), _caller_loop
        # points to the original event loop which is free to process coroutines.
        # This is required for MCP tools whose sessions are bound to that loop.
        caller_loop = getattr(self, "_caller_loop", None)
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

    def _build_namespace(
        self,
        use_async: bool = False,
        media_collector: Optional[Dict[str, List[Any]]] = None,
    ) -> Tuple[Dict[str, Any], Set[str]]:
        preapproved: Dict[str, Any] = {
            "json": _json_mod,
            "math": _math_mod,
            "datetime": _datetime_mod,
            "re": re,
            "collections": _collections_mod,
        }
        preapproved.update(self._additional_modules)

        _real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def _restricted_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name in preapproved:
                return preapproved[name]
            top_level = name.split(".")[0]
            if top_level in _BLOCKED_MODULES:
                raise ImportError(f"Import of '{name}' is not allowed.")
            return _real_import(name, *args, **kwargs)

        builtins_dict = dict(self._safe_builtins)
        builtins_dict["__import__"] = _restricted_import

        namespace: Dict[str, Any] = {"__builtins__": builtins_dict}
        namespace.update(preapproved)

        functions = self._async_functions if use_async else self._sync_functions
        for name, func in functions.items():
            wrapper = self._make_wrapper(name, func, media_collector=media_collector)
            namespace[name] = _SafeCallable(wrapper, name, func.description)

        base_keys = set(namespace.keys())
        return namespace, base_keys

    def _extract_result(
        self,
        namespace: Dict[str, Any],
        stdout: str,
        base_keys: Set[str],
        media_collector: Optional[Dict[str, List[Any]]] = None,
    ) -> str:
        result = namespace.get(self._return_variable)
        output_parts: List[str] = []
        if isinstance(result, ToolResult):
            if media_collector is not None:
                self._collect_tool_result_media(media_collector, result)
            output_parts.append(result.content)
        elif result is not None:
            output_parts.append(str(result))
        if stdout:
            output_parts.append(stdout.strip())
        if output_parts:
            return "\n".join(output_parts)

        # Fallback: return last user-defined variable
        user_vars = {k: v for k, v in namespace.items() if k not in base_keys and not k.startswith("_")}
        if user_vars:
            last_value = list(user_vars.values())[-1]
            if isinstance(last_value, ToolResult):
                if media_collector is not None:
                    self._collect_tool_result_media(media_collector, last_value)
                return last_value.content
            return str(last_value)

        return (
            f"Code executed successfully but produced no output. "
            f"Set a `{self._return_variable}` variable or use print()."
        )

    def _execute_code(self, code: str, use_async: bool = False) -> Union[str, ToolResult]:
        try:
            if len(code) > self._max_code_length:
                return f"{_EXEC_ERROR_PREFIX}Code exceeds maximum length of {self._max_code_length} characters."

            code = prepare_python_code(code)
            log_debug(f"CodeModeTool executing:\n{code}")

            media_collector: Dict[str, List[Any]] = {"images": [], "videos": [], "audios": [], "files": []}
            namespace, base_keys = self._build_namespace(use_async=use_async, media_collector=media_collector)

            stdout_buf = io.StringIO()
            with redirect_stdout(stdout_buf):
                exec(code, namespace)

            output = self._extract_result(namespace, stdout_buf.getvalue(), base_keys, media_collector=media_collector)
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
            return f"{_EXEC_ERROR_PREFIX}SyntaxError: {e}"
        except Exception as e:
            return f"{_EXEC_ERROR_PREFIX}{type(e).__name__}: {e}"

    def rebuild(self) -> None:
        self._sync_functions = self._collect_functions(self._source_tools, async_mode=False)
        self._async_functions = self._collect_functions(self._source_tools, async_mode=True)

        self._stub_map = self._generate_stub_map(self._sync_functions)
        self._stubs = "\n\n".join(self._stub_map.values())

        if self._discovery_enabled or self._code_model is not None:
            self._catalog = self._generate_catalog()

        self._sync_stubs_injected = False
        self._async_stubs_injected = False

    @staticmethod
    def _extract_code_block(text: str) -> str:
        m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        return text.strip()

    def _generate_code(self, task: str, error: Optional[str] = None) -> str:
        from agno.models.message import Message

        system = _CODE_MODEL_SYSTEM + self._stubs
        user_content = task
        if error:
            user_content += f"\n\nPrevious attempt failed with:\n{error}\n\nFix the code and try again."

        messages = [
            Message(role="system", content=system),
            Message(role="user", content=user_content),
        ]
        response = self._code_model.response(messages=messages)  # type: ignore[union-attr]
        return self._extract_code_block(response.content or "")

    async def _agenerate_code(self, task: str, error: Optional[str] = None) -> str:
        from agno.models.message import Message

        system = _CODE_MODEL_SYSTEM + self._stubs
        user_content = task
        if error:
            user_content += f"\n\nPrevious attempt failed with:\n{error}\n\nFix the code and try again."

        messages = [
            Message(role="system", content=system),
            Message(role="user", content=user_content),
        ]
        response = await self._code_model.aresponse(messages=messages)  # type: ignore[union-attr]
        return self._extract_code_block(response.content or "")

    def _run_with_code_model(self, task: str, use_async: bool = False) -> Union[str, ToolResult]:
        last_error: Optional[str] = None
        for attempt in range(self._max_code_retries):
            code = self._generate_code(task, error=last_error)
            log_debug(f"CodeModeTool code_model attempt {attempt + 1}:\n{code}")
            result = self._execute_code(code, use_async=use_async)
            if isinstance(result, ToolResult):
                return result
            if not result.startswith(_EXEC_ERROR_PREFIX):
                return result
            last_error = result[len(_EXEC_ERROR_PREFIX) :]
            log_debug(f"CodeModeTool code_model attempt {attempt + 1} failed: {last_error}")
        return f"Code generation failed after {self._max_code_retries} attempts. Last error: {last_error}"

    async def _arun_with_code_model(self, task: str, use_async: bool = True) -> Union[str, ToolResult]:
        import asyncio

        loop = asyncio.get_running_loop()
        self._caller_loop = loop
        try:
            last_error: Optional[str] = None
            for attempt in range(self._max_code_retries):
                code = await self._agenerate_code(task, error=last_error)
                log_debug(f"CodeModeTool code_model attempt {attempt + 1}:\n{code}")
                result = await loop.run_in_executor(None, self._execute_code, code, use_async)
                if isinstance(result, ToolResult):
                    return result
                if not result.startswith(_EXEC_ERROR_PREFIX):
                    return result
                last_error = result[len(_EXEC_ERROR_PREFIX) :]
                log_debug(f"CodeModeTool code_model attempt {attempt + 1} failed: {last_error}")
            return f"Code generation failed after {self._max_code_retries} attempts. Last error: {last_error}"
        finally:
            self._caller_loop = None

    def search_tools(self, query: str) -> str:
        """Search available tool functions by keyword.

        Returns matching function signatures with parameter types and docstrings.
        Use this to discover what functions are available before writing code with run_code.

        Args:
            query: Search keyword (matches against function names and descriptions)

        Example:
            search_tools(query="stock price") -> returns stubs for price-related functions
        """
        if not query or len(query.strip()) < 2:
            return (
                f"Please provide a search query (at least 2 characters). "
                f"There are {len(self._stub_map)} functions available."
            )

        query_lower = query.lower().strip()
        matches = []
        for name, stub in self._stub_map.items():
            func = self._sync_functions.get(name)
            desc = (func.description or "").lower() if func else ""
            if query_lower in name.lower() or query_lower in desc:
                matches.append(stub)

        if not matches:
            return f"No functions found matching '{query}'. Try a broader search term."

        if len(matches) > 10:
            shown = matches[:10]
            return (
                f"Found {len(matches)} functions, showing first 10. "
                f"Use a more specific query to narrow results.\n\n" + "\n\n".join(shown)
            )

        return f"Found {len(matches)} function(s):\n\n" + "\n\n".join(matches)

    async def asearch_tools(self, query: str) -> str:
        return self.search_tools(query)

    def run_code(self, code: str) -> Union[str, ToolResult]:
        """Execute Python code that calls tool functions directly.

        RULES:
        - Call functions DIRECTLY: search(query="x"), NOT functions.search()
        - json and math are pre-imported. Do NOT write import statements.
        - All tool functions return JSON strings. Use json.loads() to parse them.
        - Store your final answer in a variable called `result` (as a string).
        - You can use: json, math, loops, conditionals, list comprehensions, try/except

        Example:
            data = json.loads(search(query="laptop"))
            details = json.loads(get_details(product_id=data[0]["id"]))
            result = f"Found: {details['name']} at ${details['price']}"
        """
        if self._code_model is not None:
            return self._run_with_code_model(code, use_async=False)
        result = self._execute_code(code, use_async=False)
        if isinstance(result, ToolResult):
            return result
        if result.startswith(_EXEC_ERROR_PREFIX):
            return result[len(_EXEC_ERROR_PREFIX) :]
        return result

    async def arun_code(self, code: str) -> Union[str, ToolResult]:
        if self._code_model is not None:
            return await self._arun_with_code_model(code, use_async=True)
        import asyncio

        loop = asyncio.get_running_loop()
        self._caller_loop = loop
        try:
            result = await loop.run_in_executor(None, self._execute_code, code, True)
        finally:
            self._caller_loop = None
        if isinstance(result, ToolResult):
            return result
        if result.startswith(_EXEC_ERROR_PREFIX):
            return result[len(_EXEC_ERROR_PREFIX) :]
        return result

    @staticmethod
    def _collect_tool_result_media(collector: Dict[str, List[Any]], tool_result: ToolResult) -> None:
        if tool_result.images:
            collector["images"].extend(tool_result.images)
        if tool_result.videos:
            collector["videos"].extend(tool_result.videos)
        if tool_result.audios:
            collector["audios"].extend(tool_result.audios)
        if tool_result.files:
            collector["files"].extend(tool_result.files)
