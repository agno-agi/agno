from typing import Any, Dict, Optional

from pydantic import BaseModel


class UserSchema(BaseModel):
    """Schema for user data returned by the API."""

    id_user: str
    email: Optional[str] = None
    username: Optional[str] = None
    name: Optional[str] = None
    email_verified: Optional[bool] = False
    is_active: Optional[bool] = True
    is_machine: Optional[bool] = False
    user_data: Optional[Dict[str, Any]] = None


class EmailPasswordAuthSchema(BaseModel):
    email: str
    password: str
    auth_source: str = "cli"
