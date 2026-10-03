from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from agno.os.public._limits import Admission, PublicLimiter
from agno.utils.bounded import WorkBudget


@pytest.mark.parametrize("reset,expected", [(Decimal("60.9"), 60), (0, 1), (-4, 1), ("42", 42)])
def test_denied_admission_normalizes_scalar_retry_after(monkeypatch, reset, expected):
    engine = MagicMock()
    monkeypatch.setattr("agno.db.postgres._bounded.bounded_engine", lambda source, capacity: source)
    connection = engine.begin.return_value.__enter__.return_value
    denied = MagicMock()
    denied.first.return_value = None
    retry_after = MagicMock()
    retry_after.scalar_one.return_value = reset
    connection.execute.side_effect = [MagicMock(), denied, retry_after]
    limiter = PublicLimiter(engine, "test-namespace")
    limiter.ready = True

    result = limiter._consume("run", client_id="client", cost=1, budget=WorkBudget(3))

    assert result == Admission(False, expected, "rate_limited")
    assert connection.execute.call_count == 3
