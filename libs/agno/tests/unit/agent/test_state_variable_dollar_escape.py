"""State-variable substitution must not touch literal ``$word`` text.

The documented template syntax is ``{var}``. The substitution machinery converts
``{var}`` to ``${var}`` and then runs ``string.Template.safe_substitute``, which
also matches any pre-existing ``$word`` the user wrote. A prompt containing e.g.
``$name`` (shell/env text) used to be silently rewritten whenever ``name`` was a
session-state key.
"""

import pytest

from agno.agent._messages import format_message_with_state_variables
from agno.run.base import RunContext
from agno.team._messages import _format_message_with_state_variables


@pytest.fixture
def run_context():
    return RunContext(run_id="r", session_id="s", session_state={"name": "Alice", "path": "/tmp"})


@pytest.mark.parametrize("fn", [format_message_with_state_variables, _format_message_with_state_variables])
def test_literal_dollar_var_is_not_substituted(fn, run_context):
    assert fn(None, "echo $name to shell", run_context) == "echo $name to shell"
    assert fn(None, "export PATH=$path:/x", run_context) == "export PATH=$path:/x"


@pytest.mark.parametrize("fn", [format_message_with_state_variables, _format_message_with_state_variables])
def test_documented_brace_syntax_still_substitutes(fn, run_context):
    assert fn(None, "Hi {name}", run_context) == "Hi Alice"
    # Brace form is substituted; the literal $name in the same string is preserved.
    assert fn(None, "{name} owes $name", run_context) == "Alice owes $name"
