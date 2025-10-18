"""
Unified multi-cloud infrastructure management using Apache Libcloud.

This module provides a consistent interface for managing resources across
60+ cloud providers including AWS, GCP, Azure, DigitalOcean, and more.

Example:
    from agno.unified.resource.compute import UnifiedInstance

    # Create VM on any provider with same interface
    vm = UnifiedInstance(
        name="my-vm",
        provider="gcp",  # or "aws", "azure", "digitalocean", etc.
        size="medium",
        image="ubuntu-22.04"
    )
    vm.create()
"""

from agno.base.unified import UnifiedResource
from agno.unified.resources import UnifiedResources

__all__ = ["UnifiedResource", "UnifiedResources"]
