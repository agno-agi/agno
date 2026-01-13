from typing import Optional

from pydantic import BaseModel


class ContainerContext(BaseModel):
    """ContainerContext is a context object passed when creating containers."""

    # Infra name
    infra_name: str
    # Path to the infra directory inside the container
    infra_root: str
    # Path to the infra parent directory inside the container
    infra_parent: str
    # Path to the requirements.txt file relative to the infra_root
    requirements_file: Optional[str] = None
