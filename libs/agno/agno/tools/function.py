from functools import partial
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, get_type_hints

from docstring_parser import parse
from pydantic import BaseModel, Field, validate_call

from agno.exceptions import AgentRunException
from agno.utils.log import log_debug, log_error, log_exception, log_warning

T = TypeVar("T")


def get_entrypoint_docstring(entrypoint: Callable) -> str:
    from inspect import getdoc

    if isinstance(entrypoint, partial):
        return str(entrypoint)

    doc = getdoc(entrypoint)
    if not doc:
        return ""

    parsed = parse(doc)

    # Combine short and long descriptions
    lines = []
    if parsed.short_description:
        lines.append(parsed.short_description)
    if parsed.long_description:
        lines.extend(parsed.long_description.split("\n"))

    return "\n".join(lines)


class Function(BaseModel):
    """Model for storing functions that can be called by an agent."""

    # The name of the function to be called.
    # Must be a-z, A-Z, 0-9, or contain underscores and dashes, with a maximum length of 64.
    name: str
    # A description of what the function does, used by the model to choose when and how to call the function.
    description: Optional[str] = None
    # The parameters the functions accepts, described as a JSON Schema object.
    # To describe a function that accepts no parameters, provide the value {"type": "object", "properties": {}}.
    parameters: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []},
        description="JSON Schema object describing function parameters",
    )
    strict: Optional[bool] = None

    instructions: Optional[str] = None
    # If True, add instructions to the Agent's system message
    add_instructions: bool = True

    # The function to be called.
    entrypoint: Optional[Callable] = None
    # If True, the entrypoint processing is skipped and the Function is used as is.
    skip_entrypoint_processing: bool = False
    # If True, the arguments are sanitized before being passed to the function.
    sanitize_arguments: bool = True
    # If True, the function call will show the result along with sending it to the model.
    show_result: bool = False
    # If True, the agent will stop after the function call.
    stop_after_tool_call: bool = False
    # Hook that runs before the function is executed.
    # If defined, can accept the FunctionCall instance as a parameter.
    # Deprecated: Use tool_hooks instead.
    pre_hook: Optional[Callable] = None
    # Hook that runs after the function is executed, regardless of success/failure.
    # If defined, can accept the FunctionCall instance as a parameter.
    # Deprecated: Use tool_hooks instead.
    post_hook: Optional[Callable] = None

    # A list of hooks to run around tool calls.
    tool_hooks: Optional[List[Callable]] = None

    # Caching configuration
    cache_results: bool = False
    cache_dir: Optional[str] = None
    cache_ttl: int = 3600

    # --*-- FOR INTERNAL USE ONLY --*--
    # The agent that the function is associated with
    _agent: Optional[Any] = None
    # The team that the function is associated with
    _team: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True, include={"name", "description", "parameters", "strict"})

    @classmethod
    def from_callable(cls, c: Callable, strict: bool = False) -> "Function":
        from inspect import getdoc, isasyncgenfunction, signature

        from agno.utils.json_schema import get_json_schema

        function_name = c.__name__
        parameters = {"type": "object", "properties": {}, "required": []}
        try:
            sig = signature(c)
            type_hints = get_type_hints(c)

            # If function has an the agent argument, remove the agent parameter from the type hints
            if "agent" in sig.parameters:
                del type_hints["agent"]
            if "team" in sig.parameters:
                del type_hints["team"]
            # log_info(f"Type hints for {function_name}: {type_hints}")

            # Filter out return type and only process parameters
            param_type_hints = {
                name: type_hints.get(name)
                for name in sig.parameters
                if name != "return" and name not in ["agent", "team"]
            }

            # Parse docstring for parameters
            param_descriptions: Dict[str, Any] = {}
            if docstring := getdoc(c):
                parsed_doc = parse(docstring)
                param_docs = parsed_doc.params

                if param_docs is not None:
                    for param in param_docs:
                        param_name = param.arg_name
                        param_type = param.type_name
                        if param_type is None:
                            param_descriptions[param_name] = param.description
                        else:
                            param_descriptions[param_name] = f"({param_type}) {param.description}"

            # Get JSON schema for parameters only
            parameters = get_json_schema(
                type_hints=param_type_hints, param_descriptions=param_descriptions, strict=strict
            )

            # If strict=True mark all fields as required
            # See: https://platform.openai.com/docs/guides/structured-outputs/supported-schemas#all-fields-must-be-required
            if strict:
                parameters["required"] = [name for name in parameters["properties"] if name not in ["agent", "team"]]
            else:
                # Mark a field as required if it has no default value
                parameters["required"] = [
                    name
                    for name, param in sig.parameters.items()
                    if param.default == param.empty and name != "self" and name not in ["agent", "team"]
                ]

            # log_debug(f"JSON schema for {function_name}: {parameters}")
        except Exception as e:
            log_warning(f"Could not parse args for {function_name}: {e}", exc_info=True)

        # Don't wrap async generator with validate_call
        if isasyncgenfunction(c):
            entrypoint = c
        else:
            entrypoint = validate_call(c, config=dict(arbitrary_types_allowed=True))  # type: ignore
        return cls(
            name=function_name,
            description=get_entrypoint_docstring(entrypoint=c),
            parameters=parameters,
            entrypoint=entrypoint,
        )

    def process_entrypoint(self, strict: bool = False):
        """Process the entrypoint and make it ready for use by an agent."""
        from inspect import getdoc, isasyncgenfunction, signature

        from agno.utils.json_schema import get_json_schema

        if self.skip_entrypoint_processing:
            return

        if self.entrypoint is None:
            return

        parameters = {"type": "object", "properties": {}, "required": []}

        params_set_by_user = False
        # If the user set the parameters (i.e. they are different from the default), we should keep them
        if self.parameters != parameters:
            params_set_by_user = True

        try:
            sig = signature(self.entrypoint)
            type_hints = get_type_hints(self.entrypoint)

            # If function has an the agent argument, remove the agent parameter from the type hints
            if "agent" in sig.parameters:
                del type_hints["agent"]
            if "team" in sig.parameters:
                del type_hints["team"]
            # log_info(f"Type hints for {self.name}: {type_hints}")

            # Filter out return type and only process parameters
            param_type_hints = {
                name: type_hints.get(name)
                for name in sig.parameters
                if name != "return" and name not in ["agent", "team"]
            }

            # Parse docstring for parameters
            param_descriptions = {}
            if docstring := getdoc(self.entrypoint):
                parsed_doc = parse(docstring)
                param_docs = parsed_doc.params

                if param_docs is not None:
                    for param in param_docs:
                        param_name = param.arg_name
                        param_type = param.type_name

                        # TODO: We should use type hints first, then map param types in docs to json schema types.
                        # This is temporary to not lose information
                        param_descriptions[param_name] = f"({param_type}) {param.description}"

            # Get JSON schema for parameters only
            parameters = get_json_schema(
                type_hints=param_type_hints, param_descriptions=param_descriptions, strict=strict
            )

            # If strict=True mark all fields as required
            # See: https://platform.openai.com/docs/guides/structured-outputs/supported-schemas#all-fields-must-be-required
            if strict:
                parameters["required"] = [name for name in parameters["properties"] if name not in ["agent", "team"]]
            else:
                # Mark a field as required if it has no default value
                parameters["required"] = [
                    name
                    for name, param in sig.parameters.items()
                    if param.default == param.empty and name != "self" and name not in ["agent", "team"]
                ]

            if params_set_by_user:
                self.parameters["additionalProperties"] = False
                if strict:
                    self.parameters["required"] = [
                        name for name in self.parameters["properties"] if name not in ["agent", "team"]
                    ]
                else:
                    # Mark a field as required if it has no default value
                    self.parameters["required"] = [
                        name
                        for name, param in sig.parameters.items()
                        if param.default == param.empty and name != "self" and name not in ["agent", "team"]
                    ]

            # log_debug(f"JSON schema for {self.name}: {parameters}")
        except Exception as e:
            log_warning(f"Could not parse args for {self.name}: {e}", exc_info=True)

        self.description = self.description or get_entrypoint_docstring(self.entrypoint)
        if not params_set_by_user:
            self.parameters = parameters

        try:
            # Don't wrap async generator with validate_call
            if not isasyncgenfunction(self.entrypoint):
                self.entrypoint = validate_call(self.entrypoint, config=dict(arbitrary_types_allowed=True))  # type: ignore
        except Exception as e:
            log_warning(f"Failed to add validate decorator to entrypoint: {e}")

    def get_type_name(self, t: Type[T]):
        name = str(t)
        if "list" in name or "dict" in name:
            return name
        else:
            return t.__name__

    def get_definition_for_prompt_dict(self) -> Optional[Dict[str, Any]]:
        """Returns a function definition that can be used in a prompt."""

        if self.entrypoint is None:
            return None

        type_hints = get_type_hints(self.entrypoint)
        return_type = type_hints.get("return", None)
        returns = None
        if return_type is not None:
            returns = self.get_type_name(return_type)

        function_info = {
            "name": self.name,
            "description": self.description,
            "arguments": self.parameters.get("properties", {}),
            "returns": returns,
        }
        return function_info

    def get_definition_for_prompt(self) -> Optional[str]:
        """Returns a function definition that can be used in a prompt."""
        import json

        function_info = self.get_definition_for_prompt_dict()
        if function_info is not None:
            return json.dumps(function_info, indent=2)
        return None

    def _get_cache_key(self, entrypoint_args: Dict[str, Any], call_args: Optional[Dict[str, Any]] = None) -> str:
        """Generate a cache key based on function name and arguments."""
        from hashlib import md5

        copy_entrypoint_args = entrypoint_args.copy()
        # Remove agent from entrypoint_args
        if "agent" in copy_entrypoint_args:
            del copy_entrypoint_args["agent"]
        if "team" in copy_entrypoint_args:
            del copy_entrypoint_args["team"]
        args_str = str(copy_entrypoint_args)

        kwargs_str = str(sorted((call_args or {}).items()))
        key_str = f"{self.name}:{args_str}:{kwargs_str}"
        return md5(key_str.encode()).hexdigest()

    def _get_cache_file_path(self, cache_key: str) -> str:
        """Get the full path for the cache file."""
        from pathlib import Path
        from tempfile import gettempdir

        base_cache_dir = self.cache_dir or Path(gettempdir()) / "agno_cache"
        func_cache_dir = Path(base_cache_dir) / "functions" / self.name
        func_cache_dir.mkdir(parents=True, exist_ok=True)
        return str(func_cache_dir / f"{cache_key}.json")

    def _get_cached_result(self, cache_file: str) -> Optional[Any]:
        """Retrieve cached result if valid."""
        import json
        from pathlib import Path
        from time import time

        cache_path = Path(cache_file)
        if not cache_path.exists():
            return None

        try:
            with cache_path.open("r") as f:
                cache_data = json.load(f)

            timestamp = cache_data.get("timestamp", 0)
            result = cache_data.get("result")

            if time() - timestamp <= self.cache_ttl:
                return result

            # Remove expired entry
            cache_path.unlink()
        except Exception as e:
            log_error(f"Error reading cache: {e}")

        return None

    def _save_to_cache(self, cache_file: str, result: Any):
        """Save result to cache."""
        import json
        from time import time

        try:
            with open(cache_file, "w") as f:
                json.dump({"timestamp": time(), "result": result}, f)
        except Exception as e:
            log_error(f"Error writing cache: {e}")


