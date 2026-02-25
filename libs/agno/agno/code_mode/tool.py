import builtins
import collections
import datetime
import json
import math
import re
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Union

from agno.code_mode.sandbox import execute_code
from agno.code_mode.stubs import collect_functions, generate_catalog, generate_stub_map, resolve_discovery
from agno.tools import Toolkit
from agno.tools.function import Function, ToolResult
from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.models.base import Model


class CodeMode(Toolkit):
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
        **kwargs,
    ):
        self.source_tools = tools
        self.code_model = code_model
        if self.code_model is not None:
            from agno.metrics import ModelType

            self.code_model.model_type = ModelType.CODE_MODEL
        self.max_code_retries = max_code_retries
        self.return_variable = return_variable
        self.max_code_length = max_code_length
        self.discovery_threshold = discovery_threshold
        self.additional_modules: Dict[str, Any] = additional_modules or {}
        self.caller_loop: Any = None

        self.exec_error_prefix = "[[EXEC_ERROR]] "
        self.blocked_modules: Set[str] = {
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
        self.framework_params: Set[str] = {
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
        self.json_type_map: Dict[str, str] = {
            "string": "str",
            "number": "float",
            "integer": "int",
            "boolean": "bool",
            "array": "list",
            "object": "dict",
        }
        self.preapproved_modules: Dict[str, Any] = {
            "json": json,
            "math": math,
            "datetime": datetime,
            "re": re,
            "collections": collections,
        }
        self.code_model_system = (
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

        _default_builtins: Set[str] = {
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
            "AttributeError",
            "RuntimeError",
            "ZeroDivisionError",
            "StopIteration",
            "ArithmeticError",
            "LookupError",
            "OverflowError",
            "NotImplementedError",
            "Exception",
            "__build_class__",
            "True",
            "False",
            "None",
        }
        allowed = allowed_builtins or _default_builtins
        self.safe_builtins: Dict[str, Any] = {k: getattr(builtins, k) for k in allowed if hasattr(builtins, k)}

        self.sandbox_functions: Dict[str, Function] = collect_functions(tools, async_mode=False)
        self.sandbox_async_functions: Dict[str, Function] = collect_functions(tools, async_mode=True)

        self.stub_map: Dict[str, str] = generate_stub_map(
            self.sandbox_functions, self.framework_params, self.json_type_map
        )
        self.stubs = "\n\n".join(self.stub_map.values())

        self.discovery_enabled = resolve_discovery(
            self.code_model, discovery, len(self.sandbox_functions), self.discovery_threshold
        )
        self.catalog = (
            generate_catalog(self.sandbox_functions) if (self.discovery_enabled or self.code_model is not None) else ""
        )
        self.sync_stubs_injected = False
        self.async_stubs_injected = False

        sync_tools: List[Any] = [self.run_code]
        async_tools: List[Any] = [(self.arun_code, "run_code")]
        if self.discovery_enabled and self.code_model is None:
            sync_tools.insert(0, self.search_tools)
            async_tools.insert(0, (self.asearch_tools, "search_tools"))

        super().__init__(name="code_mode", tools=sync_tools, async_tools=async_tools, **kwargs)

        if self.code_model is not None:
            self.instructions = (
                "You have access to a `run_code` tool that accepts plain English task descriptions.\n"
                "A specialized code-generation model will write and execute Python code "
                "that calls the available tools. You do NOT need to write code yourself.\n"
                "Describe what data to fetch, what computations to perform, and the desired output format.\n"
                "You do NOT need to write code yourself."
            )
        else:
            self.instructions = (
                "You have access to a code execution environment via the `run_code` tool.\n"
                "Write ONE complete Python program per call that handles the entire task.\n"
                "Call tool functions DIRECTLY by name (e.g., get_stock_price(symbol='AAPL')).\n"
                "`json`, `math`, `datetime`, `re`, and `collections` are pre-imported. Do NOT write import statements.\n"
                "All tool functions return JSON strings — use json.loads() to parse results.\n"
                "Store your final answer in a variable called `result` as a formatted string.\n"
                "Use loops to process multiple items efficiently in a single call."
            )
        self.add_instructions = True

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
        if self.code_model is not None:
            return self._run_with_code_model(code, use_async=False)
        result = execute_code(self, code, use_async=False)
        if isinstance(result, ToolResult):
            return result
        if result.startswith(self.exec_error_prefix):
            return result[len(self.exec_error_prefix) :]
        return result

    async def arun_code(self, code: str) -> Union[str, ToolResult]:
        if self.code_model is not None:
            return await self._arun_with_code_model(code, use_async=True)
        import asyncio

        loop = asyncio.get_running_loop()
        self.caller_loop = loop
        try:
            result = await loop.run_in_executor(None, execute_code, self, code, True)
        finally:
            self.caller_loop = None
        if isinstance(result, ToolResult):
            return result
        if result.startswith(self.exec_error_prefix):
            return result[len(self.exec_error_prefix) :]
        return result

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
                f"There are {len(self.stub_map)} functions available."
            )

        query_lower = query.lower().strip()
        matches = []
        for name, stub in self.stub_map.items():
            func = self.sandbox_functions.get(name)
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

    def rebuild(self) -> None:
        self.sandbox_functions = collect_functions(self.source_tools, async_mode=False)
        self.sandbox_async_functions = collect_functions(self.source_tools, async_mode=True)

        self.stub_map = generate_stub_map(self.sandbox_functions, self.framework_params, self.json_type_map)
        self.stubs = "\n\n".join(self.stub_map.values())

        if self.discovery_enabled or self.code_model is not None:
            self.catalog = generate_catalog(self.sandbox_functions)

        self.sync_stubs_injected = False
        self.async_stubs_injected = False

    def get_functions(self) -> Dict[str, Function]:
        funcs = super().get_functions()
        self._inject_sync_stubs(funcs)
        return funcs

    def get_async_functions(self) -> Dict[str, Function]:
        funcs = super().get_async_functions()
        self._inject_async_stubs(funcs)
        return funcs

    def _inject_sync_stubs(self, funcs: Dict[str, Function]) -> None:
        if self.sync_stubs_injected:
            return
        self._inject_stubs_into(funcs)
        self.sync_stubs_injected = True

    def _inject_async_stubs(self, funcs: Dict[str, Function]) -> None:
        if self.async_stubs_injected:
            return
        self._inject_stubs_into(funcs)
        self.async_stubs_injected = True

    def _inject_stubs_into(self, funcs: Dict[str, Function]) -> None:
        run_code_func = funcs.get("run_code")
        if run_code_func is None:
            return

        if self.code_model is not None:
            run_code_func.description = (
                "Execute a task by describing what you need done in plain English.\n\n"
                "A specialized code-generation model will write and execute Python code "
                "that calls the available tools. You do NOT need to write code yourself.\n\n"
                "Just describe the task clearly, including:\n"
                "- What data to fetch\n"
                "- What computations to perform\n"
                "- What format you want the result in\n\n"
                "Available tools:\n\n" + self.catalog
            )
        elif self.discovery_enabled:
            base = run_code_func.description or ""
            run_code_func.description = (
                base + "\n\nAvailable tools (use search_tools for full signatures):\n\n" + self.catalog
            )
        else:
            base = run_code_func.description or ""
            run_code_func.description = base + "\n\nAvailable functions:\n\n" + self.stubs

    @staticmethod
    def _extract_code_block(text: str) -> str:
        m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        return text.strip()

    def _get_run_response(self) -> Any:
        run_code_func = self.functions.get("run_code")
        if run_code_func is not None:
            return getattr(run_code_func, "_run_response", None)
        return None

    def _generate_code(self, task: str, error: Optional[str] = None) -> str:
        from agno.models.message import Message

        system = self.code_model_system + self.stubs
        user_content = task
        if error:
            user_content += f"\n\nPrevious attempt failed with:\n{error}\n\nFix the code and try again."

        messages = [
            Message(role="system", content=system),
            Message(role="user", content=user_content),
        ]
        response = self.code_model.response(messages=messages, run_response=self._get_run_response())  # type: ignore[union-attr]
        return self._extract_code_block(response.content or "")

    async def _agenerate_code(self, task: str, error: Optional[str] = None) -> str:
        from agno.models.message import Message

        system = self.code_model_system + self.stubs
        user_content = task
        if error:
            user_content += f"\n\nPrevious attempt failed with:\n{error}\n\nFix the code and try again."

        messages = [
            Message(role="system", content=system),
            Message(role="user", content=user_content),
        ]
        response = await self.code_model.aresponse(messages=messages, run_response=self._get_run_response())  # type: ignore[union-attr]
        return self._extract_code_block(response.content or "")

    def _run_with_code_model(self, task: str, use_async: bool = False) -> Union[str, ToolResult]:
        last_error: Optional[str] = None
        for attempt in range(self.max_code_retries):
            code = self._generate_code(task, error=last_error)
            log_debug(f"CodeMode code_model attempt {attempt + 1}:\n{code}")
            result = execute_code(self, code, use_async=use_async)
            if isinstance(result, ToolResult):
                return result
            if not result.startswith(self.exec_error_prefix):
                return result
            last_error = result[len(self.exec_error_prefix) :]
            log_debug(f"CodeMode code_model attempt {attempt + 1} failed: {last_error}")
        return f"Code generation failed after {self.max_code_retries} attempts. Last error: {last_error}"

    async def _arun_with_code_model(self, task: str, use_async: bool = True) -> Union[str, ToolResult]:
        import asyncio

        loop = asyncio.get_running_loop()
        self.caller_loop = loop
        try:
            last_error: Optional[str] = None
            for attempt in range(self.max_code_retries):
                code = await self._agenerate_code(task, error=last_error)
                log_debug(f"CodeMode code_model attempt {attempt + 1}:\n{code}")
                result = await loop.run_in_executor(None, execute_code, self, code, use_async)
                if isinstance(result, ToolResult):
                    return result
                if not result.startswith(self.exec_error_prefix):
                    return result
                last_error = result[len(self.exec_error_prefix) :]
                log_debug(f"CodeMode code_model attempt {attempt + 1} failed: {last_error}")
            return f"Code generation failed after {self.max_code_retries} attempts. Last error: {last_error}"
        finally:
            self.caller_loop = None
