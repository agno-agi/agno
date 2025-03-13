from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agno.api.schemas.workspace import WorkspaceSchema


class WorkspaceSettings(BaseSettings):
    """Workspace settings that can be used by any resource in the workspace."""

    # Workspace name
    ws_name: str
    # Path to the workspace root
    ws_root: Path
    # Workspace git repo url
    ws_repo: Optional[str] = None

    # -*- Workspace Environments
    dev_env: str = "dev"
    dev_key: Optional[str] = None
    stg_env: str = "stg"
    stg_key: Optional[str] = None
    prd_env: str = "prd"
    prd_key: Optional[str] = None

    # default env for `agno ws` commands
    default_env: Optional[str] = "dev"
    # default infra for `agno ws` commands
    default_infra: Optional[str] = None

    # -*- Image Settings
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

    # -*- `ag` cli settings
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

    # -*- AWS settings
    # Region for AWS resources
    aws_region: Optional[str] = None
    # Profile for AWS resources
    aws_profile: Optional[str] = None
    # Availability Zones for AWS resources
    aws_az1: Optional[str] = None
    aws_az2: Optional[str] = None
    aws_az3: Optional[str] = None
    # Subnets for AWS resources
    aws_subnet_ids: Optional[List[str]] = None
    # Security Groups for AWS resources
    aws_security_group_ids: Optional[List[str]] = None

    # -*- Other Settings
    # Use cached resource if available, i.e. skip resource creation if the resource already exists
    use_cache: bool = True
    # WorkspaceSchema provided by the api
    ws_schema: Optional[WorkspaceSchema] = None

    model_config = SettingsConfigDict(extra="allow")

    @field_validator("dev_key", mode="before")
    def set_dev_key(cls, dev_key, info: ValidationInfo):
        if dev_key is not None:
            return dev_key

        ws_name = info.data.get("ws_name")
        if ws_name is None:
            raise ValueError("ws_name invalid")

        dev_env = info.data.get("dev_env")
        if dev_env is None:
            raise ValueError("dev_env invalid")

        return f"{ws_name}-{dev_env}"

    @field_validator("stg_key", mode="before")
    def set_stg_key(cls, stg_key, info: ValidationInfo):
        if stg_key is not None:
            return stg_key

        ws_name = info.data.get("ws_name")
        if ws_name is None:
            raise ValueError("ws_name invalid")

        stg_env = info.data.get("stg_env")
        if stg_env is None:
            raise ValueError("stg_env invalid")

        return f"{ws_name}-{stg_env}"

    @field_validator("prd_key", mode="before")
    def set_prd_key(cls, prd_key, info: ValidationInfo):
        if prd_key is not None:
            return prd_key

        ws_name = info.data.get("ws_name")
        if ws_name is None:
            raise ValueError("ws_name invalid")

        prd_env = info.data.get("prd_env")
        if prd_env is None:
            raise ValueError("prd_env invalid")

        return f"{ws_name}-{prd_env}"
