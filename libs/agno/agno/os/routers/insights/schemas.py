from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ModelUsage(BaseModel):
    """The runs one model served across the window"""

    model_id: str = Field(..., description="Identifier of the model")
    model_provider: Optional[str] = Field(None, description="Provider serving the model")
    run_count: int = Field(..., description="Runs the model served in the window", ge=0)
    run_share: float = Field(..., description="Percentage of the window's runs the model served", ge=0)


class MetricsInsightsResponse(BaseModel):
    models: List[ModelUsage] = Field(..., description="Per-model usage, most-run first")
    total_runs: int = Field(..., description="Runs in the window that recorded a model", ge=0)
    window_days: int = Field(..., description="Number of days the insights cover", ge=1)
    computed_at: datetime = Field(..., description="When these insights were computed")
