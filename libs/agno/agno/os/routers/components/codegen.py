"""Deterministic Python export for database-backed AgentOS components."""

from __future__ import annotations

import inspect
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Set, Tuple

from agno.models.utils import MODEL_PROVIDER_CLASSES, _resolve_provider_key
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.registry import Registry


_COMPONENT_TYPES = {"agent", "team", "workflow"}
_SECRET_KEYS = {
    "access_key",
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "authorization",
    "bearer_token",
    "client_secret",
    "connection_string",
    "credential",
    "credentials",
    "database_url",
    "db_url",
    "dsn",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
}


@dataclass(frozen=True)
class _Expression:
    code: str


@dataclass
class _ComponentNode:
    component_id: str
    component_type: str
    version: Optional[int]
    config: Dict[str, Any]
    source: str


class _PythonComponentExporter:
    def __init__(
        self,
        db: "BaseDb",
        registry: Optional["Registry"],
        include_dependencies: bool,
    ) -> None:
        self.db = db
        self.registry = registry
        self.include_dependencies = include_dependencies
        self.nodes: List[_ComponentNode] = []
        self.node_keys: Set[Tuple[str, Optional[int], str]] = set()
        self.visiting: Set[Tuple[str, Optional[int], str]] = set()
        self.warnings: List[str] = []
        self._warning_set: Set[str] = set()
        self.exportable = True
        self.environment_variables: Set[str] = set()

        self.imports: Dict[Tuple[str, str], str] = {}
        self.used_import_aliases: Set[str] = {"Agent", "Registry", "Team", "Workflow"}
        self.registry_tools: List[str] = []
        self.registry_functions: List[str] = []
        self.registry_schemas: List[str] = []
        self.placeholder_blocks: List[str] = []
        self.resource_setup_lines: List[str] = []
        self.toolkit_expressions: Dict[str, str] = {}
        self.tool_expressions: Dict[Tuple[Optional[str], str], str] = {}
        self.function_toolkits: Dict[str, str] = {}
        self.schema_expressions: Dict[str, str] = {}
        self.model_expressions: Dict[Tuple[str, str, str], str] = {}
        self.used_resource_variables: Set[str] = set()
        self._resource_keys: Set[Tuple[str, str]] = set()
        self._placeholder_count = 0

    def export(self, component_id: str, version: Optional[int]) -> Dict[str, Any]:
        root = self._collect_db_node(component_id, version=version, component_type=None)
        if root is None:
            raise ValueError(f"Component config not found: {component_id} v{version or 'current'}")

        self._collect_resources()
        source = self._render_source(root)
        env_example = self._render_env_example()
        readme = self._render_readme(root)

        return {
            "component_id": root.component_id,
            "component_type": root.component_type,
            "version": root.version,
            "language": "python",
            "entrypoint": "main.py",
            "files": [
                {"path": "main.py", "content": source},
                {"path": "requirements.txt", "content": "agno\n"},
                {"path": ".env.example", "content": env_example},
                {"path": "README.md", "content": readme},
            ],
            "requirements": ["agno"],
            "warnings": self.warnings,
            "exportable": self.exportable,
        }

    def _collect_db_node(
        self,
        component_id: str,
        version: Optional[int],
        component_type: Optional[str],
    ) -> Optional[_ComponentNode]:
        component = self.db.get_component(component_id)
        if component is None:
            return self._collect_registry_node(component_id, component_type)

        raw_type = component.get("component_type") or component_type or ""
        resolved_type = str(getattr(raw_type, "value", raw_type))
        if resolved_type not in _COMPONENT_TYPES:
            self._warn(f"Component '{component_id}' has unsupported type '{resolved_type}'.", blocking=True)
            return None

        config_row = self.db.get_config(component_id, version=version)
        if not isinstance(config_row, dict) or not isinstance(config_row.get("config"), dict):
            return None

        resolved_version = config_row.get("version")
        if not isinstance(resolved_version, int):
            resolved_version = version or component.get("current_version")

        key = (component_id, resolved_version, "db")
        if key in self.node_keys:
            return next(
                node
                for node in self.nodes
                if (node.component_id, node.version, node.source) == key
            )
        if key in self.visiting:
            self._warn(f"Cycle detected while exporting component '{component_id}'.", blocking=True)
            return None

        self.visiting.add(key)
        node = _ComponentNode(
            component_id=component_id,
            component_type=resolved_type,
            version=resolved_version,
            config=deepcopy(config_row["config"]),
            source="db",
        )
        self._collect_dependencies(node)
        self.visiting.remove(key)
        self.node_keys.add(key)
        self.nodes.append(node)
        return node

    def _collect_registry_node(
        self,
        component_id: str,
        component_type: Optional[str],
    ) -> Optional[_ComponentNode]:
        if self.registry is None or component_type not in {"agent", "team"}:
            return None

        if component_type == "agent":
            component = self.registry.get_agent(component_id)
        else:
            component = self.registry.get_team(component_id)
        if component is None:
            return None

        key = (component_id, None, "registry")
        if key in self.node_keys:
            return next(
                node
                for node in self.nodes
                if (node.component_id, node.version, node.source) == key
            )
        if key in self.visiting:
            self._warn(f"Cycle detected while exporting registry component '{component_id}'.", blocking=True)
            return None

        self.visiting.add(key)
        config = component.to_dict()
        node = _ComponentNode(
            component_id=component_id,
            component_type=component_type,
            version=None,
            config=deepcopy(config),
            source="registry",
        )
        self._collect_dependencies(node)
        self.visiting.remove(key)
        self.node_keys.add(key)
        self.nodes.append(node)
        self._warn(
            f"Dependency '{component_id}' is code-defined; the export contains its serialized configuration, "
            "not its original source."
        )
        return node

    def _collect_dependencies(self, node: _ComponentNode) -> None:
        references = list(self._iter_references(node.config, node.component_type))
        if not references:
            return
        if not self.include_dependencies:
            for component_type, component_id in references:
                self._warn(
                    f"Dependency '{component_id}' ({component_type}) was not included in the export.",
                    blocking=True,
                )
            return

        link_versions: Dict[str, List[Optional[int]]] = {}
        if node.source == "db" and node.version is not None:
            for link in self.db.get_links(node.component_id, node.version):
                child_id = link.get("child_component_id")
                if isinstance(child_id, str):
                    link_versions.setdefault(child_id, []).append(link.get("child_version"))

        for component_type, component_id in references:
            if component_type == "workflow":
                self._warn(
                    f"Nested workflow '{component_id}' cannot be rehydrated exactly by the current "
                    "Workflow.from_dict contract.",
                    blocking=True,
                )
            versions = link_versions.get(component_id) or []
            child_version = versions.pop(0) if versions else None
            child = self._collect_db_node(component_id, child_version, component_type)
            if child is None:
                self._warn(
                    f"Referenced {component_type} '{component_id}' could not be exported from the component "
                    "DB or registry.",
                    blocking=True,
                )
            elif child.source == "db" and child_version is None:
                self._warn(
                    f"Dependency '{component_id}' is not version-pinned; its current version was exported."
                )

    def _iter_references(
        self,
        config: Dict[str, Any],
        component_type: str,
    ) -> Iterable[Tuple[str, str]]:
        if component_type == "team":
            for member in config.get("members") or []:
                if not isinstance(member, dict):
                    continue
                member_type = member.get("type")
                id_key = "agent_id" if member_type == "agent" else "team_id"
                member_id = member.get(id_key)
                if member_type in {"agent", "team"} and isinstance(member_id, str):
                    yield member_type, member_id

        if component_type != "workflow":
            return

        for step in _iter_step_configs(config.get("steps") or []):
            for reference_type, key in (
                ("agent", "agent_id"),
                ("team", "team_id"),
                ("workflow", "workflow_id"),
            ):
                reference_id = step.get(key)
                if isinstance(reference_id, str):
                    yield reference_type, reference_id

    def _collect_resources(self) -> None:
        executor_names: Set[str] = set()
        tool_dicts: List[Dict[str, Any]] = []
        schema_names: Set[str] = set()

        for node in self.nodes:
            tools = node.config.get("tools")
            if isinstance(tools, list):
                tool_dicts.extend(tool for tool in tools if isinstance(tool, dict))
            for schema_key in ("input_schema", "output_schema"):
                schema_name = node.config.get(schema_key)
                if isinstance(schema_name, str):
                    schema_names.add(schema_name)
            if node.component_type == "workflow":
                for step in _iter_step_configs(node.config.get("steps") or []):
                    executor_ref = step.get("executor_ref")
                    if isinstance(executor_ref, str):
                        executor_names.add(executor_ref)
                    for function_key, type_key in (
                        ("end_condition", "end_condition_type"),
                        ("evaluator", "evaluator_type"),
                        ("selector", "selector_type"),
                    ):
                        function_name = step.get(function_key)
                        if step.get(type_key) == "function" and isinstance(function_name, str):
                            executor_names.add(function_name)
            for model_key in ("model", "output_model", "parser_model", "reasoning_model"):
                self._collect_model(node, model_key)

        self._collect_tools(tool_dicts)
        for function_name in sorted(executor_names):
            self._collect_function(function_name, destination="functions")
        for schema_name in sorted(schema_names):
            self._collect_schema(schema_name)

    def _collect_model(self, node: _ComponentNode, model_key: str) -> None:
        model = node.config.get(model_key)
        if not isinstance(model, dict) or not model.get("id"):
            return
        provider_key = _resolve_provider_key(model.get("provider"), model.get("name"))
        if provider_key not in MODEL_PROVIDER_CLASSES:
            self._warn(
                f"Model provider '{model.get('provider')}' for component '{node.component_id}' cannot be "
                "reconstructed from the stored config.",
                blocking=True,
            )
            return

        module, class_name = MODEL_PROVIDER_CLASSES[provider_key]
        alias = self._add_import(module, class_name)
        identity = _model_identity(model)
        self.model_expressions[identity] = f"{alias}(id={model['id']!r})"

    def _collect_tools(self, tool_dicts: List[Dict[str, Any]]) -> None:
        toolkit_functions: Dict[str, Set[str]] = {}
        standalone_functions: Set[str] = set()
        for tool in tool_dicts:
            name = tool.get("name")
            if not isinstance(name, str) or "parameters" not in tool:
                continue
            toolkit_name = tool.get("toolkit")
            if isinstance(toolkit_name, str) and toolkit_name:
                toolkit_functions.setdefault(toolkit_name, set()).add(name)
            else:
                direct_function = self._find_function(name, toolkit_name=None)
                matching_toolkits = self._find_toolkits_for_function(name)
                if direct_function is None and len(matching_toolkits) == 1:
                    inferred_toolkit = matching_toolkits[0]
                    toolkit_functions.setdefault(inferred_toolkit.name, set()).add(name)
                    self.function_toolkits[name] = inferred_toolkit.name
                else:
                    standalone_functions.add(name)

        for toolkit_name, function_names in sorted(toolkit_functions.items()):
            toolkit = self._find_toolkit(toolkit_name)
            can_import_toolkit = (
                toolkit is not None
                and self._is_importable(type(toolkit))
                and not self._has_required_init_args(toolkit)
            )
            if can_import_toolkit and toolkit is not None:
                alias = self._add_import(type(toolkit).__module__, type(toolkit).__name__)
                variable = self._resource_variable(f"{toolkit_name}_tools")
                self.resource_setup_lines.append(f"{variable} = {alias}()")
                self.toolkit_expressions[toolkit_name] = variable
                self._append_resource("tools", variable, key=("toolkit", toolkit_name))
                self._warn(
                    f"Toolkit '{toolkit_name}' was recreated with its default constructor; restore any custom "
                    "local settings."
                )
                continue
            for function_name in sorted(function_names):
                self._collect_function(function_name, destination="tools", toolkit_name=toolkit_name)
            self._warn(
                f"Toolkit '{toolkit_name}' could not be recreated from stored configuration; placeholder "
                "functions were generated.",
                blocking=True,
            )

        for function_name in sorted(standalone_functions):
            self._collect_function(function_name, destination="tools")

    def _collect_function(
        self,
        function_name: str,
        destination: str,
        toolkit_name: Optional[str] = None,
    ) -> None:
        resource_key = (destination, f"{toolkit_name or ''}:{function_name}")
        if resource_key in self._resource_keys:
            return

        function = self._find_function(function_name, toolkit_name)
        if function is not None and self._is_importable(function):
            alias = self._add_import(function.__module__, function.__name__)
            self._append_resource(destination, alias, key=resource_key)
            if destination == "tools":
                self.tool_expressions[(toolkit_name, function_name)] = alias
            return

        placeholder = self._add_placeholder(function_name, destination)
        self._append_resource(destination, placeholder, key=resource_key)
        if destination == "tools":
            self.tool_expressions[(toolkit_name, function_name)] = placeholder
        label = "workflow executor" if destination == "functions" else "tool"
        self._warn(
            f"The {label} '{function_name}' has no importable registry source; a placeholder was generated.",
            blocking=True,
        )

    def _collect_schema(self, schema_name: str) -> None:
        key = ("schema", schema_name)
        if key in self._resource_keys:
            return
        schema = self.registry.get_schema(schema_name) if self.registry is not None else None
        if schema is not None and self._is_importable(schema):
            alias = self._add_import(schema.__module__, schema.__name__)
            self._append_resource("schemas", alias, key=key)
            self.schema_expressions[schema_name] = alias
            return
        self._warn(
            f"Schema '{schema_name}' has no importable registry source and will be skipped while loading the "
            "component.",
            blocking=True,
        )

    def _find_toolkit(self, toolkit_name: str) -> Optional[Toolkit]:
        if self.registry is None:
            return None
        return next(
            (
                tool
                for tool in self.registry.tools
                if isinstance(tool, Toolkit) and tool.name == toolkit_name
            ),
            None,
        )

    def _find_toolkits_for_function(self, function_name: str) -> List[Toolkit]:
        if self.registry is None:
            return []
        matches: List[Toolkit] = []
        for tool in self.registry.tools:
            if not isinstance(tool, Toolkit):
                continue
            if any(function.name == function_name for function in tool.get_functions().values()):
                matches.append(tool)
        return matches

    def _find_function(
        self,
        function_name: str,
        toolkit_name: Optional[str],
    ) -> Optional[Any]:
        if self.registry is None:
            return None
        if toolkit_name:
            toolkit = self._find_toolkit(toolkit_name)
            if toolkit is not None:
                function = next(
                    (func for func in toolkit.get_functions().values() if func.name == function_name),
                    None,
                )
                if function is not None:
                    return function.entrypoint

        registered = self.registry.get_function(function_name)
        if registered is not None:
            return registered
        for tool in self.registry.tools:
            if isinstance(tool, Function) and tool.name == function_name:
                return tool.entrypoint
            if callable(tool) and getattr(tool, "__name__", None) == function_name:
                return tool
        return None

    def _is_importable(self, value: Any) -> bool:
        module = getattr(value, "__module__", None)
        name = getattr(value, "__name__", None)
        qualname = getattr(value, "__qualname__", name)
        return bool(
            module
            and module != "__main__"
            and name
            and qualname == name
            and "<locals>" not in qualname
        )

    def _has_required_init_args(self, toolkit: Toolkit) -> bool:
        try:
            signature = inspect.signature(type(toolkit).__init__)
        except (TypeError, ValueError):
            return True
        return any(
            parameter.name != "self"
            and parameter.default is inspect.Parameter.empty
            and parameter.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            for parameter in signature.parameters.values()
        )

    def _add_import(self, module: str, name: str) -> str:
        key = (module, name)
        existing = self.imports.get(key)
        if existing is not None:
            return existing
        alias = name
        suffix = 2
        while alias in self.used_import_aliases:
            alias = f"{name}_{suffix}"
            suffix += 1
        self.imports[key] = alias
        self.used_import_aliases.add(alias)
        if not module.startswith("agno."):
            self._warn(f"The exported project requires the external module '{module}'.")
        return alias

    def _resource_variable(self, name: str) -> str:
        base = _safe_identifier(name)
        variable = base
        suffix = 2
        while variable in self.used_resource_variables:
            variable = f"{base}_{suffix}"
            suffix += 1
        self.used_resource_variables.add(variable)
        return variable

    def _append_resource(
        self,
        destination: str,
        expression: str,
        key: Tuple[str, str],
    ) -> None:
        if key in self._resource_keys:
            return
        self._resource_keys.add(key)
        if destination == "tools":
            self.registry_tools.append(expression)
        elif destination == "functions":
            self.registry_functions.append(expression)
        else:
            self.registry_schemas.append(expression)

    def _add_placeholder(self, original_name: str, destination: str) -> str:
        self._placeholder_count += 1
        variable = _safe_identifier(f"missing_{destination}_{original_name}_{self._placeholder_count}")
        message = f"Provide a local implementation for {original_name} before running this component."
        self.placeholder_blocks.append(
            f"def {variable}(*args, **kwargs):\n"
            f"    raise NotImplementedError({message!r})\n\n"
            f"{variable}.__name__ = {original_name!r}"
        )
        return variable

    def _prepare_constructor_config(
        self,
        node: _ComponentNode,
        config: Dict[str, Any],
        variable_names: Dict[Tuple[str, Optional[int], str], str],
    ) -> Optional[Dict[str, Any]]:
        if node.component_type == "workflow":
            return None

        from agno.agent import Agent
        from agno.team import Team

        constructor = Agent if node.component_type == "agent" else Team
        supported_fields = set(inspect.signature(constructor.__init__).parameters) - {"self"}
        result = dict(config)

        for model_key in ("model", "output_model", "parser_model", "reasoning_model"):
            model = result.get(model_key)
            if isinstance(model, dict):
                expression = self.model_expressions.get(_model_identity(model))
                if expression is not None:
                    result[model_key] = _Expression(expression)
                else:
                    result.pop(model_key, None)

        tools = result.get("tools")
        if isinstance(tools, list):
            result["tools"] = self._component_tool_expressions(tools)

        for schema_key in ("input_schema", "output_schema"):
            schema_name = result.get(schema_key)
            if not isinstance(schema_name, str):
                continue
            expression = self.schema_expressions.get(schema_name)
            if expression is not None:
                result[schema_key] = _Expression(expression)
            else:
                result.pop(schema_key, None)

        learning = result.get("learning")
        if isinstance(learning, dict):
            alias = self._add_import("agno.learn.machine", "LearningMachine")
            result["learning"] = _Expression(
                f"{alias}.from_dict({_render_value(learning)})"
            )

        if node.component_type == "team":
            mode = result.get("mode")
            if isinstance(mode, str):
                alias = self._add_import("agno.team.mode", "TeamMode")
                result["mode"] = _Expression(f"{alias}({mode!r})")
            result["members"] = self._member_expressions(node, variable_names)

        for field_name in list(result):
            if field_name in supported_fields:
                continue
            result.pop(field_name)
            self._warn(
                f"Stored field '{field_name}' on component '{node.component_id}' is not accepted by the "
                f"current {constructor.__name__} constructor and was omitted.",
                blocking=True,
            )
        return result

    def _component_tool_expressions(self, tools: List[Any]) -> List[Any]:
        selected_by_toolkit: Dict[str, Set[str]] = {}
        for tool in tools:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                continue
            name = tool["name"]
            toolkit_name = tool.get("toolkit") or self.function_toolkits.get(name)
            if isinstance(toolkit_name, str):
                selected_by_toolkit.setdefault(toolkit_name, set()).add(name)

        result: List[Any] = []
        emitted_toolkits: Set[str] = set()
        for tool in tools:
            if not isinstance(tool, dict) or "parameters" not in tool:
                result.append(tool)
                continue
            name = tool.get("name")
            if not isinstance(name, str):
                continue

            toolkit_name = tool.get("toolkit") or self.function_toolkits.get(name)
            if isinstance(toolkit_name, str) and toolkit_name in self.toolkit_expressions:
                if toolkit_name in emitted_toolkits:
                    continue
                toolkit = self._find_toolkit(toolkit_name)
                if toolkit is not None:
                    available_names = {
                        function.name
                        for function in toolkit.get_functions().values()
                    }
                else:
                    available_names = set()
                selected_names = selected_by_toolkit.get(toolkit_name, set())
                toolkit_expression = self.toolkit_expressions[toolkit_name]
                if selected_names == available_names:
                    result.append(_Expression(toolkit_expression))
                    emitted_toolkits.add(toolkit_name)
                    continue

                for selected_name in sorted(selected_names):
                    result.append(
                        _Expression(
                            f"{toolkit_expression}.get_functions()[{selected_name!r}].entrypoint"
                        )
                    )
                emitted_toolkits.add(toolkit_name)
                continue

            expression = self.tool_expressions.get((toolkit_name, name))
            if expression is None:
                expression = self.tool_expressions.get((None, name))
            if expression is not None:
                result.append(_Expression(expression))
        return result

    def _member_expressions(
        self,
        node: _ComponentNode,
        variable_names: Dict[Tuple[str, Optional[int], str], str],
    ) -> List[_Expression]:
        variables_by_id: Dict[str, str] = {}
        for dependency in self.nodes:
            if dependency is node:
                continue
            variables_by_id.setdefault(
                dependency.component_id,
                variable_names[self._node_key(dependency)],
            )

        members: List[_Expression] = []
        for member in node.config.get("members") or []:
            if not isinstance(member, dict):
                continue
            member_id = member.get("agent_id") or member.get("team_id")
            variable = variables_by_id.get(member_id) if isinstance(member_id, str) else None
            if variable is None:
                self._warn(
                    f"Team member '{member_id}' could not be bound in generated constructor code.",
                    blocking=True,
                )
                continue
            members.append(_Expression(variable))
        return members

    def _render_source(self, root: _ComponentNode) -> str:
        variable_names = self._variable_names()
        sanitized_configs = {
            self._node_key(node): self._sanitize_config(node)
            for node in self.nodes
        }
        constructor_configs = {
            self._node_key(node): self._prepare_constructor_config(
                node,
                sanitized_configs[self._node_key(node)],
                variable_names,
            )
            for node in self.nodes
        }

        imports = ["from agno.registry import Registry"]
        node_types = {node.component_type for node in self.nodes}
        if "agent" in node_types:
            imports.append("from agno.agent import Agent")
        if "team" in node_types:
            imports.append("from agno.team import Team")
        if "workflow" in node_types:
            imports.append("from agno.workflow import Workflow")
        if self.environment_variables:
            imports.insert(0, "import os")
        for (module, name), alias in sorted(self.imports.items()):
            import_line = f"from {module} import {name}"
            if alias != name:
                import_line += f" as {alias}"
            imports.append(import_line)

        lines = [
            '"""Generated by AgentOS from a versioned Studio component.',
            "",
            "Review the warnings returned by the export API before running this file.",
            '"""',
            "",
            *imports,
            "",
        ]
        if self.placeholder_blocks:
            lines.extend(["\n\n".join(self.placeholder_blocks), ""])
        if self.resource_setup_lines:
            lines.extend(["\n".join(self.resource_setup_lines), ""])

        registry_args = []
        if self.registry_tools:
            registry_tools = [_Expression(value) for value in self.registry_tools]
            registry_args.append(f"tools={_render_value(registry_tools, 4)}")
        if self.registry_functions:
            registry_args.append(
                f"functions={_render_value([_Expression(value) for value in self.registry_functions], 4)}"
            )
        if self.registry_schemas:
            registry_schemas = [_Expression(value) for value in self.registry_schemas]
            registry_args.append(f"schemas={_render_value(registry_schemas, 4)}")

        if registry_args:
            lines.append("registry = Registry(")
            lines.extend(f"    {argument}," for argument in registry_args)
            lines.append(")")
        else:
            lines.append("registry = Registry()")
        lines.append("")

        for node in self.nodes:
            node_key = self._node_key(node)
            variable = variable_names[node_key]
            config_variable = f"{variable}_config"
            component_class = node.component_type.capitalize()
            lines.append(f"# {node.component_type} {node.component_id!r}, version {node.version or 'registry'}")
            constructor_config = constructor_configs[node_key]
            if constructor_config is not None:
                lines.append(f"{variable} = {_render_call(component_class, constructor_config)}")
            else:
                lines.append(f"{config_variable} = {_render_value(sanitized_configs[node_key])}")
                lines.append(f"{variable} = {component_class}.from_dict({config_variable}, registry=registry)")
            if node.component_type == "agent":
                lines.append(f"registry.agents.append({variable})")
            elif node.component_type == "team":
                lines.append(f"registry.teams.append({variable})")
            lines.append("")

        root_variable = variable_names[self._node_key(root)]
        lines.extend(
            [
                f"component = {root_variable}",
                "",
                "",
                'if __name__ == "__main__":',
                '    component.print_response("Replace with your input")',
                "",
            ]
        )
        return "\n".join(lines)

    def _sanitize_config(self, node: _ComponentNode) -> Dict[str, Any]:
        config = deepcopy(node.config)
        config.setdefault("id", node.component_id)
        if "db" in config:
            config.pop("db", None)
            self._warn(
                f"Database configuration for component '{node.component_id}' was omitted; configure local "
                "persistence separately."
            )
        if "knowledge" in config:
            config.pop("knowledge", None)
            self._warn(
                f"Knowledge configuration for component '{node.component_id}' was omitted because the DB stores "
                "only a registry reference.",
                blocking=True,
            )
        return self._sanitize_value(config, path=(node.component_id,))

    def _sanitize_value(self, value: Any, path: Tuple[str, ...]) -> Any:
        if isinstance(value, dict):
            result: Dict[str, Any] = {}
            for key, nested in value.items():
                key_string = str(key)
                nested_path = (*path, key_string)
                normalized_key = key_string.lower().replace("-", "_")
                if _is_sensitive_key(normalized_key) and nested is not None:
                    env_name = _environment_name(nested_path)
                    self.environment_variables.add(env_name)
                    result[key] = _Expression(f'os.getenv("{env_name}")')
                else:
                    result[key] = self._sanitize_value(nested, nested_path)
            return result
        if isinstance(value, list):
            return [
                self._sanitize_value(item, (*path, str(index)))
                for index, item in enumerate(value)
            ]
        if isinstance(value, tuple):
            return [
                self._sanitize_value(item, (*path, str(index)))
                for index, item in enumerate(value)
            ]
        if value is None or isinstance(value, (bool, float, int, str)):
            return value
        self._warn(
            f"Unsupported value at '{'.'.join(path)}' was omitted from the generated configuration.",
            blocking=True,
        )
        return None

    def _variable_names(self) -> Dict[Tuple[str, Optional[int], str], str]:
        names: Dict[Tuple[str, Optional[int], str], str] = {}
        used: Set[str] = set()
        versions_by_id: Dict[str, Set[Optional[int]]] = {}
        for node in self.nodes:
            versions_by_id.setdefault(node.component_id, set()).add(node.version)
            base = _safe_identifier(f"{node.component_type}_{node.component_id}")
            name = base
            if name in used:
                version_suffix = f"v{node.version}" if node.version is not None else node.source
                name = _safe_identifier(f"{base}_{version_suffix}")
            suffix = 2
            while name in used:
                name = f"{base}_{suffix}"
                suffix += 1
            used.add(name)
            names[self._node_key(node)] = name

        for component_id, versions in versions_by_id.items():
            if len(versions) > 1:
                self._warn(
                    f"Multiple versions of dependency '{component_id}' are present; Registry ID lookup cannot "
                    "preserve both versions exactly.",
                    blocking=True,
                )
        return names

    def _render_env_example(self) -> str:
        if not self.environment_variables:
            return "# No secrets were included in this export.\n"
        return "".join(f"{name}=\n" for name in sorted(self.environment_variables))

    def _render_readme(self, root: _ComponentNode) -> str:
        warning_section = ""
        if self.warnings:
            rendered_warnings = "\n".join(f"- {warning}" for warning in self.warnings)
            warning_section = f"\n## Export warnings\n\n{rendered_warnings}\n"
        return (
            f"# {root.component_id}\n\n"
            f"Generated from the `{root.component_type}` component at version `{root.version}`.\n\n"
            "## Run locally\n\n"
            "```bash\n"
            "python -m venv .venv\n"
            "source .venv/bin/activate\n"
            "pip install -r requirements.txt\n"
            "python main.py\n"
            "```\n"
            "\nExport the variables listed in `.env.example` before running.\n"
            f"{warning_section}"
        )

    def _warn(self, message: str, blocking: bool = False) -> None:
        if message not in self._warning_set:
            self._warning_set.add(message)
            self.warnings.append(message)
        if blocking:
            self.exportable = False

    @staticmethod
    def _node_key(node: _ComponentNode) -> Tuple[str, Optional[int], str]:
        return node.component_id, node.version, node.source


