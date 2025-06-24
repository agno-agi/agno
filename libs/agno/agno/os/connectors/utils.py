"""Logic and classes shared across managers"""

from enum import Enum


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"
