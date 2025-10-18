"""
Unified storage resources for multi-cloud deployments.

Provides consistent interface for managing object storage (S3-compatible)
and block storage (volumes) across AWS, GCP, Azure, DigitalOcean, and 60+ other providers.
"""

from agno.unified.resource.storage.object_storage import UnifiedBucket, UnifiedObject
from agno.unified.resource.storage.volume import UnifiedVolume

__all__ = ["UnifiedBucket", "UnifiedObject", "UnifiedVolume"]
