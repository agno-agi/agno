import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.registry import Registry
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_error

ComponentType = Literal["tool", "toolkit", "model", "db", "vector_db", "schema"]


# ============================================
# Response Schema
# ============================================


class FunctionDetailResponse(BaseModel):
    """Detailed information about a function within a toolkit."""

    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    requires_confirmation: Optional[bool] = None
    external_execution: Optional[bool] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ComponentResponse(BaseModel):
    name: str
    component_type: ComponentType
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Tool-specific fields (matching config format)
    parameters: Optional[Dict[str, Any]] = None
    requires_confirmation: Optional[bool] = None
    external_execution: Optional[bool] = None
    # Toolkit-specific field: detailed function information as key-value pairs
    # Key is the function name, value is the function details
    functions_details: Optional[Dict[str, FunctionDetailResponse]] = None


# ============================================
# Router
# ============================================


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
        # Best-effort: keep only data that is likely JSON serializable
        # If your Function.parameters is a Pydantic model or custom object, this avoids 500s.
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

    def _get_all_components(include_schema: bool) -> List[ComponentResponse]:
        components: List[ComponentResponse] = []

        # Helper function to extract function details
        def _get_function_details(
            func: Function, toolkit_name: str, toolkit: Optional[Toolkit] = None
        ) -> FunctionDetailResponse:
            func_name = _safe_name(func, fallback=func.__class__.__name__)
            # Check if function requires confirmation or external execution
            # First check function-level settings, then toolkit-level settings
            requires_confirmation = getattr(func, "requires_confirmation", None)
            external_execution = getattr(func, "external_execution", None)

            # If not set on function, check toolkit settings
            if toolkit is not None:
                if requires_confirmation is None and hasattr(toolkit, "requires_confirmation_tools"):
                    requires_confirmation = func_name in (toolkit.requires_confirmation_tools or [])
                if external_execution is None and hasattr(toolkit, "external_execution_required_tools"):
                    external_execution = func_name in (toolkit.external_execution_required_tools or [])

            # Get parameters - ensure they're processed if needed
            func_params = func.parameters
            # If parameters are empty/default and function has entrypoint, try to process it
            default_params = {"type": "object", "properties": {}, "required": []}
            if func_params == default_params and func.entrypoint and not func.skip_entrypoint_processing:
                try:
                    # Create a copy to avoid modifying the original
                    func_copy = func.model_copy(deep=False)
                    func_copy.process_entrypoint(strict=False)
                    func_params = func_copy.parameters
                except Exception:
                    # If processing fails, use original parameters
                    pass

            return FunctionDetailResponse(
                name=func_name,
                description=_safe_str(getattr(func, "description", None)),
                parameters=_maybe_jsonable(func_params),
                requires_confirmation=requires_confirmation,
                external_execution=external_execution,
                metadata={
                    "class_path": _class_path(func),
                    "toolkit": toolkit_name,
                    "has_entrypoint": bool(getattr(func, "entrypoint", None)),
                },
            )

        # Tools
        for tool in getattr(registry, "tools", []) or []:
            if isinstance(tool, Toolkit):
                toolkit_name = _safe_name(tool, fallback=tool.__class__.__name__)
                functions = getattr(tool, "functions", {}) or {}

                # Build detailed function information for the toolkit as a dictionary
                functions_details: Dict[str, FunctionDetailResponse] = {}
                for func in functions.values():
                    func_detail = _get_function_details(func, toolkit_name, toolkit=tool)
                    functions_details[func_detail.name] = func_detail

                components.append(
                    ComponentResponse(
                        name=toolkit_name,
                        component_type="toolkit",
                        description=_safe_str(getattr(tool, "description", None)),
                        metadata={
                            "class_path": _class_path(tool),
                            "functions": sorted(list(functions.keys())),
                        },
                        functions_details=functions_details,
                    )
                )

                # Also expose individual functions within toolkit as separate tool components
                for func_detail in functions_details.values():
                    components.append(
                        ComponentResponse(
                            name=func_detail.name,
                            component_type="tool",
                            description=func_detail.description,
                            parameters=func_detail.parameters,
                            requires_confirmation=func_detail.requires_confirmation,
                            external_execution=func_detail.external_execution,
                            metadata=func_detail.metadata,
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

                components.append(
                    ComponentResponse(
                        name=func_name,
                        component_type="tool",
                        description=_safe_str(getattr(tool, "description", None)),
                        parameters=_maybe_jsonable(func_params),
                        requires_confirmation=requires_confirmation,
                        external_execution=external_execution,
                        metadata={
                            "class_path": _class_path(tool),
                            "has_entrypoint": bool(getattr(tool, "entrypoint", None)),
                        },
                    )
                )

            elif callable(tool):
                call_name = getattr(tool, "__name__", None) or tool.__class__.__name__
                components.append(
                    ComponentResponse(
                        name=str(call_name),
                        component_type="tool",
                        description=_safe_str(getattr(tool, "__doc__", None)),
                        metadata={"class_path": _class_path(tool)},
                    )
                )

        # Models
        for model in getattr(registry, "models", []) or []:
            model_name = (
                _safe_str(getattr(model, "id", None))
                or _safe_str(getattr(model, "name", None))
                or model.__class__.__name__
            )
            components.append(
                ComponentResponse(
                    name=model_name,
                    component_type="model",
                    description=_safe_str(getattr(model, "description", None)),
                    metadata={
                        "class_path": _class_path(model),
                        "provider": _safe_str(getattr(model, "provider", None)),
                        "model_id": _safe_str(getattr(model, "id", None)),
                    },
                )
            )

        # Databases
        for db in getattr(registry, "dbs", []) or []:
            db_name = (
                _safe_str(getattr(db, "name", None))
                or _safe_str(getattr(db, "id", None))
                or _safe_str(getattr(db, "table_name", None))
                or db.__class__.__name__
            )
            components.append(
                ComponentResponse(
                    name=db_name,
                    component_type="db",
                    metadata={
                        "class_path": _class_path(db),
                        "db_id": _safe_str(getattr(db, "id", None)),
                        "table_name": _safe_str(getattr(db, "table_name", None)),
                    },
                )
            )

        # Vector databases
        for vdb in getattr(registry, "vector_dbs", []) or []:
            vdb_name = (
                _safe_str(getattr(vdb, "name", None))
                or _safe_str(getattr(vdb, "id", None))
                or _safe_str(getattr(vdb, "collection", None))
                or _safe_str(getattr(vdb, "table_name", None))
                or vdb.__class__.__name__
            )
            components.append(
                ComponentResponse(
                    name=vdb_name,
                    component_type="vector_db",
                    metadata={
                        "class_path": _class_path(vdb),
                        "vector_db_id": _safe_str(getattr(vdb, "id", None)),
                        "collection": _safe_str(getattr(vdb, "collection", None)),
                        "table_name": _safe_str(getattr(vdb, "table_name", None)),
                    },
                )
            )

        # Schemas
        for schema in getattr(registry, "schemas", []) or []:
            schema_name = schema.__name__
            meta: Dict[str, Any] = {"class_path": _class_path(schema)}
            if include_schema:
                try:
                    meta["schema"] = schema.model_json_schema() if hasattr(schema, "model_json_schema") else {}
                except Exception as e:
                    meta["schema_error"] = str(e)

            components.append(
                ComponentResponse(
                    name=schema_name,
                    component_type="schema",
                    metadata=meta,
                )
            )

        # Stable ordering helps pagination
        components.sort(key=lambda c: (c.component_type, c.name))
        return components

    @router.get(
        "/registry",
        response_model=PaginatedResponse[ComponentResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_registry",
        summary="List Registry",
        description="List all components in the registry with optional filtering.",
    )
    async def list_registry(
        component_type: Optional[ComponentType] = Query(None, description="Filter by component type"),
        name: Optional[str] = Query(None, description="Filter by name (partial match)"),
        include_schema: bool = Query(False, description="Include JSON schema for schema components"),
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
    ) -> PaginatedResponse[ComponentResponse]:
        try:
            start_time_ms = time.time() * 1000
            components = _get_all_components(include_schema=include_schema)

            if component_type:
                components = [c for c in components if c.component_type == component_type]

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
