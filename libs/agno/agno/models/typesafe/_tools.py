"""Build one bounded dispatch from independent Jev questions."""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agno.models.typesafe._schemas import DecisionSchema, compile_decisions, resolve_ref


@dataclass
class ToolPlan:
    schema: DecisionSchema
    names: Dict[str, str]
    arguments: Dict[str, Dict[str, Tuple[str, List[Any], Optional[str]]]] = field(default_factory=dict)
    route_members: Optional[List[str]] = None

    def dispatch(self, values: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
        selected = values["select"]
        name = self.names.get(selected)
        if name is None:
            return None, {}
        args = {}
        for arg, (key, options, presence) in self.arguments.get(name, {}).items():
            if presence and values[presence] == "omit":
                continue
            args[arg] = options[int(values[key][1:])]
        return name, args


def finite_values(node: Dict[str, Any], root: Dict[str, Any], refs: Tuple[str, ...] = ()) -> List[Any]:
    ref = node.get("$ref")
    if ref and ref in refs:
        raise ValueError("Jev does not support recursive tool schemas")
    node = resolve_ref(node, root)
    refs = (*refs, ref) if ref else refs
    if "anyOf" in node:
        values = [value for child in node["anyOf"] for value in finite_values(child, root, refs)]
    elif "enum" in node:
        values = node["enum"]
    elif "const" in node:
        values = [node["const"]]
    elif node.get("type") == "boolean":
        values = [False, True]
    elif node.get("type") == "null":
        values = [None]
    else:
        raise ValueError("Jev tool arguments must be finite enums/Literals or booleans, optionally nullable/defaulted")
    if not values or len(values) > 255 or any(isinstance(v, (dict, list)) for v in values):
        raise ValueError("Jev tool arguments need 1 to 255 scalar values")
    return values


def compile_tools(tools: List[Dict[str, Any]], tool_choice: Any, route: bool = False) -> ToolPlan:
    functions = []
    for tool in tools:
        if tool.get("type") != "function" or not tool.get("function", {}).get("name"):
            raise ValueError("Jev supports function tools only")
        functions.append(tool["function"])
    if route:
        if isinstance(tool_choice, dict):
            if tool_choice.get("function", {}).get("name") != "delegate_task_to_member":
                raise ValueError("Route mode can only call delegate_task_to_member")
        elif tool_choice not in (None, "auto", "required"):
            raise ValueError("Unsupported Jev routing tool_choice")
        if len(functions) != 1 or functions[0]["name"] != "delegate_task_to_member":
            raise ValueError("Jev route mode requires a Team in route mode with only its member delegation tool")
        routing = functions[0].get("parameters", {}).get("x-agno-route")
        if not routing or not routing.get("passthrough"):
            raise ValueError("Jev routing requires determine_input_for_members=False and a current member roster")
        members = routing["members"]
        if not members or len({member["id"] for member in members}) != len(members):
            raise ValueError("Jev routing requires nonempty, unique member IDs")
        criteria = {member["id"]: member["description"] for member in members}
        schema = compile_decisions(
            {
                "select": {
                    "type": "choice",
                    "instructions": "Select the best member for the current input, following the routing instructions.",
                    "criteria": criteria,
                }
            }
        )
        return ToolPlan(schema, {key: "delegate_task_to_member" for key in criteria}, route_members=list(criteria))
    if not functions:
        raise ValueError("Jev tools mode needs at least one finite function tool")
    if len({fn["name"] for fn in functions}) != len(functions):
        raise ValueError("Jev tool names must be unique")
    forced = None
    if isinstance(tool_choice, dict):
        forced = tool_choice.get("function", {}).get("name")
        if forced not in {fn["name"] for fn in functions}:
            raise ValueError("Forced tool is not in the available tools")
    elif tool_choice not in (None, "auto", "required", "none"):
        raise ValueError("Unsupported Jev tool_choice")
    selected_functions = [fn for fn in functions if forced is None or fn["name"] == forced]
    names = {f"t{i}": fn["name"] for i, fn in enumerate(selected_functions)}
    criteria = {
        key: {"name": fn["name"], "description": fn.get("description", "")}
        for key, fn in zip(names, selected_functions)
    }
    if not forced and tool_choice != "required":
        criteria["none"] = "No available tool is appropriate for the input"
    questions: Dict[str, Any] = {
        "select": {
            "type": "choice",
            "instructions": "Choose at most one appropriate tool for the current input.",
            "criteria": criteria,
        }
    }
    arguments: Dict[str, Any] = {}
    for i, fn in enumerate(selected_functions):
        root = fn.get("parameters", {"type": "object", "properties": {}})
        if root.get("type") != "object" or root.get("additionalProperties") not in (None, False):
            raise ValueError("Jev tools need fixed object parameters")
        arguments[fn["name"]] = {}
        for j, (name, prop) in enumerate(root.get("properties", {}).items()):
            options = finite_values(prop, root)
            key = f"arg{i}_{j}"
            premise = {
                "assumption": f"Assume tool {fn['name']} has been selected. Decide argument {name} independently from the state.",
                "tool": fn.get("description"),
                "argument": prop.get("description"),
            }
            questions[key] = {
                "type": "choice",
                "instructions": premise,
                "criteria": {f"v{k}": json.dumps(value) for k, value in enumerate(options)},
            }
            presence = None
            if name not in root.get("required", []):
                presence = f"present{i}_{j}"
                questions[presence] = {
                    "type": "choice",
                    "instructions": {
                        **premise,
                        "decision": "Should this optional argument be supplied, or omitted to use its default?",
                        "default": prop.get("default"),
                    },
                    "criteria": {"supply": "Supply a value", "omit": "Omit the argument and use its default"},
                }
            arguments[fn["name"]][name] = (key, options, presence)
    return ToolPlan(compile_decisions(questions), names, arguments)
