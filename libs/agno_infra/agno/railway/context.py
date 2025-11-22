"""Railway build context."""

from typing import Optional

from pydantic import BaseModel


class RailwayBuildContext(BaseModel):
    """Context for building Railway resources.

    This context is passed to apps when building their resource graphs,
    providing Railway-specific configuration and state.
    """

    # Workspace/Team ID (required for project creation)
    workspace_id: Optional[str] = None

    # Project and environment IDs (can be set after project/environment creation)
    project_id: Optional[str] = None
    environment_id: Optional[str] = None

    # API authentication
    api_token: Optional[str] = None

    # Default environment name for new projects
    default_environment: str = "production"

    model_config = {"arbitrary_types_allowed": True}
