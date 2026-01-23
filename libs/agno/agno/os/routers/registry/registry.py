import inspect
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    RegistryContentResponse,
    RegistryContentType,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.registry import Registry
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_error


def get_registry_router(registry: Registry, settings: AgnoAPISettings = AgnoAPISettings()) -> APIRouter:
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Registry"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )
    return attach_routes(router=router, registry=registry)


def attach_routes(router: APIRouter, registry: Registry) -> APIRouter:
    def _safe_str(v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s or None
        return str(v)

    def _safe_name(obj: Any, fallback: str) -> str:
        n = getattr(obj, "name", None)
        n = _safe_str(n)
        return n or fallback

    def _class_path(obj: Any) -> str:
        cls = obj.__class__
        return f"{cls.__module__}.{cls.__name__}"

    def _maybe_jsonable(value: Any) -> Any:
        # Keep only data that is likely JSON serializable
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [_maybe_jsonable(x) for x in value]
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for k, v in value.items():
                out[str(k)] = _maybe_jsonable(v)
            return out
        # Fallback to string to avoid serialization errors
        return str(value)

    def _get_callable_params(func: Any) -> Dict[str, Any]:
        """Extract JSON schema-like parameters from a callable using inspect."""
        try:
            sig = inspect.signature(func)
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for param_name, param in sig.parameters.items():
                if param_name in ("self", "cls"):
                    continue

                prop: Dict[str, Any] = {}

                # Try to map annotation to JSON schema type
                if param.annotation is not inspect.Parameter.empty:
                    ann = param.annotation
                    if ann is str or ann == "str":
                        prop["type"] = "string"
                    elif ann is int or ann == "int":
                        prop["type"] = "integer"
                    elif ann is float or ann == "float":
                        prop["type"] = "number"
                    elif ann is bool or ann == "bool":
                        prop["type"] = "boolean"
                    elif ann is list or ann == "list":
                        prop["type"] = "array"
                    elif ann is dict or ann == "dict":
                        prop["type"] = "object"
                    else:
                        prop["type"] = "string"
                        prop["annotation"] = str(ann)
                else:
                    prop["type"] = "string"

                if param.default is not inspect.Parameter.empty:
                    prop["default"] = (
                        param.default if _maybe_jsonable(param.default) == param.default else str(param.default)
                    )
                else:
                    required.append(param_name)

                properties[param_name] = prop

            return {"type": "object", "properties": properties, "required": required}
        except (ValueError, TypeError):
            return {"type": "object", "properties": {}, "required": []}

    def _get_components(component_type: Optional[RegistryContentType] = None) -> List[RegistryContentResponse]:
        components: List[RegistryContentResponse] = []

        # Tools
        if component_type is None or component_type == "tool":
            for tool in getattr(registry, "tools", []) or []:
                if isinstance(tool, Toolkit):
                    toolkit_name = _safe_name(tool, fallback=tool.__class__.__name__)
                    functions = getattr(tool, "functions", {}) or {}

                    # Build full function details for each function in the toolkit
                    function_details: List[Dict[str, Any]] = []
                    for func in functions.values():
                        func_name = _safe_name(func, fallback=func.__class__.__name__)
                        # Check if function requires confirmation or external execution
                        requires_confirmation = getattr(func, "requires_confirmation", None)
                        external_execution = getattr(func, "external_execution", None)

                        # If not set on function, check toolkit settings
                        if requires_confirmation is None and hasattr(tool, "requires_confirmation_tools"):
                            requires_confirmation = func_name in (tool.requires_confirmation_tools or [])
                        if external_execution is None and hasattr(tool, "external_execution_required_tools"):
                            external_execution = func_name in (tool.external_execution_required_tools or [])

                        # Get parameters - ensure they're processed if needed
                        func_params = func.parameters
                        default_params = {"type": "object", "properties": {}, "required": []}
                        if func_params == default_params and func.entrypoint and not func.skip_entrypoint_processing:
                            try:
                                func_copy = func.model_copy(deep=False)
                                func_copy.process_entrypoint(strict=False)
                                func_params = func_copy.parameters
                            except Exception:
                                pass

                        func_detail: Dict[str, Any] = {
                            "name": func_name,
                            "description": _safe_str(getattr(func, "description", None)),
                            "class_path": _class_path(func),
                            "has_entrypoint": bool(getattr(func, "entrypoint", None)),
                            "parameters": _maybe_jsonable(func_params),
                            "requires_confirmation": requires_confirmation,
                            "external_execution": external_execution,
                        }

                        # Add callable metadata from entrypoint if available
                        if func.entrypoint:
                            ep = func.entrypoint
                            func_detail["module"] = getattr(ep, "__module__", None)
                            func_detail["qualname"] = getattr(ep, "__qualname__", None)
                            try:
                                sig = inspect.signature(ep)
                                func_detail["signature"] = str(sig)
                                if sig.return_annotation is not inspect.Signature.empty:
                                    func_detail["return_annotation"] = str(sig.return_annotation)
                            except (ValueError, TypeError):
                                pass

                        function_details.append(func_detail)

                    components.append(
                        RegistryContentResponse(
                            name=toolkit_name,
                            type="tool",
                            description=_safe_str(getattr(tool, "description", None)),
                            metadata={
                                "class_path": _class_path(tool),
                                "is_toolkit": True,
                                "functions": function_details,
                            },
                        )
                    )

                elif isinstance(tool, Function):
                    func_name = _safe_name(tool, fallback=tool.__class__.__name__)
                    requires_confirmation = getattr(tool, "requires_confirmation", None)
                    external_execution = getattr(tool, "external_execution", None)

                    # Get parameters - ensure they're processed if needed
                    func_params = tool.parameters
                    # If parameters are empty/default and function has entrypoint, try to process it
                    default_params = {"type": "object", "properties": {}, "required": []}
                    if func_params == default_params and tool.entrypoint and not tool.skip_entrypoint_processing:
                        try:
                            # Create a copy to avoid modifying the original
                            tool_copy = tool.model_copy(deep=False)
                            tool_copy.process_entrypoint(strict=False)
                            func_params = tool_copy.parameters
                        except Exception:
                            # If processing fails, use original parameters
                            pass

                    func_tool_meta: Dict[str, Any] = {
                        "class_path": _class_path(tool),
                        "has_entrypoint": bool(getattr(tool, "entrypoint", None)),
                        "parameters": _maybe_jsonable(func_params),
                        "requires_confirmation": requires_confirmation,
                        "external_execution": external_execution,
                    }

                    # Add callable metadata from entrypoint if available
                    if tool.entrypoint:
                        ep = tool.entrypoint
                        func_tool_meta["module"] = getattr(ep, "__module__", None)
                        func_tool_meta["qualname"] = getattr(ep, "__qualname__", None)
                        try:
                            sig = inspect.signature(ep)
                            func_tool_meta["signature"] = str(sig)
                            if sig.return_annotation is not inspect.Signature.empty:
                                func_tool_meta["return_annotation"] = str(sig.return_annotation)
                        except (ValueError, TypeError):
                            pass

                    components.append(
                        RegistryContentResponse(
                            name=func_name,
                            type="tool",
                            description=_safe_str(getattr(tool, "description", None)),
                            metadata=func_tool_meta,
                        )
                    )

                elif callable(tool):
                    call_name = getattr(tool, "__name__", None) or tool.__class__.__name__
                    tool_module = getattr(tool, "__module__", "unknown")
                    tool_meta: Dict[str, Any] = {
                        "class_path": f"{tool_module}.{call_name}",
                        "module": tool_module,
                        "qualname": getattr(tool, "__qualname__", None),
                        "has_entrypoint": True,
                        "parameters": _get_callable_params(tool),
                        "requires_confirmation": None,
                        "external_execution": None,
                    }

                    # Add signature for display (parity with functions)
                    try:
                        sig = inspect.signature(tool)
                        tool_meta["signature"] = str(sig)
                        if sig.return_annotation is not inspect.Signature.empty:
                            tool_meta["return_annotation"] = str(sig.return_annotation)
                    except (ValueError, TypeError):
                        pass

                    components.append(
                        RegistryContentResponse(
                            name=str(call_name),
                            type="tool",
                            description=_safe_str(getattr(tool, "__doc__", None)),
                            metadata=tool_meta,
                        )
                    )

        # Models
        if component_type is None or component_type == "model":
            for model in getattr(registry, "models", []) or []:
                model_name = (
                    _safe_str(getattr(model, "id", None))
                    or _safe_str(getattr(model, "name", None))
                    or model.__class__.__name__
                )
                components.append(
                    RegistryContentResponse(
                        name=model_name,
                        type="model",
                        description=_safe_str(getattr(model, "description", None)),
                        metadata={
                            "class_path": _class_path(model),
                            "provider": _safe_str(getattr(model, "provider", None)),
                            "model_id": _safe_str(getattr(model, "id", None)),
                            "supports_tools": getattr(model, "supports_tools", None),
                            "supports_structured_outputs": getattr(model, "supports_structured_outputs", None),
                        },
                    )
                )

        # Databases
        if component_type is None or component_type == "db":
            for db in getattr(registry, "dbs", []) or []:
                db_name = (
                    _safe_str(getattr(db, "name", None))
                    or _safe_str(getattr(db, "id", None))
                    or _safe_str(getattr(db, "table_name", None))
                    or db.__class__.__name__
                )
                components.append(
                    RegistryContentResponse(
                        name=db_name,
                        type="db",
                        description=_safe_str(getattr(db, "description", None)),
                        metadata={
                            "class_path": _class_path(db),
                            "db_id": _safe_str(getattr(db, "id", None)),
                            "table_name": _safe_str(getattr(db, "table_name", None)),
                        },
                    )
                )

        # Vector databases
        if component_type is None or component_type == "vector_db":
            for vdb in getattr(registry, "vector_dbs", []) or []:
                vdb_name = (
                    _safe_str(getattr(vdb, "name", None))
                    or _safe_str(getattr(vdb, "id", None))
                    or _safe_str(getattr(vdb, "collection", None))
                    or _safe_str(getattr(vdb, "table_name", None))
                    or vdb.__class__.__name__
                )
                components.append(
                    RegistryContentResponse(
                        name=vdb_name,
                        type="vector_db",
                        description=_safe_str(getattr(vdb, "description", None)),
                        metadata={
                            "class_path": _class_path(vdb),
                            "vector_db_id": _safe_str(getattr(vdb, "id", None)),
                            "collection": _safe_str(getattr(vdb, "collection", None)),
                            "table_name": _safe_str(getattr(vdb, "table_name", None)),
                        },
                    )
                )

        # Schemas
        if component_type is None or component_type == "schema":
            for schema in getattr(registry, "schemas", []) or []:
                schema_name = schema.__name__
                meta: Dict[str, Any] = {"class_path": _class_path(schema)}
                try:
                    meta["schema"] = schema.model_json_schema() if hasattr(schema, "model_json_schema") else {}
                except Exception as e:
                    meta["schema_error"] = str(e)

                components.append(
                    RegistryContentResponse(
                        name=schema_name,
                        type="schema",
                        metadata=meta,
                    )
                )

        # Functions (raw callables used for workflow conditions, selectors, etc.)
        if component_type is None or component_type == "function":
            for func in getattr(registry, "functions", []) or []:
                func_name = getattr(func, "__name__", None) or "anonymous"
                func_module = getattr(func, "__module__", "unknown")
                func_meta: Dict[str, Any] = {
                    "class_path": f"{func_module}.{func_name}",
                    "module": func_module,
                    "qualname": getattr(func, "__qualname__", None),
                    "has_entrypoint": True,
                    "parameters": _get_callable_params(func),
                    "requires_confirmation": None,
                    "external_execution": None,
                }

                # Also add signature string for display
                try:
                    sig = inspect.signature(func)
                    func_meta["signature"] = str(sig)
                    if sig.return_annotation is not inspect.Signature.empty:
                        func_meta["return_annotation"] = str(sig.return_annotation)
                except (ValueError, TypeError):
                    pass

                components.append(
                    RegistryContentResponse(
                        name=func_name,
                        type="function",
                        description=_safe_str(getattr(func, "__doc__", None)),
                        metadata=func_meta,
                    )
                )

        # Stable ordering helps pagination
        components.sort(key=lambda c: (c.type, c.name))
        return components

    @router.get(
        "/registry",
        response_model=PaginatedResponse[RegistryContentResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_registry",
        summary="List Registry",
        description="List all components in the registry with optional filtering.",
    )
    async def list_registry(
        component_type: Optional[RegistryContentType] = Query(None, description="Filter by component type"),
        name: Optional[str] = Query(None, description="Filter by name (partial match)"),
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
    ) -> PaginatedResponse[RegistryContentResponse]:
        try:
            start_time_ms = time.time() * 1000
            components = _get_components(component_type)

            if name:
                needle = name.lower().strip()
                components = [c for c in components if needle in c.name.lower()]

            total_count = len(components)
            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0
            start_idx = (page - 1) * limit
            paginated = components[start_idx : start_idx + limit]

            return PaginatedResponse(
                data=paginated,
                meta=PaginationInfo(
                    page=page,
                    limit=limit,
                    total_pages=total_pages,
                    total_count=total_count,
                    search_time_ms=round(time.time() * 1000 - start_time_ms, 2),
                ),
            )
        except Exception as e:
            log_error(f"Error listing components: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
