from enum import Enum


class ApprovalType(str, Enum):
    """Approval types for the @approval decorator.

    required: Blocking approval. The run cannot continue until the approval
              is resolved via the approvals API.
    audit:    Non-blocking audit trail. An approval record is created after
              the HITL interaction resolves, for compliance/logging purposes.
    """

    required = "required"
    audit = "audit"
