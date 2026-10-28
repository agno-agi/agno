"""Tests for check_output_review_status in agno/workflow/utils/hitl.py."""

from types import SimpleNamespace

from agno.workflow.utils.hitl import check_output_review_status


def _make_step(predicate):
    return SimpleNamespace(
        name="guarded",
        human_review=SimpleNamespace(requires_output_review=predicate),
        create_output_review_requirement=lambda *args, **kwargs: SimpleNamespace(),
    )


def test_output_review_predicate_exception_fails_closed():
    """A predicate error must pause for review, not silently skip it."""

    def bad_predicate(step_output):
        raise RuntimeError("user predicate bug")

    result = check_output_review_status(
        _make_step(bad_predicate),
        0,
        SimpleNamespace(),
        SimpleNamespace(content="sensitive output"),
    )
    assert result.should_pause is True
    assert result.step_requirement is not None


def test_output_review_predicate_false_does_not_pause():
    result = check_output_review_status(
        _make_step(lambda step_output: False),
        0,
        SimpleNamespace(),
        SimpleNamespace(content="hi"),
    )
    assert result.should_pause is False
    assert result.step_requirement is None
