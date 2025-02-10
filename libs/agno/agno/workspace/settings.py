from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from agno.api.schemas.workspace import WorkspaceSchema


class WorkspaceSettings(BaseSettings):
    """Workspace settings that can be used by any resource in the workspace."""

    # Workspace name: only used for naming cloud resources
    ws_name: str
    # Path to the workspace root
    ws_root: Path
    # Workspace git repo url
    ws_repo: Optional[str] = None
    # default env for agno ws commands
    default_env: Optional[str] = "dev"
    # default infra for agno ws commands
    default_infra: Optional[str] = None

    # Image Settings
    # Repository for images
    image_repo: str = "agnohq"
    # 'Name:tag' for the image
    image_name: Optional[str] = None
    # Build images locally
    build_images: bool = False
    # Push images after building
    push_images: bool = False
    # Skip cache when building images
    skip_image_cache: bool = False
    # Force pull images in FROM
    force_pull_images: bool = False

    # ag cli settings
    # Set to True if Agno should continue creating
    # resources after a resource creation has failed
    continue_on_create_failure: bool = False
    # Set to True if Agno should continue deleting
    # resources after a resource deleting has failed
    # Defaults to True because we normally want to continue deleting
    continue_on_delete_failure: bool = True
    # Set to True if Agno should continue patching
    # resources after a resource patch has failed
    continue_on_patch_failure: bool = False

    # AWS settings
    # Region for AWS resources
    aws_region: Optional[str] = None
    # Profile for AWS resources
    aws_profile: Optional[str] = None

    # Other Settings
    # Use cached resource if available, i.e. skip resource creation if the resource already exists
    use_cache: bool = True
    # WorkspaceSchema provided by the api
    ws_schema: Optional[WorkspaceSchema] = None

    model_config = SettingsConfigDict(extra="allow")
