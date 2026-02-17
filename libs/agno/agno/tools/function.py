from dataclasses import dataclass
from functools import partial
from importlib.metadata import version
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Type, TypeVar, get_type_hints

from docstring_parser import parse
from packaging.version import Version
from pydantic import BaseModel, Field, validate_call

from agno.exceptions import AgentRunException
from agno.media import Audio, File, Image, Video
from agno.run import RunContext
from agno.utils.log import log_debug, log_error, log_exception, log_warning

T = TypeVar("T")


def get_entrypoint_docstring(entrypoint: Callable) -> str:
    from inspect import getdoc

    if isinstance(entrypoint, partial):
        return str(entrypoint)

    docstring = getdoc(entrypoint)
    if not docstring:
        return ""

    parsed_doc = parse(docstring)

    # Combine short and long descriptions
    lines = []
    if parsed_doc.short_description:
        lines.append(parsed_doc.short_description)
    if parsed_doc.long_description:
        lines.extend(parsed_doc.long_description.split("\n"))

    return "\n".join(lines)


@dataclass
class UserInputField:
    name: str
    field_type: Type
    description: Optional[str] = None
    value: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "field_type": str(self.field_type.__name__),
            "description": self.description,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserInputField":
        type_mapping = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}
        field_type_raw = data["field_type"]
        if isinstance(field_type_raw, str):
            field_type = type_mapping.get(field_type_raw, str)
        elif isinstance(field_type_raw, type):
            field_type = field_type_raw
        else:
            field_type = str
        return cls(
            name=data["name"],
            field_type=field_type,
            description=data["description"],
            value=data["value"],
        )


@dataclass
class UserFeedbackOption:
    """An option for a user feedback question."""

    label: str
    description: Optional[str] = None
    selected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "description": self.description,
            "selected": self.selected,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserFeedbackOption":
        return cls(
            label=data["label"],
            description=data.get("description"),
            selected=data.get("selected", False),
        )


