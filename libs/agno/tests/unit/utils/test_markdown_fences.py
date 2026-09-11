"""Shared fence rules keep literal examples out of prose transformations."""

import pytest

from agno.utils.markdown import advance_code_fence


@pytest.mark.parametrize(
    "opening,inside,closing",
    [
        ("````markdown", "```", "````"),
        ("~~~mdx", "```", "~~~~"),
        ("```python", "```not-a-close", "```"),
        ("  ````markdown", "  ~~~~", "  `````  "),
    ],
)
def test_matching_fences_preserve_nested_content(opening, inside, closing):
    state, delimiter = advance_code_fence(opening, None)
    assert delimiter and state is not None and state[2] == opening
    original = state
    for line in (inside, "<Note>literal</Note>", "", "# literal heading"):
        state, delimiter = advance_code_fence(line, state)
        assert state == original and not delimiter
    assert advance_code_fence(closing, state) == (None, True)
    assert advance_code_fence("ordinary prose", None) == (None, False)


def test_backticks_in_info_string_do_not_open_a_block():
    assert advance_code_fence("```invalid`info", None) == (None, False)
    state, delimiter = advance_code_fence("~~~valid`info", None)
    assert state == ("~", 3, "~~~valid`info") and delimiter
