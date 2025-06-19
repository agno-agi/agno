from typing import Any, Dict, Optional

from pydantic import BaseModel


class AppCreate(BaseModel):
    """Data sent to API to create an App"""

    app_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    config: Dict[str, Any]
