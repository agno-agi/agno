import json
from typing import Any, Dict, Optional

from agno.tools.function import Function, FunctionCall
from agno.utils.log import log_debug, log_error


def get_function_call(
    name: str,
    arguments: Optional[str] = None,
    call_id: Optional[str] = None,
    functions: Optional[Dict[str, Function]] = None,
) -> Optional[FunctionCall]:
    log_debug(f"Getting function {name}")
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
            if function_to_call.sanitize_arguments:
                if "None" in arguments:
                    arguments = arguments.replace("None", "null")
                if "True" in arguments:
                    arguments = arguments.replace("True", "true")
                if "False" in arguments:
                    arguments = arguments.replace("False", "false")
            _arguments = json.loads(arguments)
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
