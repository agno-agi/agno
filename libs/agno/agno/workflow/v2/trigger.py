from dataclasses import dataclass
from enum import Enum


class TriggerType(str, Enum):
    """Types of workflow triggers"""

    MANUAL = "manual"
    AGENTIC = "agentic"
    SCHEDULED = "scheduled"


@dataclass
class Trigger:
    """Base class for workflow triggers - minimal implementation"""

    @property
    def trigger_type(self) -> TriggerType:
        """Return the type of this trigger"""
        raise NotImplementedError


@dataclass
class ManualTrigger(Trigger):
    """Manual trigger - workflow is executed on demand"""

    @property
    def trigger_type(self) -> TriggerType:
        return TriggerType.MANUAL
