from typing import Optional

from pydantic import BaseModel


class ContainerContext(BaseModel):
    """ContainerContext is a context object passed when creating containers."""

    # OS name
    os_name: str
    # Path to the OS directory inside the container
    os_root: str
    # Path to the OS parent directory inside the container
    os_parent: str
    # Path to the requirements.txt file relative to the os_root
    requirements_file: Optional[str] = None
