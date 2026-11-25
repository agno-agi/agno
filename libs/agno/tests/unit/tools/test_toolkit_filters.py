import pytest

from agno.tools import Toolkit
from agno.tools.decorator import tool


def sync_lookup():
    return "sync"


async def async_lookup():
    return "async"


@pytest.mark.parametrize("filter_name", ["include_tools", "exclude_tools"])
def test_filters_accept_async_only_tool_aliases(filter_name):
    toolkit = Toolkit(async_tools=[(async_lookup, "lookup")], **{filter_name: ["lookup"]})
    assert toolkit.get_functions() == {}
    expected = {"lookup"} if filter_name == "include_tools" else set()
    assert set(toolkit.get_async_functions()) == expected


@pytest.mark.parametrize("filter_name", ["include_tools", "exclude_tools"])
def test_filters_accept_mixed_sync_and_async_names(filter_name):
    toolkit = Toolkit(
        tools=[sync_lookup],
        async_tools=[(async_lookup, "lookup")],
        **{filter_name: ["sync_lookup", "lookup"]},
    )
    expected = {"sync_lookup", "lookup"} if filter_name == "include_tools" else set()
    assert set(toolkit.get_async_functions()) == expected


@pytest.mark.parametrize("filter_name", ["include_tools", "exclude_tools"])
@pytest.mark.parametrize("invalid_name", ["missing", "async_lookup"])
def test_async_filters_still_reject_unregistered_names(filter_name, invalid_name):
    with pytest.raises(ValueError, match="not present in the toolkit"):
        Toolkit(async_tools=[(async_lookup, "lookup")], **{filter_name: [invalid_name]})


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("decorated", [False, True])
@pytest.mark.parametrize("include", [None, [], "selected"])
def test_empty_include_list_has_same_meaning_for_decorated_tools(asynchronous, decorated, include):
    entrypoint = async_lookup if asynchronous else sync_lookup
    name = entrypoint.__name__
    include = [name] if include == "selected" else include
    if decorated:
        entrypoint = tool()(entrypoint)
    toolkit = Toolkit(tools=[entrypoint], include_tools=include)
    expected = set() if include == [] else {name}
    assert set(toolkit.get_async_functions()) == expected
