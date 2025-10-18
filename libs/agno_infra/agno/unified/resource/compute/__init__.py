"""
Unified compute resources for multi-cloud deployments.

Provides consistent interface for managing virtual machines, instances,
and compute resources across AWS, GCP, Azure, DigitalOcean, and 60+ other providers.
"""

from agno.unified.resource.compute.instance import UnifiedInstance

__all__ = ["UnifiedInstance"]
