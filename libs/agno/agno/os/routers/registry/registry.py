import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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


class ComponentResponse(BaseModel):
    name: str
    component_type: ComponentType
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


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

        # Tools
        for tool in getattr(registry, "tools", []) or []:
            if isinstance(tool, Toolkit):
                toolkit_name = _safe_name(tool, fallback=tool.__class__.__name__)
                functions = getattr(tool, "functions", {}) or {}

                components.append(
                    ComponentResponse(
                        name=toolkit_name,
                        component_type="toolkit",
                        description=_safe_str(getattr(tool, "description", None)),
                        metadata={
                            "class_path": _class_path(tool),
                            "functions": sorted(list(functions.keys())),
                        },
                    )
                )

                # Also expose individual functions within toolkit
                for func in functions.values():
                    func_name = _safe_name(func, fallback=getattr(func, "name", None) or func.__class__.__name__)
                    components.append(
                        ComponentResponse(
                            name=func_name,
                            component_type="tool",
                            description=_safe_str(getattr(func, "description", None)),
                            metadata={
                                "class_path": _class_path(func),
                                "toolkit": toolkit_name,
                                "parameters": _maybe_jsonable(getattr(func, "parameters", None)),
                                "has_entrypoint": bool(getattr(func, "entrypoint", None)),
                            },
                        )
                    )

            elif isinstance(tool, Function):
                func_name = _safe_name(tool, fallback=getattr(tool, "name", None) or tool.__class__.__name__)
                components.append(
                    ComponentResponse(
                        name=func_name,
                        component_type="tool",
                        description=_safe_str(getattr(tool, "description", None)),
                        metadata={
                            "class_path": _class_path(tool),
                            "parameters": _maybe_jsonable(getattr(tool, "parameters", None)),
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
        for schema_name, schema in (getattr(registry, "schemas", {}) or {}).items():
            meta: Dict[str, Any] = {"class_path": _class_path(schema)}
            if include_schema:
                try:
                    meta["schema"] = schema.model_json_schema() if hasattr(schema, "model_json_schema") else {}
                except Exception as e:
                    meta["schema_error"] = str(e)

            components.append(
                ComponentResponse(
                    name=str(schema_name),
                    component_type="schema",
                    metadata=meta,
                )
            )

        # Stable ordering helps pagination
        components.sort(key=lambda c: (c.component_type, c.name))
        return components

    @router.get(
        "/registry/components",
        response_model=PaginatedResponse[ComponentResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_components",
        summary="List Registry Components",
        description="List all components in the registry with optional filtering.",
    )
    async def list_components(
        request: Request,
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