def generate_component_code(
    db: "BaseDb",
    registry: Optional["Registry"],
    component_id: str,
    version: Optional[int] = None,
    include_dependencies: bool = True,
) -> Dict[str, Any]:
    """Generate a local Python project for a versioned DB component."""
    return _PythonComponentExporter(
        db=db,
        registry=registry,
        include_dependencies=include_dependencies,
    ).export(component_id=component_id, version=version)


def _render_call(name: str, kwargs: Dict[str, Any]) -> str:
    if not kwargs:
        return f"{name}()"
    lines = [f"{name}("]
    for key, value in kwargs.items():
        lines.append(f"    {key}={_render_value(value, 4)},")
    lines.append(")")
    return "\n".join(lines)


def _render_value(value: Any, indent: int = 0) -> str:
    if isinstance(value, _Expression):
        return value.code
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = ["{"]
        for key, nested in value.items():
            rendered = _render_value(nested, indent + 4)
            lines.append(f"{' ' * (indent + 4)}{key!r}: {rendered},")
        lines.append(f"{' ' * indent}}}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = ["["]
        for nested in value:
            rendered = _render_value(nested, indent + 4)
            lines.append(f"{' ' * (indent + 4)}{rendered},")
        lines.append(f"{' ' * indent}]")
        return "\n".join(lines)
    return repr(value)


def _safe_identifier(value: str) -> str:
    identifier = re.sub(r"\W+", "_", value).strip("_").lower()
    if not identifier:
        identifier = "component"
    if identifier[0].isdigit():
        identifier = f"component_{identifier}"
    return identifier


def _environment_name(path: Tuple[str, ...]) -> str:
    value = "_".join(path)
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _model_identity(model: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(model.get("provider") or ""),
        str(model.get("name") or ""),
        str(model.get("id") or ""),
    )


def _is_sensitive_key(key: str) -> bool:
    return key in _SECRET_KEYS or key.endswith(
        ("_access_key", "_api_key", "_password", "_private_key", "_secret", "_token")
    )


def _iter_step_configs(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, list):
        for nested in value:
            yield from _iter_step_configs(nested)
        return
    if not isinstance(value, dict):
        return

    yield value
    for child_key in ("choices", "else_steps", "steps"):
        yield from _iter_step_configs(value.get(child_key))
