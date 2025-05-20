import json
from datetime import datetime
from hashlib import md5
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, model_validator


class MemoryRow(BaseModel):
    """Memory Row that is stored in the database"""

    memory: Dict[str, Any]
    user_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # id for this memory, auto-generated from the memory
    id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    def serializable_dict(self) -> Dict[str, Any]:
        _dict = self.model_dump(exclude={"created_at", "updated_at"})
        _dict["created_at"] = self.created_at.isoformat() if self.created_at else None
        _dict["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        return _dict

    def to_dict(self) -> Dict[str, Any]:
        return self.serializable_dict()

    @model_validator(mode="after")
    def generate_id(self) -> "MemoryRow":
        if self.id is None:
            memory_str = json.dumps(self.memory, sort_keys=True)
            cleaned_memory = memory_str.replace(" ", "").replace("\n", "").replace("\t", "")
            self.id = md5(cleaned_memory.encode()).hexdigest()
        return self
