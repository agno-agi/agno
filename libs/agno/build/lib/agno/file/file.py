from dataclasses import dataclass
from typing import Any, List, Optional

from agno.utils.common import dataclass_to_dict


@dataclass
class File:
    name: Optional[str] = None
    description: Optional[str] = None
    columns: Optional[List[str]] = None
    path: Optional[str] = None
    type: str = "FILE"

    def get_metadata(self) -> dict[str, Any]:
        return dataclass_to_dict(self, exclude_none=True)
