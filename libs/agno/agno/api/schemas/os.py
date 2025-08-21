from pydantic import BaseModel


class OSLaunch(BaseModel):
    """Data sent to API to create an OS Launch"""

    os_id: str
