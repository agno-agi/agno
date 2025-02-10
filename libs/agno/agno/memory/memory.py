from typing import Any, Dict, Optional

from pydantic import BaseModel


class Memory(BaseModel):
    """Model for Agent Memories"""

    memory: str
    id: Optional[str] = None
    topic: Optional[str] = None
    input: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)
