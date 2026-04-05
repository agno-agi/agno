from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunInput
from agno.utils.hooks import normalize_pre_hooks


class _StubGuardrail(BaseGuardrail):
    name: str = "stub"

    def check(self, run_input: RunInput) -> None:
        pass

    async def async_check(self, run_input: RunInput) -> None:
        pass


def test_pre_hooks_normalised_on_first_run():
    guardrail = _StubGuardrail()
    hooks = normalize_pre_hooks([guardrail], async_mode=True)
    assert hooks is not None
    assert hooks[0] == guardrail.async_check


def test_pre_hooks_normalised_after_reassignment():
    # Re-normalising with a new guardrail instance must return its bound method
    guardrail = _StubGuardrail()
    hooks = normalize_pre_hooks([guardrail], async_mode=True)
    assert hooks is not None
    assert hooks[0] == guardrail.async_check

    guardrail2 = _StubGuardrail()
    hooks2 = normalize_pre_hooks([guardrail2], async_mode=True)
    assert hooks2 is not None
    assert hooks2[0] == guardrail2.async_check