@dataclass
class UserFeedbackQuestion:
    """A structured question with predefined options for user feedback."""

    question: str
    header: Optional[str] = None
    options: Optional[List["UserFeedbackOption"]] = None
    multi_select: bool = False
    selected_options: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "question": self.question,
            "header": self.header,
            "multi_select": self.multi_select,
            "selected_options": self.selected_options,
        }
        if self.options is not None:
            result["options"] = [opt.to_dict() for opt in self.options]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserFeedbackQuestion":
        options = None
        if data.get("options") is not None:
            options = [UserFeedbackOption.from_dict(opt) if isinstance(opt, dict) else opt for opt in data["options"]]
        return cls(
            question=data["question"],
            header=data.get("header"),
            options=options,
            multi_select=data.get("multi_select", False),
            selected_options=data.get("selected_options"),
        )


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
    # If True, the function call will show the result along with sending it to the model.
    show_result: bool = False
    # If True, the agent will stop after the function call.
    stop_after_tool_call: bool = False
    # Hook that runs before the function is executed.
    # If defined, can accept the FunctionCall instance as a parameter.
    pre_hook: Optional[Callable] = None
    # Hook that runs after the function is executed, regardless of success/failure.
    # If defined, can accept the FunctionCall instance as a parameter.
    post_hook: Optional[Callable] = None

    # A list of hooks to run around tool calls.
    tool_hooks: Optional[List[Callable]] = None

    # If True, the function will require confirmation before execution
    requires_confirmation: Optional[bool] = None

    # If True, the function will require user input before execution
    requires_user_input: Optional[bool] = None
    # List of fields that the user will provide as input and that should be ignored by the agent (empty list means all fields are provided by the user)
    user_input_fields: Optional[List[str]] = None
    # This is set during parsing, not by the user
    user_input_schema: Optional[List[UserInputField]] = None

    # If True, the function will be executed outside the agent's control.
    external_execution: Optional[bool] = None

    # If True (and external_execution=True), the function will not produce verbose paused messages (e.g., "I have tools to execute...")
    external_execution_silent: Optional[bool] = None

    # Approval type: "required" (blocking) or "audit" (non-blocking audit trail).
    # Set via the @approval decorator, not directly via @tool().
    approval_type: Optional[str] = None

    # Caching configuration
    cache_results: bool = False
    cache_dir: Optional[str] = None
    cache_ttl: int = 3600

    # --*-- FOR INTERNAL USE ONLY --*--
    # The agent that the function is associated with
    _agent: Optional[Any] = None
    # The team that the function is associated with
    _team: Optional[Any] = None
    # The run context that the function is associated with
    _run_context: Optional[RunContext] = None

    # Media context that the function is associated with
    _images: Optional[Sequence[Image]] = None
    _videos: Optional[Sequence[Video]] = None
    _audios: Optional[Sequence[Audio]] = None
    _files: Optional[Sequence[File]] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(
            exclude_none=True,
            include={
                "name",
                "description",
                "parameters",
                "strict",
                "requires_confirmation",
                "external_execution",
                "approval_type",
            },
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Function":
        """Reconstruct a Function from a dictionary."""

        return cls(
            name=data.get("name"),
            description=data.get("description"),
            parameters=data.get("parameters"),
            strict=data.get("strict"),
            requires_confirmation=data.get("requires_confirmation", False),
            external_execution=data.get("external_execution", False),
            approval_type=data.get("approval_type"),
        )

    def model_copy(self, *, deep: bool = False) -> "Function":
        """
        Override model_copy to handle callable fields that can't be deep copied (pickled).
        Callables should always be shallow copied (referenced), not deep copied.
        """
        # For deep copy, we need to handle callable fields specially
        if deep:
            # Fields that should NOT be deep copied (callables and complex objects)
            shallow_fields = {
                "entrypoint",
                "pre_hook",
                "post_hook",
                "tool_hooks",
                "_agent",
                "_team",
            }

            # Create a copy with shallow references to callable fields
            copied_data = {}
            for field_name, field_value in self.__dict__.items():
                if field_name in shallow_fields:
                    # Shallow copy - just reference the same object
                    copied_data[field_name] = field_value
                elif field_name == "parameters":
                    # Deep copy the parameters dict
                    from copy import deepcopy

                    copied_data[field_name] = deepcopy(field_value)
                else:
                    # For simple types, just copy the value
                    copied_data[field_name] = field_value

            # Create new instance with copied data
            new_instance = self.__class__.model_construct(**copied_data)

            return new_instance
        else:
            # For shallow copy, use the default Pydantic behavior
            return super().model_copy(deep=False)

    @classmethod
    def from_callable(cls, c: Callable, name: Optional[str] = None, strict: bool = False) -> "Function":
        from inspect import getdoc, signature

        from agno.utils.json_schema import get_json_schema

        function_name = name or c.__name__
        parameters = {"type": "object", "properties": {}, "required": []}
        try:
            sig = signature(c)
            type_hints = get_type_hints(c)

            # If function has an the agent argument, remove the agent parameter from the type hints
            if "agent" in sig.parameters and "agent" in type_hints:
                del type_hints["agent"]
            if "team" in sig.parameters and "team" in type_hints:
                del type_hints["team"]
            if "run_context" in sig.parameters and "run_context" in type_hints:
                del type_hints["run_context"]

            # Remove media parameters from type hints as they are injected automatically
            if "images" in sig.parameters and "images" in type_hints:
                del type_hints["images"]
            if "videos" in sig.parameters and "videos" in type_hints:
                del type_hints["videos"]
            if "audios" in sig.parameters and "audios" in type_hints:
                del type_hints["audios"]
            if "files" in sig.parameters and "files" in type_hints:
                del type_hints["files"]
            # log_info(f"Type hints for {function_name}: {type_hints}")

            # Filter out return type and only process parameters
            param_type_hints = {
                name: type_hints.get(name)
                for name in sig.parameters
                if name != "return"
                and name
                not in [
                    "agent",
                    "team",
                    "run_context",
                    "self",
                    "images",
                    "videos",
                    "audios",
                    "files",
                ]
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
                parameters["required"] = [
                    name
                    for name in parameters["properties"]
                    if name
                    not in [
                        "agent",
                        "team",
                        "run_context",
                        "self",
                        "images",
                        "videos",
                        "audios",
                        "files",
                    ]
                ]
            else:
                # Mark a field as required if it has no default value (this would include optional fields)
                parameters["required"] = [
                    name
                    for name, param in sig.parameters.items()
                    if param.default == param.empty
                    and name
                    not in [
                        "agent",
                        "team",
                        "run_context",
                        "self",
                        "images",
                        "videos",
                        "audios",
                        "files",
                    ]
                ]

            # log_debug(f"JSON schema for {function_name}: {parameters}")
        except Exception as e:
            log_warning(f"Could not parse args for {function_name}: {e}", exc_info=True)

        entrypoint = cls._wrap_callable(c)

        return cls(
            name=function_name,
            description=get_entrypoint_docstring(entrypoint=c),
            parameters=parameters,
            entrypoint=entrypoint,
        )

    def process_entrypoint(self, strict: bool = False):
        """Process the entrypoint and make it ready for use by an agent."""
        from inspect import getdoc, signature

        from agno.utils.json_schema import get_json_schema

        if self.skip_entrypoint_processing:
            if strict:
                self.process_schema_for_strict()
            return

        if self.entrypoint is None:
            return

        parameters = {"type": "object", "properties": {}, "required": []}

        params_set_by_user = False
        # If the user set the parameters (i.e. they are different from the default), we should keep them
        if self.parameters != parameters:
            params_set_by_user = True

        if self.requires_user_input:
            self.user_input_schema = self.user_input_schema or []

        try:
            sig = signature(self.entrypoint)
            type_hints = get_type_hints(self.entrypoint)

            # If function has an the agent argument, remove the agent parameter from the type hints
            if "agent" in sig.parameters and "agent" in type_hints:
                del type_hints["agent"]
            if "team" in sig.parameters and "team" in type_hints:
                del type_hints["team"]
            if "run_context" in sig.parameters and "run_context" in type_hints:
                del type_hints["run_context"]
            if "images" in sig.parameters and "images" in type_hints:
                del type_hints["images"]
            if "videos" in sig.parameters and "videos" in type_hints:
                del type_hints["videos"]
            if "audios" in sig.parameters and "audios" in type_hints:
                del type_hints["audios"]
            if "files" in sig.parameters and "files" in type_hints:
                del type_hints["files"]
            # log_info(f"Type hints for {self.name}: {type_hints}")

            # Filter out return type and only process parameters
            excluded_params = [
                "return",
                "agent",
                "team",
                "run_context",
                "self",
                "images",
                "videos",
                "audios",
                "files",
            ]
            if self.requires_user_input and self.user_input_fields:
                if len(self.user_input_fields) == 0:
                    excluded_params.extend(list(type_hints.keys()))
                else:
                    excluded_params.extend(self.user_input_fields)

            # Get filtered list of parameter types
            param_type_hints = {name: type_hints.get(name) for name in sig.parameters if name not in excluded_params}

            # Parse docstring for parameters
            param_descriptions = {}
            param_descriptions_clean = {}
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
                        param_descriptions_clean[param_name] = param.description

            # If the function requires user input, we should set the user_input_schema to all parameters. The arguments provided by the model are filled in later.
            if self.requires_user_input:
                self.user_input_schema = [
                    UserInputField(
                        name=name,
                        description=param_descriptions_clean.get(name),
                        field_type=type_hints.get(name, str),
                    )
                    for name in sig.parameters
                ]

            # Get JSON schema for parameters only
            parameters = get_json_schema(
                type_hints=param_type_hints, param_descriptions=param_descriptions, strict=strict
            )

            # If strict=True mark all fields as required
            # See: https://platform.openai.com/docs/guides/structured-outputs/supported-schemas#all-fields-must-be-required
            if strict:
                parameters["required"] = [name for name in parameters["properties"] if name not in excluded_params]
            else:
                # Mark a field as required if it has no default value
                parameters["required"] = [
                    name
                    for name, param in sig.parameters.items()
                    if param.default == param.empty and name != "self" and name not in excluded_params
                ]

            if params_set_by_user:
                self.parameters["additionalProperties"] = False
                if strict:
                    self.parameters["required"] = [
                        name for name in self.parameters["properties"] if name not in excluded_params
                    ]
                else:
                    # Mark a field as required if it has no default value
                    self.parameters["required"] = [
                        name
                        for name, param in sig.parameters.items()
                        if param.default == param.empty and name != "self" and name not in excluded_params
                    ]

            self.description = self.description or get_entrypoint_docstring(self.entrypoint)

            # log_debug(f"JSON schema for {self.name}: {parameters}")
        except Exception as e:
            log_warning(f"Could not parse args for {self.name}: {e}", exc_info=True)

        if not params_set_by_user:
            self.parameters = parameters

        if strict:
            self.process_schema_for_strict()

        try:
            self.entrypoint = self._wrap_callable(self.entrypoint)
        except Exception as e:
            log_warning(f"Failed to add validate decorator to entrypoint: {e}")

    @staticmethod
    def _wrap_callable(func: Callable) -> Callable:
        """Wrap a callable with Pydantic's validate_call decorator, if relevant"""
        from inspect import isasyncgenfunction, iscoroutinefunction, signature

        pydantic_version = Version(version("pydantic"))

        # Don't wrap async generators validate_call
        if isasyncgenfunction(func):
            return func

        # Don't wrap coroutines with validate_call if pydantic version is less than 2.10.0
        if iscoroutinefunction(func) and pydantic_version < Version("2.10.0"):
            log_debug(
                f"Skipping validate_call for {func.__name__} because pydantic version is less than 2.10.0, please consider upgrading to pydantic 2.10.0 or higher"
            )
            return func

        # Don't wrap callables that are already wrapped with validate_call
        elif getattr(func, "_wrapped_for_validation", False):
            return func

        # Don't wrap functions with framework-injected parameters
        # These parameters (agent, team) are
        # injected by the framework at runtime and shouldn't be validated by Pydantic
        sig = signature(func)
        framework_params = {"agent", "team"}
        if framework_params & set(sig.parameters.keys()):
            return func

        # Wrap the callable with validate_call
        else:
            wrapped = validate_call(func, config=dict(arbitrary_types_allowed=True))  # type: ignore
            wrapped._wrapped_for_validation = True  # Mark as wrapped to avoid infinite recursion
            return wrapped

    def process_schema_for_strict(self):
        """Process the schema to make it strict mode compliant."""

        def make_nested_strict(schema):
            """Recursively ensure all object schemas have additionalProperties: false"""
            if not isinstance(schema, dict):
                return schema

            # Make a copy to avoid modifying the original
            result = schema.copy()

            # If this is an object schema, ensure additionalProperties: false
            if result.get("type") == "object" or "properties" in result:
                result["additionalProperties"] = False

            # If schema has no type but has other schema properties, give it a type
            if "type" not in result:
                if "properties" in result:
                    result["type"] = "object"
                    result["additionalProperties"] = False
                elif result.get("title") and not any(
                    key in result for key in ["properties", "items", "anyOf", "oneOf", "allOf", "enum"]
                ):
                    result["type"] = "string"

            # Recursively process nested schemas
            for key, value in result.items():
                if key == "properties" and isinstance(value, dict):
                    result[key] = {k: make_nested_strict(v) for k, v in value.items()}
                elif key == "items" and isinstance(value, dict):
                    # This handles array items like List[KnowledgeFilter]
                    result[key] = make_nested_strict(value)
                elif isinstance(value, dict):
                    result[key] = make_nested_strict(value)

            return result

        # Apply strict mode to the entire schema
        self.parameters = make_nested_strict(self.parameters)

        self.parameters["required"] = [
            name
            for name in self.parameters["properties"]
            if name
            not in [
                "agent",
                "team",
                "run_context",
                "images",
                "videos",
                "audios",
                "files",
                "self",
            ]
        ]

    def _get_cache_key(self, entrypoint_args: Dict[str, Any], call_args: Optional[Dict[str, Any]] = None) -> str:
        """Generate a cache key based on function name and arguments."""
        import json
        from hashlib import md5

        copy_entrypoint_args = entrypoint_args.copy()
        # Remove agent from entrypoint_args
        if "agent" in copy_entrypoint_args:
            del copy_entrypoint_args["agent"]
        if "team" in copy_entrypoint_args:
            del copy_entrypoint_args["team"]
        if "run_context" in copy_entrypoint_args:
            del copy_entrypoint_args["run_context"]
        if "images" in copy_entrypoint_args:
            del copy_entrypoint_args["images"]
        if "videos" in copy_entrypoint_args:
            del copy_entrypoint_args["videos"]
        if "audios" in copy_entrypoint_args:
            del copy_entrypoint_args["audios"]
        if "files" in copy_entrypoint_args:
            del copy_entrypoint_args["files"]
        # Use json.dumps with sort_keys=True to ensure consistent ordering regardless of dict key order
        args_str = json.dumps(copy_entrypoint_args, sort_keys=True, default=str)

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


class FunctionExecutionResult(BaseModel):
    status: Literal["success", "failure"]
    result: Optional[Any] = None
    error: Optional[str] = None

    updated_session_state: Optional[Dict[str, Any]] = None

    # New fields for media artifacts
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audios: Optional[List[Audio]] = None
    files: Optional[List[File]] = None


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

        # Get terminal width, default to 80 if it can't be determined
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
                # Check if the pre-hook has an agent argument
                if "agent" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["agent"] = self.function._agent
                # Check if the pre-hook has a team argument
                if "team" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["team"] = self.function._team
                # Check if the pre-hook has a run_context argument
                if "run_context" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["run_context"] = self.function._run_context
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
                # Check if the post-hook has an agent argument
                if "agent" in signature(self.function.post_hook).parameters:
                    post_hook_args["agent"] = self.function._agent
                # Check if the post-hook has a team argument
                if "team" in signature(self.function.post_hook).parameters:
                    post_hook_args["team"] = self.function._team
                # Check if the post-hook has a run_context argument
                if "run_context" in signature(self.function.post_hook).parameters:
                    post_hook_args["run_context"] = self.function._run_context
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
        # Check if the entrypoint has a team argument
        if "team" in signature(self.function.entrypoint).parameters:  # type: ignore
            entrypoint_args["team"] = self.function._team
        # Check if the entrypoint has a run_context argument
        if "run_context" in signature(self.function.entrypoint).parameters:  # type: ignore
            entrypoint_args["run_context"] = self.function._run_context
        # Check if the entrypoint has an fc argument
        if "fc" in signature(self.function.entrypoint).parameters:  # type: ignore
            entrypoint_args["fc"] = self

        # Check if the entrypoint has media arguments
        if "images" in signature(self.function.entrypoint).parameters:  # type: ignore
            entrypoint_args["images"] = self.function._images
        if "videos" in signature(self.function.entrypoint).parameters:  # type: ignore
            entrypoint_args["videos"] = self.function._videos
        if "audios" in signature(self.function.entrypoint).parameters:  # type: ignore
            entrypoint_args["audios"] = self.function._audios
        if "files" in signature(self.function.entrypoint).parameters:  # type: ignore
            entrypoint_args["files"] = self.function._files
        return entrypoint_args

    def _build_hook_args(self, hook: Callable, name: str, func: Callable, args: Dict[str, Any]) -> Dict[str, Any]:
        """Build the arguments for the hook."""
        from inspect import signature

        hook_args = {}
        # Check if the hook has an agent argument
        if "agent" in signature(hook).parameters:
            hook_args["agent"] = self.function._agent
        # Check if the hook has a team argument
        if "team" in signature(hook).parameters:
            hook_args["team"] = self.function._team
        # Check if the hook has a run_context argument
        if "run_context" in signature(hook).parameters:
            hook_args["run_context"] = self.function._run_context
        if "name" in signature(hook).parameters:
            hook_args["name"] = name
        if "function_name" in signature(hook).parameters:
            hook_args["function_name"] = name
        if "function" in signature(hook).parameters:
            hook_args["function"] = func
        if "func" in signature(hook).parameters:
            hook_args["func"] = func
        if "function_call" in signature(hook).parameters:
            hook_args["function_call"] = func
        if "args" in signature(hook).parameters:
            hook_args["args"] = args
        if "arguments" in signature(hook).parameters:
            hook_args["arguments"] = args
        return hook_args

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

                hook_args = self._build_hook_args(hook, name, next_func, args)

                return hook(**hook_args)

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

    def execute(self) -> FunctionExecutionResult:
        """Runs the function call."""
        from inspect import isgenerator, isgeneratorfunction

        if self.function.entrypoint is None:
            return FunctionExecutionResult(status="failure", error="Entrypoint is not set")

        log_debug(f"Running: {self.get_call_str()}")

        # Execute pre-hook if it exists
        self._handle_pre_hook()

        entrypoint_args = self._build_entrypoint_args()

        # Check cache if enabled and not a generator function
        if self.function.cache_results and not isgeneratorfunction(self.function.entrypoint):
            cache_key = self.function._get_cache_key(entrypoint_args, self.arguments)
            cache_file = self.function._get_cache_file_path(cache_key)
            cached_result = self.function._get_cached_result(cache_file)

            if cached_result is not None:
                log_debug(f"Cache hit for: {self.get_call_str()}")
                self.result = cached_result
                return FunctionExecutionResult(status="success", result=cached_result)

        # Execute function
        execution_result: FunctionExecutionResult
        exception_to_raise = None

        try:
            # Build and execute the nested chain of hooks
            if self.function.tool_hooks is not None:
                execution_chain = self._build_nested_execution_chain(entrypoint_args=entrypoint_args)
                result = execution_chain(self.function.name, self.function.entrypoint, self.arguments or {})
            else:
                result = self.function.entrypoint(**entrypoint_args, **self.arguments)  # type: ignore

            # Handle generator case
            if isgenerator(result):
                self.result = result  # Store generator directly, can't cache
                # For generators, don't capture updated_session_state yet -
                # session_state is passed by reference, so mutations made during
                # generator iteration are already reflected in the original dict.
                # Returning None prevents stale state from being merged later.
                execution_result = FunctionExecutionResult(
                    status="success", result=self.result, updated_session_state=None
                )
            else:
                self.result = result
                # Only cache non-generator results
                if self.function.cache_results:
                    cache_key = self.function._get_cache_key(entrypoint_args, self.arguments)
                    cache_file = self.function._get_cache_file_path(cache_key)
                    self.function._save_to_cache(cache_file, self.result)

                updated_session_state = None
                if entrypoint_args.get("run_context") is not None:
                    run_context = entrypoint_args.get("run_context")
                    updated_session_state = (
                        run_context.session_state
                        if run_context is not None and run_context.session_state is not None
                        else None
                    )

                execution_result = FunctionExecutionResult(
                    status="success", result=self.result, updated_session_state=updated_session_state
                )

        except AgentRunException as e:
            log_debug(f"{e.__class__.__name__}: {e}")
            self.error = str(e)
            exception_to_raise = e
            execution_result = FunctionExecutionResult(status="failure", error=str(e))
        except Exception as e:
            log_warning(f"Could not run function {self.get_call_str()}")
            log_exception(e)
            self.error = str(e)
            execution_result = FunctionExecutionResult(status="failure", error=str(e))

        finally:
            self._handle_post_hook()

        if exception_to_raise is not None:
            raise exception_to_raise

        return execution_result

    async def _handle_pre_hook_async(self):
        """Handles the async pre-hook for the function call."""
        if self.function.pre_hook is not None:
            try:
                from inspect import signature

                pre_hook_args = {}
                # Check if the pre-hook has an agent argument
                if "agent" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["agent"] = self.function._agent
                # Check if the pre-hook has a team argument
                if "team" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["team"] = self.function._team
                # Check if the pre-hook has a run_context argument
                if "run_context" in signature(self.function.pre_hook).parameters:
                    pre_hook_args["run_context"] = self.function._run_context
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
                # Check if the post-hook has a team argument
                if "team" in signature(self.function.post_hook).parameters:
                    post_hook_args["team"] = self.function._team
                # Check if the post-hook has a run_context argument
                if "run_context" in signature(self.function.post_hook).parameters:
                    post_hook_args["run_context"] = self.function._run_context
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
        from inspect import isasyncgenfunction, iscoroutinefunction

        async def execute_entrypoint_async(name, func, args):
            """Execute the entrypoint function asynchronously."""
            arguments = entrypoint_args.copy()
            if self.arguments is not None:
                arguments.update(self.arguments)

            result = self.function.entrypoint(**arguments)  # type: ignore
            if iscoroutinefunction(self.function.entrypoint) and not isasyncgenfunction(self.function.entrypoint):
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

                hook_args = self._build_hook_args(hook, name, next_func, args)

                if iscoroutinefunction(hook):
                    return await hook(**hook_args)
                else:
                    return hook(**hook_args)

            return wrapper

        # Build the chain from inside out - reverse the hooks to start from the innermost
        hooks = list(reversed(self.function.tool_hooks))

        # Handle async and sync entrypoints
        if iscoroutinefunction(self.function.entrypoint):
            chain = reduce(create_hook_wrapper, hooks, execute_entrypoint_async)
        else:
            chain = reduce(create_hook_wrapper, hooks, execute_entrypoint)
        return chain

    async def aexecute(self) -> FunctionExecutionResult:
        """Runs the function call asynchronously."""
        from inspect import isasyncgen, isasyncgenfunction, iscoroutinefunction, isgenerator, isgeneratorfunction

        if self.function.entrypoint is None:
            return FunctionExecutionResult(status="failure", error="Entrypoint is not set")

        log_debug(f"Running: {self.get_call_str()}")

        # Execute pre-hook if it exists
        if iscoroutinefunction(self.function.pre_hook):
            await self._handle_pre_hook_async()
        else:
            self._handle_pre_hook()

        entrypoint_args = self._build_entrypoint_args()

        # Check cache if enabled and not a generator function
        if self.function.cache_results and not (
            isasyncgenfunction(self.function.entrypoint) or isgeneratorfunction(self.function.entrypoint)
        ):
            cache_key = self.function._get_cache_key(entrypoint_args, self.arguments)
            cache_file = self.function._get_cache_file_path(cache_key)
            cached_result = self.function._get_cached_result(cache_file)
            if cached_result is not None:
                log_debug(f"Cache hit for: {self.get_call_str()}")
                self.result = cached_result
                return FunctionExecutionResult(status="success", result=cached_result)

        # Execute function
        execution_result: FunctionExecutionResult
        exception_to_raise = None

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

                # Handle both sync and async entrypoints
                if isasyncgenfunction(self.function.entrypoint):
                    self.result = result  # Store async generator directly
                elif iscoroutinefunction(self.function.entrypoint):
                    self.result = await result  # Await coroutine result
                elif isgeneratorfunction(self.function.entrypoint):
                    self.result = result  # Store sync generator directly
                else:
                    self.result = result  # Sync function, result is already computed

            # Only cache if not a generator
            if self.function.cache_results and not (isgenerator(self.result) or isasyncgen(self.result)):
                cache_key = self.function._get_cache_key(entrypoint_args, self.arguments)
                cache_file = self.function._get_cache_file_path(cache_key)
                self.function._save_to_cache(cache_file, self.result)

            # For generators, don't capture updated_session_state -
            # session_state is passed by reference, so mutations made during
            # generator iteration are already reflected in the original dict.
            # Returning None prevents stale state from being merged later.
            if isgenerator(self.result) or isasyncgen(self.result):
                updated_session_state = None
            else:
                updated_session_state = None
                if entrypoint_args.get("run_context") is not None:
                    run_context = entrypoint_args.get("run_context")
                    updated_session_state = (
                        run_context.session_state
                        if run_context is not None and run_context.session_state is not None
                        else None
                    )

            execution_result = FunctionExecutionResult(
                status="success", result=self.result, updated_session_state=updated_session_state
            )

        except AgentRunException as e:
            log_debug(f"{e.__class__.__name__}: {e}")
            self.error = str(e)
            exception_to_raise = e
            execution_result = FunctionExecutionResult(status="failure", error=str(e))
        except Exception as e:
            log_warning(f"Could not run function {self.get_call_str()}")
            log_exception(e)
            self.error = str(e)
            execution_result = FunctionExecutionResult(status="failure", error=str(e))

        finally:
            if iscoroutinefunction(self.function.post_hook):
                await self._handle_post_hook_async()
            else:
                self._handle_post_hook()

        if exception_to_raise is not None:
            raise exception_to_raise

        return execution_result


class ToolResult(BaseModel):
    """Result from a tool that can include media artifacts."""

    content: str
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audios: Optional[List[Audio]] = None
    files: Optional[List[File]] = None
