import inspect
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    BadRequestResponse,
    CallableMetadata,
    DbMetadata,
    FunctionMetadata,
    InternalServerErrorResponse,
    ModelMetadata,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    RegistryContentResponse,
    RegistryResourceType,
    SchemaMetadata,
    ToolMetadata,
    UnauthenticatedResponse,
    ValidationErrorResponse,
    VectorDbMetadata,
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

    def _extract_entrypoint_metadata(
        entrypoint: Any,
    ) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Extract module, qualname, signature, and return annotation from an entrypoint callable."""
        ep_module: Optional[str] = getattr(entrypoint, "__module__", None)
        ep_qualname: Optional[str] = getattr(entrypoint, "__qualname__", None)
        ep_signature: Optional[str] = None
        ep_return_annotation: Optional[str] = None
        try:
            sig = inspect.signature(entrypoint)
            ep_signature = str(sig)
            if sig.return_annotation is not inspect.Signature.empty:
                ep_return_annotation = str(sig.return_annotation)
        except (ValueError, TypeError):
            pass
        return ep_module, ep_qualname, ep_signature, ep_return_annotation

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

    def _get_resources(resource_type: Optional[RegistryResourceType] = None) -> List[RegistryContentResponse]:
        resources: List[RegistryContentResponse] = []

        # Tools
        if resource_type is None or resource_type == RegistryResourceType.TOOL:
            for tool in getattr(registry, "tools", []) or []:
                if isinstance(tool, Toolkit):
                    toolkit_name = _safe_name(tool, fallback=tool.__class__.__name__)
                    functions = getattr(tool, "functions", {}) or {}

                    # Build full function details for each function in the toolkit
                    function_details: List[CallableMetadata] = []
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

                        # Extract callable metadata from entrypoint
                        func_module: Optional[str] = None
                        func_qualname: Optional[str] = None
                        func_signature: Optional[str] = None
                        func_return_annotation: Optional[str] = None
                        if func.entrypoint:
                            func_module, func_qualname, func_signature, func_return_annotation = (
                                _extract_entrypoint_metadata(func.entrypoint)
                            )

                        func_description = getattr(func, "description", None)
                        if func_description is None and func.entrypoint:
                            func_description = inspect.getdoc(func.entrypoint)

                        function_details.append(
                            CallableMetadata(
                                name=func_name,
                                description=_safe_str(func_description),
                                class_path=_class_path(func),
                                module=func_module,
                                qualname=func_qualname,
                                has_entrypoint=bool(getattr(func, "entrypoint", None)),
                                parameters=_maybe_jsonable(func_params),
                                requires_confirmation=requires_confirmation,
                                external_execution=external_execution,
                                signature=func_signature,
                                return_annotation=func_return_annotation,
                            )
                        )

                    toolkit_metadata = ToolMetadata(
                        class_path=_class_path(tool),
                        is_toolkit=True,
                        functions=function_details,
                    )
                    resources.append(
                        RegistryContentResponse(
                            name=toolkit_name,
                            type=RegistryResourceType.TOOL,
                            description=_safe_str(getattr(tool, "description", None)),
                            metadata=toolkit_metadata.model_dump(exclude_none=True),
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

                    # Extract callable metadata from entrypoint
                    tool_module: Optional[str] = None
                    tool_qualname: Optional[str] = None
                    tool_signature: Optional[str] = None
                    tool_return_annotation: Optional[str] = None
                    if tool.entrypoint:
                        tool_module, tool_qualname, tool_signature, tool_return_annotation = (
                            _extract_entrypoint_metadata(tool.entrypoint)
                        )

                    func_tool_metadata = ToolMetadata(
                        class_path=_class_path(tool),
                        module=tool_module,
                        qualname=tool_qualname,
                        has_entrypoint=bool(getattr(tool, "entrypoint", None)),
                        parameters=_maybe_jsonable(func_params),
                        requires_confirmation=requires_confirmation,
                        external_execution=external_execution,
                        signature=tool_signature,
                        return_annotation=tool_return_annotation,
                    )
                    resources.append(
                        RegistryContentResponse(
                            name=func_name,
                            type=RegistryResourceType.TOOL,
                            description=_safe_str(getattr(tool, "description", None)),
                            metadata=func_tool_metadata.model_dump(exclude_none=True),
                        )
                    )

                elif callable(tool):
                    call_name = getattr(tool, "__name__", None) or tool.__class__.__name__
                    tool_module = getattr(tool, "__module__", "unknown")

                    # Extract signature
                    callable_signature: Optional[str] = None
                    callable_return_annotation: Optional[str] = None
                    try:
                        sig = inspect.signature(tool)
                        callable_signature = str(sig)
                        if sig.return_annotation is not inspect.Signature.empty:
                            callable_return_annotation = str(sig.return_annotation)
                    except (ValueError, TypeError):
                        pass

                    callable_metadata = ToolMetadata(
                        class_path=f"{tool_module}.{call_name}",
                        module=tool_module,
                        qualname=getattr(tool, "__qualname__", None),
                        has_entrypoint=True,
                        parameters=_get_callable_params(tool),
                        requires_confirmation=None,
                        external_execution=None,
                        signature=callable_signature,
                        return_annotation=callable_return_annotation,
                    )
                    resources.append(
                        RegistryContentResponse(
                            name=str(call_name),
                            type=RegistryResourceType.TOOL,
                            description=_safe_str(getattr(tool, "__doc__", None)),
                            metadata=callable_metadata.model_dump(exclude_none=True),
                        )
                    )

        # Models
        if resource_type is None or resource_type == RegistryResourceType.MODEL:
            for model in getattr(registry, "models", []) or []:
                model_name = (
                    _safe_str(getattr(model, "id", None))
                    or _safe_str(getattr(model, "name", None))
                    or model.__class__.__name__
                )
                model_metadata = ModelMetadata(
                    class_path=_class_path(model),
                    provider=_safe_str(getattr(model, "provider", None)),
                    model_id=_safe_str(getattr(model, "id", None)),
                )
                resources.append(
                    RegistryContentResponse(
                        name=model_name,
                        type=RegistryResourceType.MODEL,
                        description=_safe_str(getattr(model, "description", None)),
                        metadata=model_metadata.model_dump(exclude_none=True),
                    )
                )

        # Databases
        if resource_type is None or resource_type == RegistryResourceType.DB:
            for db in getattr(registry, "dbs", []) or []:
                db_name = (
                    _safe_str(getattr(db, "name", None)) or _safe_str(getattr(db, "id", None)) or db.__class__.__name__
                )
                db_metadata = DbMetadata(
                    class_path=_class_path(db),
                    db_id=_safe_str(getattr(db, "id", None)),
                )
                resources.append(
                    RegistryContentResponse(
                        name=db_name,
                        type=RegistryResourceType.DB,
                        description=_safe_str(getattr(db, "description", None)),
                        metadata=db_metadata.model_dump(exclude_none=True),
                    )
                )

        # Vector databases
        if resource_type is None or resource_type == RegistryResourceType.VECTOR_DB:
            for vdb in getattr(registry, "vector_dbs", []) or []:
                vdb_name = (
                    _safe_str(getattr(vdb, "name", None))
                    or _safe_str(getattr(vdb, "id", None))
                    or _safe_str(getattr(vdb, "collection", None))
                    or _safe_str(getattr(vdb, "table_name", None))
                    or vdb.__class__.__name__
                )
                vdb_metadata = VectorDbMetadata(
                    class_path=_class_path(vdb),
                    vector_db_id=_safe_str(getattr(vdb, "id", None)),
                    collection=_safe_str(getattr(vdb, "collection", None)),
                    table_name=_safe_str(getattr(vdb, "table_name", None)),
                )
                resources.append(
                    RegistryContentResponse(
                        name=vdb_name,
                        type=RegistryResourceType.VECTOR_DB,
                        description=_safe_str(getattr(vdb, "description", None)),
                        metadata=vdb_metadata.model_dump(exclude_none=True),
                    )
                )

        # Schemas
        if resource_type is None or resource_type == RegistryResourceType.SCHEMA:
            for schema in getattr(registry, "schemas", []) or []:
                schema_name = schema.__name__
                schema_json: Optional[Dict[str, Any]] = None
                schema_error: Optional[str] = None
                try:
                    schema_json = schema.model_json_schema() if hasattr(schema, "model_json_schema") else {}
                except Exception as e:
                    schema_error = str(e)

                schema_metadata = SchemaMetadata(
                    class_path=_class_path(schema),
                    schema=schema_json,
                    schema_error=schema_error,
                )
                resources.append(
                    RegistryContentResponse(
                        name=schema_name,
                        type=RegistryResourceType.SCHEMA,
                        metadata=schema_metadata.model_dump(exclude_none=True, by_alias=True),
                    )
                )

        # Functions (raw callables used for workflow conditions, selectors, etc.)
        if resource_type is None or resource_type == RegistryResourceType.FUNCTION:
            for func in getattr(registry, "functions", []) or []:
                func_name = getattr(func, "__name__", None) or "anonymous"
                func_module = getattr(func, "__module__", "unknown")

                # Extract signature
                reg_func_signature: Optional[str] = None
                reg_func_return_annotation: Optional[str] = None
                try:
                    sig = inspect.signature(func)
                    reg_func_signature = str(sig)
                    if sig.return_annotation is not inspect.Signature.empty:
                        reg_func_return_annotation = str(sig.return_annotation)
                except (ValueError, TypeError):
                    pass

                func_description = _safe_str(getattr(func, "__doc__", None))
                reg_func_metadata = FunctionMetadata(
                    name=func_name,
                    description=func_description,
                    class_path=f"{func_module}.{func_name}",
                    module=func_module,
                    qualname=getattr(func, "__qualname__", None),
                    has_entrypoint=True,
                    parameters=_get_callable_params(func),
                    requires_confirmation=None,
                    external_execution=None,
                    signature=reg_func_signature,
                    return_annotation=reg_func_return_annotation,
                )
                resources.append(
                    RegistryContentResponse(
                        name=func_name,
                        type=RegistryResourceType.FUNCTION,
                        description=func_description,
                        metadata=reg_func_metadata.model_dump(exclude_none=True),
                    )
                )

        # Stable ordering helps pagination
        resources.sort(key=lambda r: (r.type, r.name))
        return resources

    @router.get(
        "/registry",
        response_model=PaginatedResponse[RegistryContentResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_registry",
        summary="List Registry",
        description="List all resources in the registry with optional filtering.",
    )
    async def list_registry(
        resource_type: Optional[RegistryResourceType] = Query(None, description="Filter by resource type"),
        name: Optional[str] = Query(None, description="Filter by name (partial match)"),
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
    ) -> PaginatedResponse[RegistryContentResponse]:
        try:
            start_time_ms = time.time() * 1000
            resources = _get_resources(resource_type)

            if name:
                needle = name.lower().strip()
                resources = [r for r in resources if needle in r.name.lower()]

            total_count = len(resources)
            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0
            start_idx = (page - 1) * limit
            paginated = resources[start_idx : start_idx + limit]

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
            log_error(f"Error listing registry resources: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
