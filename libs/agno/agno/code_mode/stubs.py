from collections import OrderedDict
from inspect import getdoc
from typing import AbstractSet, Any, Callable, Dict, List, Union

from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_warning


def should_include(func: Function) -> bool:
    for attr in ("requires_confirmation", "requires_user_input", "external_execution"):
        if getattr(func, attr, None):
            log_warning(f"CodeMode: Excluding '{func.name}' ({attr})")
            return False
    return True


def _prepare_function(func: Function) -> Function:
    func = func.model_copy(deep=True)
    if not func.skip_entrypoint_processing:
        func.process_entrypoint()
    return func


def collect_functions(
    tools: List[Union[Toolkit, Callable, Function]],
    async_mode: bool = False,
) -> Dict[str, Function]:
    collected: Dict[str, Function] = OrderedDict()
    for item in tools:
        if isinstance(item, Toolkit):
            toolkit_funcs = item.get_async_functions() if async_mode else item.get_functions()
            for name, func in toolkit_funcs.items():
                if should_include(func):
                    collected[name] = _prepare_function(func)
        elif isinstance(item, Function):
            if should_include(item):
                prepared = _prepare_function(item)
                collected[prepared.name] = prepared
        elif callable(item):
            func = Function.from_callable(item)
            if should_include(func):
                collected[func.name] = func
    return collected


def generate_stub_map(
    functions: Dict[str, Function],
    framework_params: AbstractSet[str],
    json_type_map: Dict[str, str],
) -> Dict[str, str]:
    stub_map: Dict[str, str] = OrderedDict()
    for name, func in functions.items():
        params = func.parameters.get("properties", {})
        required = set(func.parameters.get("required", []))

        args: List[str] = []
        for pname, schema in params.items():
            if pname in framework_params:
                continue
            py_type = json_type_map.get(schema.get("type", "string"), "Any")
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
        doc = doc.replace('"""', "'''")

        sig = ", ".join(args)
        stub = f"def {name}({sig}) -> str:\n"
        stub += f'    """{doc}\n    """'
        stub_map[name] = stub
    return stub_map


def generate_catalog(functions: Dict[str, Function]) -> str:
    lines = []
    for name, func in functions.items():
        desc = func.description or "No description"
        first_line = desc.split("\n")[0][:100]
        lines.append(f"- {name}: {first_line}")
    return "\n".join(lines)


def resolve_discovery(
    code_model: Any,
    discovery: Union[bool, str],
    function_count: int,
    threshold: int,
) -> bool:
    if code_model is not None:
        return False
    if discovery == "auto":
        return function_count > threshold
    if isinstance(discovery, bool):
        return discovery
    raise ValueError(f"discovery must be True, False, or 'auto', got {discovery!r}")
