import pytest

from agno.utils.safe_formatter import SafeFormatter


@pytest.mark.parametrize(
    "template,args,kwargs,expected",
    [
        ("{} {}", ("hello", "world"), {}, "hello world"),
        ("{1} {0}", ("first", "second"), {}, "second first"),
        ("{0} {name}", ("hello",), {"name": "world"}, "hello world"),
        ("{0:.2f}", (1.234,), {}, "1.23"),
        ("{0[label]}", ({"label": "value"},), {}, "value"),
        ("{0!r}", ("text",), {}, "'text'"),
    ],
)
def test_formatter_resolves_positional_values(template, args, kwargs, expected):
    assert SafeFormatter().format(template, *args, **kwargs) == expected


def test_missing_positional_argument_raises_index_error():
    with pytest.raises(IndexError):
        SafeFormatter().format("{1}", "only one")


def test_missing_named_argument_retains_existing_fallback():
    assert SafeFormatter().format("{known} {missing}", known="value") == "value missing"
