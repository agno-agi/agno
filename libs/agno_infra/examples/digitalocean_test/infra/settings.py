"""
Infrastructure settings for DigitalOcean test project.

This file configures the infrastructure project for testing
unified multi-cloud resources with DigitalOcean.
"""

from pathlib import Path

from agno.infra.settings import InfraSettings

# Get the current directory (infra directory)
infra_dir = Path(__file__).parent.resolve()
# Get the project root (one level up from infra)
infra_root = infra_dir.parent

# Infrastructure settings
infra_settings = InfraSettings(
    # Project name
    infra_name="digitalocean-test",

    # Project root directory
    infra_root=infra_root,

    # Default environment (dev, staging, prod)
    default_env="dev",

    # Default infrastructure type
    default_infra="unified",
)
