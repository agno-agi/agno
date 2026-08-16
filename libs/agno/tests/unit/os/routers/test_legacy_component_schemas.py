"""The legacy component request models must reject unknown fields.

The v2 models all set extra="forbid"; without it on the legacy models, a v2
client talking to a v1-served deployment gets its guard silently dropped
instead of a validation error.
"""

import pytest
from pydantic import ValidationError

from agno.os.routers.components.legacy import (
    LegacyComponentCreate,
    LegacyComponentUpdate,
    LegacyConfigCreate,
    LegacyConfigUpdate,
)

VALID_PAYLOADS = [
    (LegacyComponentCreate, {"name": "a1", "component_type": "agent"}),
    (LegacyComponentUpdate, {"name": "a1"}),
    (LegacyConfigCreate, {"config": {"name": "a1"}}),
    (LegacyConfigUpdate, {"config": {"name": "a1"}}),
]


@pytest.mark.parametrize("model,payload", VALID_PAYLOADS)
def test_legacy_models_reject_unknown_fields(model, payload):
    model(**payload)
    with pytest.raises(ValidationError):
        model(**payload, unexpected_field=1)


def test_legacy_update_rejects_v2_guard_instead_of_dropping_it():
    with pytest.raises(ValidationError):
        LegacyComponentUpdate(name="a1", guard={"latest_version": 1, "current_version": 1})
