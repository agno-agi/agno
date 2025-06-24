"""Logic and classes shared across managers"""

from enum import Enum
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class PaginationInfo(BaseModel):
    page: Optional[int] = 0
    limit: Optional[int] = 20
    total_pages: Optional[int] = 0
    total_count: Optional[int] = 0


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper to add pagination info to classes used as response models"""

    data: List[T]
    meta: PaginationInfo
