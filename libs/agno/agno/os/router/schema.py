from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field

from agno.eval.base import BaseEval
from agno.guardrails.base import BaseGuardrail
from agno.hooks.decorator import should_run_in_background


class RunCancelledResponse(BaseModel):
    id: str
    success: bool
    
class ToolDefinitionResponse(BaseModel):
    name: Optional[str] = Field(None, description="Name of the tool")
    description: Optional[str] = Field(None, description="Description of the tool")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Parameters of the tool")
    raw: Optional[Dict[str, Any]] = Field(None, description="Raw tool definition")

class TableNameResponse(BaseModel):
    type: str = Field(..., description="The name of the table")
    name: str = Field(..., description="The name of the table")

class DatabaseConfigResponse(BaseModel):
    id: str = Field(..., description="The ID of the database")
    table_names: List[TableNameResponse] = Field(..., description="The table names of the database")
    config: Dict[str, Any] = Field(..., description="The configuration of the database")

class MessageResponse(BaseModel):
    role: str = Field(..., description="The role of the message")
    content: str = Field(..., description="The content of the message")
    created_at: Optional[datetime] = Field(None, description="The timestamp of the message")


class ModelResponse(BaseModel):
    name: Optional[str] = Field(None, description="Name of the model")
    model: Optional[str] = Field(None, description="Model identifier")
    provider: Optional[str] = Field(None, description="Model provider name")


class HookType(str, Enum):
    """Type of hook"""
    FUNCTION = "function"
    GUARDRAIL = "guardrail"
    EVAL = "eval"


class HookResponse(BaseModel):
    """Response schema for pre/post hooks"""
    name: str = Field(..., description="Name of the hook function or class")
    type: HookType = Field(..., description="Type of the hook (function, guardrail, or eval)")
    run_in_background: bool = Field(False, description="Whether the hook runs in background")

    @classmethod
    def from_hook(cls, hook: Union[Callable[..., Any], BaseGuardrail, BaseEval]) -> "HookResponse":
        """Create a HookResponse from a hook object."""
        if isinstance(hook, BaseGuardrail):
            return cls(
                name=hook.__class__.__name__,
                type=HookType.GUARDRAIL,
                run_in_background=getattr(hook, "run_in_background", False),
            )
        elif isinstance(hook, BaseEval):
            return cls(
                name=hook.__class__.__name__,
                type=HookType.EVAL,
                run_in_background=getattr(hook, "run_in_background", False),
            )
        else:
            # Regular callable function
            return cls(
                name=getattr(hook, "__name__", str(hook)),
                type=HookType.FUNCTION,
                run_in_background=should_run_in_background(hook),
            )

class HealthResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"status": "ok", "instantiated_at": "2025-06-10T12:00:00Z"}}
    )

    status: str = Field(..., description="Health status of the service")
    instantiated_at: datetime = Field(..., description="Timestamp when service was instantiated")



T = TypeVar("T")


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class PaginationInfo(BaseModel):
    page: int = Field(0, description="Current page number (0-indexed)", ge=0)
    limit: int = Field(20, description="Number of items per page", ge=1)
    total_pages: int = Field(0, description="Total number of pages", ge=0)
    total_count: int = Field(0, description="Total count of items", ge=0)
    search_time_ms: float = Field(0, description="Search execution time in milliseconds", ge=0)


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper to add pagination info to classes used as response models"""

    data: List[T] = Field(..., description="List of items for the current page")
    meta: PaginationInfo = Field(..., description="Pagination metadata")


# ERRORS

class BadRequestResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Bad request", "error_code": "BAD_REQUEST"}})

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class NotFoundResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Not found", "error_code": "NOT_FOUND"}})

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class UnauthorizedResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Unauthorized access", "error_code": "UNAUTHORIZED"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class UnauthenticatedResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Unauthenticated access", "error_code": "UNAUTHENTICATED"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class ValidationErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Validation error", "error_code": "VALIDATION_ERROR"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class InternalServerErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Internal server error", "error_code": "INTERNAL_SERVER_ERROR"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")

