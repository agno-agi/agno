from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel


class MemoryRetrieval(str, Enum):
    last_n = "last_n"
    first_n = "first_n"
    semantic = "semantic"


class Memory(BaseModel):
    """Model for Agent Memories"""

    memory: str
    id: Optional[str] = None
    topic: Optional[str] = None
    input: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)