class FunctionCall(BaseModel):
    """Model for Function Calls"""

    # The function to be called.
    function: Function
    # The arguments to call the function with.
    arguments: Optional[Dict[str, Any]] = None
    # The result of the function call.
    result: Optional[Any] = None
    # The ID of the function call.
    call_id: Optional[str] = None

    # Error while parsing arguments or running the function.
    error: Optional[str] = None

    def get_call_str(self) -> str:
        """Returns a string representation of the function call."""
        import shutil

        # Get terminal width, default to 80 if can't determine
        term_width = shutil.get_terminal_size().columns or 80
        max_arg_len = max(20, (term_width - len(self.function.name) - 4) // 2)

        if self.arguments is None:
            return f"{self.function.name}()"

        trimmed_arguments = {}
        for k, v in self.arguments.items():
            if isinstance(v, str) and len(str(v)) > max_arg_len:
                trimmed_arguments[k] = "..."
            else:
                trimmed_arguments[k] = v

        call_str = f"{self.function.name}({', '.join([f'{k}={v}' for k, v in trimmed_arguments.items()])})"

        # If call string is too long, truncate arguments
        if len(call_str) > term_width:
            return f"{self.function.name}(...)"

        return call_str

    def _handle_pre_hook(self):
        """Handles the pre-hook for the function call."""
        if self.function.pre_hook is not None:
            try:
                from inspect import signature

                pre_hook_args = {}
                # Check if the pre-hook has and agent argument
                if "agent" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["agent"] = self.function._agent
                # Check if the pre-hook has an team argument
                if "team" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["team"] = self.function._team
                # Check if the pre-hook has an fc argument
                if "fc" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["fc"] = self
                self.function.pre_hook(**pre_hook_args)
            except AgentRunException as e:
                log_debug(f"{e.__class__.__name__}: {e}")
                self.error = str(e)
                raise
            except Exception as e:
                log_warning(f"Error in pre-hook callback: {e}")
                log_exception(e)

    def _handle_post_hook(self):
        """Handles the post-hook for the function call."""
        if self.function.post_hook is not None:
            try:
                from inspect import signature

                post_hook_args = {}
                # Check if the post-hook has and agent argument
                if "agent" in signature(self.function.post_hook).parameters:
                    post_hook_args["agent"] = self.function._agent
                # Check if the post-hook has an team argument
                if "team" in signature(self.function.post_hook).parameters:
                    post_hook_args["team"] = self.function._team
                # Check if the post-hook has an fc argument
                if "fc" in signature(self.function.post_hook).parameters:
                    post_hook_args["fc"] = self
                self.function.post_hook(**post_hook_args)
            except AgentRunException as e:
                log_debug(f"{e.__class__.__name__}: {e}")
                self.error = str(e)
                raise
            except Exception as e:
                log_warning(f"Error in post-hook callback: {e}")
                log_exception(e)

    def _build_entrypoint_args(self) -> Dict[str, Any]:
        """Builds the arguments for the entrypoint."""
        from inspect import signature

        entrypoint_args = {}
        # Check if the entrypoint has an agent argument
        if "agent" in signature(self.function.entrypoint).parameters:  # type: ignore
            entrypoint_args["agent"] = self.function._agent
        # Check if the entrypoint has an team argument
        if "team" in signature(self.function.entrypoint).parameters:  # type: ignore
            entrypoint_args["team"] = self.function._team
        # Check if the entrypoint has an fc argument
        if "fc" in signature(self.function.entrypoint).parameters:  # type: ignore
            entrypoint_args["fc"] = self
        return entrypoint_args

    def _build_nested_execution_chain(self, entrypoint_args: Dict[str, Any]):
        """Build a nested chain of hook executions with the entrypoint at the center.

        This creates a chain where each hook wraps the next one, with the function call
        at the innermost level. Returns bubble back up through each hook.
        """
        from functools import reduce
        from inspect import iscoroutinefunction

        def execute_entrypoint(name, func, args):
            """Execute the entrypoint function."""
            arguments = entrypoint_args.copy()
            if self.arguments is not None:
                arguments.update(self.arguments)
            return self.function.entrypoint(**arguments)  # type: ignore

        # If no hooks, just return the entrypoint execution function
        if not self.function.tool_hooks:
            return execute_entrypoint

        def create_hook_wrapper(inner_func, hook):
            """Create a nested wrapper for the hook."""

            def wrapper(name, func, args):
                # Pass the inner function as next_func to the hook
                # The hook will call next_func to continue the chain
                def next_func(**kwargs):
                    return inner_func(name, func, kwargs)

                return hook(name, next_func, args)

            return wrapper

        # Remove coroutine hooks
        final_hooks = []
        for hook in self.function.tool_hooks:
            if iscoroutinefunction(hook):
                log_warning(f"Cannot use async hooks with sync function calls. Skipping hook: {hook.__name__}")
            else:
                final_hooks.append(hook)

        # Build the chain from inside out - reverse the hooks to start from the innermost
        hooks = list(reversed(final_hooks))
        chain = reduce(create_hook_wrapper, hooks, execute_entrypoint)
        return chain

    def execute(self) -> bool:
        """Runs the function call."""
        from inspect import isgenerator

        if self.function.entrypoint is None:
            return False

        log_debug(f"Running: {self.get_call_str()}")
        function_call_success = False

        # Execute pre-hook if it exists
        self._handle_pre_hook()

        entrypoint_args = self._build_entrypoint_args()

        # Check cache if enabled and not a generator function
        if self.function.cache_results and not isgenerator(self.function.entrypoint):
            cache_key = self.function._get_cache_key(entrypoint_args, self.arguments)
            cache_file = self.function._get_cache_file_path(cache_key)
            cached_result = self.function._get_cached_result(cache_file)

            if cached_result is not None:
                log_debug(f"Cache hit for: {self.get_call_str()}")
                self.result = cached_result
                function_call_success = True
                return function_call_success

        # Execute function
        try:
            # Build and execute the nested chain of hooks
            if self.function.tool_hooks is not None:
                execution_chain = self._build_nested_execution_chain(entrypoint_args=entrypoint_args)
                result = execution_chain(self.function.name, self.function.entrypoint, self.arguments or {})
            else:
                arguments = entrypoint_args
                if self.arguments is not None:
                    arguments.update(self.arguments)
                result = self.function.entrypoint(**arguments)

            # Handle generator case
            if isgenerator(result):
                self.result = result  # Store generator directly, can't cache
            else:
                self.result = result
                # Only cache non-generator results
                if self.function.cache_results:
                    cache_key = self.function._get_cache_key(entrypoint_args, self.arguments)
                    cache_file = self.function._get_cache_file_path(cache_key)
                    self.function._save_to_cache(cache_file, self.result)

            function_call_success = True

        except AgentRunException as e:
            log_debug(f"{e.__class__.__name__}: {e}")
            self.error = str(e)
            raise
        except Exception as e:
            log_warning(f"Could not run function {self.get_call_str()}")
            log_exception(e)
            self.error = str(e)
            return function_call_success

        # Execute post-hook if it exists
        self._handle_post_hook()

        return function_call_success

    async def _handle_pre_hook_async(self):
        """Handles the async pre-hook for the function call."""
        if self.function.pre_hook is not None:
            try:
                from inspect import signature

                pre_hook_args = {}
                # Check if the pre-hook has an agent argument
                if "agent" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["agent"] = self.function._agent
                # Check if the pre-hook has an team argument
                if "team" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["team"] = self.function._team
                # Check if the pre-hook has an fc argument
                if "fc" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["fc"] = self

                await self.function.pre_hook(**pre_hook_args)
            except AgentRunException as e:
                log_debug(f"{e.__class__.__name__}: {e}")
                self.error = str(e)
                raise
            except Exception as e:
                log_warning(f"Error in pre-hook callback: {e}")
                log_exception(e)

    async def _handle_post_hook_async(self):
        """Handles the async post-hook for the function call."""
        if self.function.post_hook is not None:
            try:
                from inspect import signature

                post_hook_args = {}
                # Check if the post-hook has an agent argument
                if "agent" in signature(self.function.post_hook).parameters:
                    post_hook_args["agent"] = self.function._agent
                # Check if the post-hook has an team argument
                if "team" in signature(self.function.post_hook).parameters:
                    post_hook_args["team"] = self.function._team
                # Check if the post-hook has an fc argument
                if "fc" in signature(self.function.post_hook).parameters:
                    post_hook_args["fc"] = self

                await self.function.post_hook(**post_hook_args)
            except AgentRunException as e:
                log_debug(f"{e.__class__.__name__}: {e}")
                self.error = str(e)
                raise
            except Exception as e:
                log_warning(f"Error in post-hook callback: {e}")
                log_exception(e)

    async def _build_nested_execution_chain_async(self, entrypoint_args: Dict[str, Any]):
        """Build a nested chain of async hook executions with the entrypoint at the center.

        Similar to _build_nested_execution_chain but for async execution.
        """
        from functools import reduce
        from inspect import isasyncgen, isasyncgenfunction, iscoroutinefunction

        async def execute_entrypoint_async(name, func, args):
            """Execute the entrypoint function asynchronously."""
            arguments = entrypoint_args.copy()
            if self.arguments is not None:
                arguments.update(self.arguments)

            result = self.function.entrypoint(**arguments)  # type: ignore
            if iscoroutinefunction(self.function.entrypoint) and not (
                isasyncgen(self.function.entrypoint) or isasyncgenfunction(self.function.entrypoint)
            ):
                result = await result
            return result

        def execute_entrypoint(name, func, args):
            """Execute the entrypoint function synchronously."""
            arguments = entrypoint_args.copy()
            if self.arguments is not None:
                arguments.update(self.arguments)
            return self.function.entrypoint(**arguments)  # type: ignore

        # If no hooks, just return the entrypoint execution function
        if not self.function.tool_hooks:
            return execute_entrypoint

        def create_hook_wrapper(inner_func, hook):
            """Create a nested wrapper for the hook."""

            async def wrapper(name, func, args):
                """Create a nested wrapper for the hook."""

                # Pass the inner function as next_func to the hook
                # The hook will call next_func to continue the chain
                async def next_func(**kwargs):
                    if iscoroutinefunction(inner_func):
                        return await inner_func(name, func, kwargs)
                    else:
                        return inner_func(name, func, kwargs)

                if iscoroutinefunction(hook):
                    return await hook(name, next_func, args)
                else:
                    return hook(name, next_func, args)

            return wrapper

        # Build the chain from inside out - reverse the hooks to start from the innermost
        hooks = list(reversed(self.function.tool_hooks))

        # Handle async and sync entrypoints
        if iscoroutinefunction(self.function.entrypoint):
            chain = reduce(create_hook_wrapper, hooks, execute_entrypoint_async)
        else:
            chain = reduce(create_hook_wrapper, hooks, execute_entrypoint)

        return chain

    async def aexecute(self) -> bool:
        """Runs the function call asynchronously."""
        from inspect import isasyncgen, isasyncgenfunction, iscoroutinefunction, isgenerator

        if self.function.entrypoint is None:
            return False

        log_debug(f"Running: {self.get_call_str()}")
        function_call_success = False

        # Execute pre-hook if it exists
        if iscoroutinefunction(self.function.pre_hook):
            await self._handle_pre_hook_async()
        else:
            self._handle_pre_hook()

        entrypoint_args = self._build_entrypoint_args()

        # Check cache if enabled and not a generator function
        if self.function.cache_results and not (
            isasyncgen(self.function.entrypoint) or isgenerator(self.function.entrypoint)
        ):
            cache_key = self.function._get_cache_key(entrypoint_args, self.arguments)
            cache_file = self.function._get_cache_file_path(cache_key)
            cached_result = self.function._get_cached_result(cache_file)
            if cached_result is not None:
                log_debug(f"Cache hit for: {self.get_call_str()}")
                self.result = cached_result
                function_call_success = True
                return function_call_success

        # Execute function
        try:
            # Build and execute the nested chain of hooks
            if self.function.tool_hooks is not None:
                execution_chain = await self._build_nested_execution_chain_async(entrypoint_args)
                self.result = await execution_chain(self.function.name, self.function.entrypoint, self.arguments or {})
            else:
                if self.arguments is None or self.arguments == {}:
                    result = self.function.entrypoint(**entrypoint_args)
                else:
                    result = self.function.entrypoint(**entrypoint_args, **self.arguments)

                if isasyncgen(self.function.entrypoint) or isasyncgenfunction(self.function.entrypoint):
                    self.result = result  # Store async generator directly
                else:
                    self.result = await result

            # Only cache if not a generator
            if self.function.cache_results and not (isgenerator(self.result) or isasyncgen(self.result)):
                cache_key = self.function._get_cache_key(entrypoint_args, self.arguments)
                cache_file = self.function._get_cache_file_path(cache_key)
                self.function._save_to_cache(cache_file, self.result)

            function_call_success = True

        except AgentRunException as e:
            log_debug(f"{e.__class__.__name__}: {e}")
            self.error = str(e)
            raise
        except Exception as e:
            log_warning(f"Could not run function {self.get_call_str()}")
            log_exception(e)
            self.error = str(e)
            return function_call_success

        # Execute post-hook if it exists
        if iscoroutinefunction(self.function.post_hook):
            await self._handle_post_hook_async()
        else:
            self._handle_post_hook()

        return function_call_success
