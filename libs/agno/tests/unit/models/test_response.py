"""Tests for ModelResponse and ToolExecution dataclass defaults.

Regression coverage for the boot-time ``created_at`` bug: ``created_at`` used
to be defined as ``int = int(time())`` (a class-level expression evaluated
once at import), so every instance in a process shared the same timestamp.
The fix is to use ``field(default_factory=lambda: int(time()))`` so each
instance is stamped at construction time.
"""

from dataclasses import fields
from time import sleep, time
from unittest.mock import patch

from agno.models.response import ModelResponse, ToolExecution


class TestModelResponseCreatedAt:
    def test_created_at_is_near_construction_time(self):
        before = int(time())
        response = ModelResponse()
        after = int(time())
        assert before <= response.created_at <= after

    def test_two_instances_get_distinct_timestamps(self):
        """Regression: pre-fix, both instances shared the module-import timestamp."""
        first = ModelResponse()
        sleep(1.1)
        second = ModelResponse()
        assert second.created_at > first.created_at
        assert second.created_at - first.created_at >= 1

    def test_uses_default_factory_not_class_level_default(self):
        """Guard against a regression to ``int = int(time())``.

        A class-level int default would be captured on the dataclass field's
        ``default`` attribute; the correct pattern leaves ``default`` as
        MISSING and sets ``default_factory`` instead.
        """
        from dataclasses import MISSING

        created_at_field = next(f for f in fields(ModelResponse) if f.name == "created_at")
        assert created_at_field.default is MISSING, (
            "created_at must not have a class-level default; use default_factory "
            "or every instance will share the module-import timestamp"
        )
        assert created_at_field.default_factory is not MISSING
        # The factory should be callable and return an int at call time.
        assert isinstance(created_at_field.default_factory(), int)

    def test_factory_invoked_per_instance(self):
        """Patch ``time`` in the module and confirm each construction re-reads it."""
        with patch("agno.models.response.time") as mock_time:
            mock_time.side_effect = [1000.0, 2000.0, 3000.0]
            a = ModelResponse()
            b = ModelResponse()
            c = ModelResponse()
        assert a.created_at == 1000
        assert b.created_at == 2000
        assert c.created_at == 3000

    def test_explicit_created_at_is_respected(self):
        response = ModelResponse(created_at=42)
        assert response.created_at == 42

    def test_created_at_survives_to_dict_roundtrip(self):
        response = ModelResponse(created_at=1234567890)
        data = response.to_dict()
        assert data["created_at"] == 1234567890


class TestToolExecutionCreatedAt:
    """ToolExecution already uses default_factory; these guard against regressions."""

    def test_two_instances_get_distinct_timestamps(self):
        first = ToolExecution()
        sleep(1.1)
        second = ToolExecution()
        assert second.created_at - first.created_at >= 1

    def test_factory_invoked_per_instance(self):
        with patch("agno.models.response.time") as mock_time:
            mock_time.side_effect = [5000.0, 6000.0]
            a = ToolExecution()
            b = ToolExecution()
        assert a.created_at == 5000
        assert b.created_at == 6000

    def test_from_dict_preserves_explicit_created_at(self):
        original = ToolExecution(tool_name="foo", created_at=111)
        restored = ToolExecution.from_dict(original.to_dict())
        assert restored.created_at == 111

    def test_from_dict_without_created_at_uses_factory(self):
        """When the payload omits created_at, from_dict falls back to the factory."""
        before = int(time())
        restored = ToolExecution.from_dict({"tool_name": "foo"})
        after = int(time())
        assert before <= restored.created_at <= after
