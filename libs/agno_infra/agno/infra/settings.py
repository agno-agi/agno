from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class InfraSettings:
    """Settings that can be used by any resource in the infrastructure."""

    # Infrastructure name
    infra_name: str

    # Path to the infrastructure root
    infra_root: Path

    # infrastructure git repo url
    infra_repo: Optional[str] = None

    # default env for agno infra commands
    default_env: Optional[str] = "dev"

    # default infra for agno infra commands
    default_infra: Optional[str] = None

    # Image Settings
    # Repository for images
    image_repo: str = "agnohq"
    # 'name:tag' for the image
    image_name: Optional[str] = None
    # If True, build images locally
    build_images: bool = False
    # If True, push images after building
    push_images: bool = False
    # If True, skip cache when building images
    skip_image_cache: bool = False
    # If True, force pull images in FROM
    force_pull_images: bool = False

    # Test Settings
    test_env: str = "test"
    test_key: Optional[str] = None

    # Development Settings
    dev_env: str = "dev"
    dev_key: Optional[str] = None

    # Staging Settings
    stg_env: str = "stg"
    stg_key: Optional[str] = None

    # Production Settings
    prd_env: str = "prd"
    prd_key: Optional[str] = None

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
    # Other Settings
    # Use cached resource if available, i.e. skip resource creation if the resource already exists
    use_cache: bool = True

    ## AWS ##
    # AWS Region and Profile
    aws_region: Optional[str] = None
    aws_profile: Optional[str] = None

    # AWS Subnet Configuration
    aws_subnet_ids: List[str] = field(default_factory=list)
    # Public subnets. Will be added to aws_subnet_ids if provided and aws_subnet_ids is empty.
    # Note: not added to aws_subnet_ids if aws_subnet_ids is provided.
    aws_public_subnets: List[str] = field(default_factory=list)
    # Private subnets. Will be added to aws_subnet_ids if provided and aws_subnet_ids is empty.
    # Note: not added to aws_subnet_ids if aws_subnet_ids is provided.
    aws_private_subnets: List[str] = field(default_factory=list)

    # AWS Availability Zones
    aws_az1: Optional[str] = None
    aws_az2: Optional[str] = None
    aws_az3: Optional[str] = None
    aws_az4: Optional[str] = None
    aws_az5: Optional[str] = None

    # AWS Security Groups
    aws_security_group_ids: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate and set computed fields after initialization."""
        self._validate_and_set_keys()
        self._validate_and_set_subnet_ids()

    def _validate_and_set_keys(self):
        """Validate and set environment keys if not provided."""
        if self.test_key is None:
            if self.infra_name is None:
                raise ValueError("`infra_name` is None: Please set a valid value")
            if self.test_env is None:
                raise ValueError("`test_env` is None: Please set a valid value")
            self.test_key = f"{self.infra_name}-{self.test_env}"

        if self.dev_key is None:
            if self.infra_name is None:
                raise ValueError("`infra_name` is None: Please set a valid value")
            if self.dev_env is None:
                raise ValueError("`dev_env` is None: Please set a valid value")
            self.dev_key = f"{self.infra_name}-{self.dev_env}"

        if self.stg_key is None:
            if self.infra_name is None:
                raise ValueError("`infra_name` is None: Please set a valid value")
            if self.stg_env is None:
                raise ValueError("`stg_env` is None: Please set a valid value")
            self.stg_key = f"{self.infra_name}-{self.stg_env}"

        if self.prd_key is None:
            if self.infra_name is None:
                raise ValueError("`infra_name` is None: Please set a valid value")
            if self.prd_env is None:
                raise ValueError("`prd_env` is None: Please set a valid value")
            self.prd_key = f"{self.infra_name}-{self.prd_env}"

    def _validate_and_set_subnet_ids(self):
        """Set subnet IDs from public and private subnets if not provided."""
        if not self.aws_subnet_ids:
            self.aws_subnet_ids = self.aws_public_subnets + self.aws_private_subnets
