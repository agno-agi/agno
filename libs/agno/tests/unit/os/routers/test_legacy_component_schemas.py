"""The legacy component request models keep the pre-2.9 tolerance contract.

The legacy router exists to accept exact pre-2.9 call shapes, and the old
API silently ignored unknown fields — so these models deliberately stay at
pydantic's default extra behavior. The cost, accepted knowingly: a v2
client's guard is dropped rather than rejected on the body-parsing routes.
"""

import pytest

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
def test_legacy_models_tolerate_unknown_fields(model, payload):
    parsed = model(**payload, unexpected_field=1)
    assert "unexpected_field" not in parsed.model_dump(exclude_unset=True)


def test_legacy_update_drops_a_v2_guard_silently():
    parsed = LegacyComponentUpdate(name="a1", guard={"latest_version": 1, "current_version": 1})
    assert not hasattr(parsed, "guard")
    assert "guard" not in parsed.model_dump(exclude_unset=True)
