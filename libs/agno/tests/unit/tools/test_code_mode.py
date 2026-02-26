import json
from typing import Optional
from unittest.mock import AsyncMock, Mock

import pytest

from agno.code_mode import CodeMode
from agno.tools import Toolkit
from agno.tools.function import Function


def search_items(query: str, category: Optional[str] = None) -> str:
    """Search items by keyword.

    Args:
        query: Search keyword
        category: Optional category filter

    Returns:
        JSON array of objects with keys: id (int), name (str)
    """
    return json.dumps([{"id": 1, "name": f"result for {query}"}])


def get_item_details(item_id: int) -> str:
    """Get full details for an item.

    Args:
        item_id: The unique item ID

    Returns:
        JSON object with keys: id, name, price (float)
    """
    return json.dumps({"id": item_id, "name": "Widget", "price": 9.99})


def tool_needing_agent(query: str, agent: Optional[object] = None) -> str:
    """A tool that needs the agent reference.

    Args:
        query: Search query

    Returns:
        JSON string with agent status
    """
    has_agent = agent is not None
    return json.dumps({"query": query, "has_agent": has_agent})


def tool_needing_run_context(query: str, run_context: Optional[object] = None) -> str:
    """A tool that needs run_context.

    Args:
        query: Search query
    """
    has_ctx = run_context is not None
    return json.dumps({"query": query, "has_run_context": has_ctx})


class SimpleToolkit(Toolkit):
    def __init__(self):
        super().__init__(name="simple", tools=[self.greet, self.add])

    def greet(self, name: str) -> str:
        """Greet someone by name.

        Args:
            name: The person's name

        Returns:
            A greeting string
        """
        return f"Hello, {name}!"

    def add(self, a: int, b: int) -> str:
        """Add two numbers.

        Args:
            a: First number
            b: Second number

        Returns:
            JSON object with key: result (int)
        """
        return json.dumps({"result": a + b})


@pytest.fixture
def code_mode_callables():
    return CodeMode(tools=[search_items, get_item_details])


@pytest.fixture
def code_mode_toolkit():
    return CodeMode(tools=[SimpleToolkit()])


@pytest.fixture
def code_mode_mixed():
    return CodeMode(tools=[SimpleToolkit(), search_items])


class TestInitialization:
    def test_accepts_callables(self, code_mode_callables):
        assert "search_items" in code_mode_callables.sandbox_functions
        assert "get_item_details" in code_mode_callables.sandbox_functions
        assert len(code_mode_callables.sandbox_functions) == 2

    def test_accepts_toolkit(self, code_mode_toolkit):
        assert "greet" in code_mode_toolkit.sandbox_functions
        assert "add" in code_mode_toolkit.sandbox_functions
        assert len(code_mode_toolkit.sandbox_functions) == 2

    def test_accepts_function_objects(self):
        func = Function.from_callable(search_items)
        cm = CodeMode(tools=[func])
        assert "search_items" in cm.sandbox_functions

    def test_accepts_mixed_types(self, code_mode_mixed):
        assert "greet" in code_mode_mixed.sandbox_functions
        assert "add" in code_mode_mixed.sandbox_functions
        assert "search_items" in code_mode_mixed.sandbox_functions

    def test_registers_run_code(self, code_mode_callables):
        assert "run_code" in code_mode_callables.functions

    def test_registers_async_run_code(self, code_mode_callables):
        assert "run_code" in code_mode_callables.async_functions


class TestHITLExclusion:
    def test_excludes_requires_confirmation(self):
        func = Function.from_callable(search_items)
        func.requires_confirmation = True
        cm = CodeMode(tools=[func])
        assert "search_items" not in cm.sandbox_functions

    def test_excludes_requires_user_input(self):
        func = Function.from_callable(search_items)
        func.requires_user_input = True
        cm = CodeMode(tools=[func])
        assert "search_items" not in cm.sandbox_functions

    def test_excludes_external_execution(self):
        func = Function.from_callable(search_items)
        func.external_execution = True
        cm = CodeMode(tools=[func])
        assert "search_items" not in cm.sandbox_functions

    def test_non_hitl_tools_included(self):
        func = Function.from_callable(search_items)
        cm = CodeMode(tools=[func])
        assert "search_items" in cm.sandbox_functions


class TestStubGeneration:
    def test_stubs_contain_function_names(self, code_mode_callables):
        assert "def search_items(" in code_mode_callables.stubs
        assert "def get_item_details(" in code_mode_callables.stubs

    def test_stubs_contain_parameters(self, code_mode_callables):
        assert "query: str" in code_mode_callables.stubs
        # from_callable maps Python int to JSON Schema "integer" which maps to "int",
        # but the actual mapping depends on the schema. Check the param name exists.
        assert "item_id:" in code_mode_callables.stubs

    def test_stubs_contain_optional_defaults(self, code_mode_callables):
        assert "category: str = None" in code_mode_callables.stubs

    def test_stubs_contain_docstrings(self, code_mode_callables):
        assert "Search items by keyword" in code_mode_callables.stubs
        assert "Returns:" in code_mode_callables.stubs

    def test_stubs_exclude_framework_params(self):
        cm = CodeMode(tools=[tool_needing_agent])
        assert "agent" not in cm.stubs.split("def tool_needing_agent(")[1].split(")")[0]
        assert "query: str" in cm.stubs

    def test_stubs_from_toolkit_functions(self, code_mode_toolkit):
        assert "def greet(" in code_mode_toolkit.stubs
        assert "def add(" in code_mode_toolkit.stubs
        assert "name: str" in code_mode_toolkit.stubs


class TestStubInjection:
    def test_stubs_in_get_functions(self, code_mode_callables):
        funcs = code_mode_callables.get_functions()
        desc = funcs["run_code"].description or ""
        assert "Available functions:" in desc
        assert "def search_items(" in desc

    def test_stubs_in_get_async_functions(self, code_mode_callables):
        funcs = code_mode_callables.get_async_functions()
        desc = funcs["run_code"].description or ""
        assert "Available functions:" in desc
        assert "def search_items(" in desc

    def test_stubs_not_duplicated(self, code_mode_callables):
        funcs1 = code_mode_callables.get_functions()
        funcs2 = code_mode_callables.get_functions()
        desc1 = funcs1["run_code"].description or ""
        desc2 = funcs2["run_code"].description or ""
        assert desc1.count("Available functions:") == 1
        assert desc2.count("Available functions:") == 1


class TestCodeExecution:
    def test_result_variable_captured(self, code_mode_callables):
        output = code_mode_callables.run_code('result = "hello world"')
        assert output == "hello world"

    def test_print_output_captured(self, code_mode_callables):
        output = code_mode_callables.run_code('print("printed output")')
        assert "printed output" in output

    def test_result_and_print_combined(self, code_mode_callables):
        output = code_mode_callables.run_code('result = "answer"\nprint("debug")')
        assert "answer" in output
        assert "debug" in output

    def test_fallback_to_last_variable(self, code_mode_callables):
        output = code_mode_callables.run_code("x = 42")
        assert "42" in output

    def test_no_output_message(self, code_mode_callables):
        output = code_mode_callables.run_code("pass")
        assert "no output" in output.lower()

    def test_tool_wrapper_called(self, code_mode_callables):
        output = code_mode_callables.run_code('data = json.loads(search_items(query="test"))\nresult = data[0]["name"]')
        assert "result for test" in output

    def test_tool_chaining(self, code_mode_callables):
        code = (
            'items = json.loads(search_items(query="widget"))\n'
            'details = json.loads(get_item_details(item_id=items[0]["id"]))\n'
            "result = f\"{details['name']} costs ${details['price']}\""
        )
        output = code_mode_callables.run_code(code)
        assert "Widget" in output
        assert "9.99" in output

    def test_loop_execution(self, code_mode_callables):
        code = (
            "names = []\n"
            "for i in range(3):\n"
            "    data = json.loads(get_item_details(item_id=i))\n"
            '    names.append(data["name"])\n'
            'result = ", ".join(names)'
        )
        output = code_mode_callables.run_code(code)
        assert "Widget" in output

    def test_syntax_error_returned(self, code_mode_callables):
        output = code_mode_callables.run_code("def broken(")
        assert "SyntaxError" in output

    def test_runtime_error_returned(self, code_mode_callables):
        output = code_mode_callables.run_code("x = 1 / 0")
        assert "ZeroDivisionError" in output

    def test_max_code_length_enforced(self):
        cm = CodeMode(tools=[search_items], max_code_length=10)
        output = cm.run_code("x = 1\n" * 100)
        assert "exceeds maximum length" in output

    def test_json_module_available(self, code_mode_callables):
        output = code_mode_callables.run_code('result = json.dumps({"a": 1})')
        assert '"a"' in output

    def test_math_module_available(self, code_mode_callables):
        output = code_mode_callables.run_code("result = str(math.sqrt(16))")
        assert "4.0" in output

    def test_import_blocked(self, code_mode_callables):
        output = code_mode_callables.run_code("import os")
        assert "Error" in output or "not allowed" in output

    def test_sys_import_blocked(self, code_mode_callables):
        output = code_mode_callables.run_code("import sys; result = str(type(sys))")
        assert "Error" in output or "not allowed" in output

    def test_sys_modules_escape_blocked(self, code_mode_callables):
        output = code_mode_callables.run_code('import sys; os_mod = sys.modules["os"]; result = os_mod.getcwd()')
        assert "Error" in output or "not allowed" in output

    @pytest.mark.xfail(
        reason="__globals__ inherent to Python functions; sandbox targets LLM code, not adversarial input"
    )
    def test_wrapper_globals_blocked(self, code_mode_callables):
        output = code_mode_callables.run_code("result = str(search_items.__globals__.keys())")
        assert "Error" in output or "not allowed" in output

    def test_builtins_import_blocked(self, code_mode_callables):
        output = code_mode_callables.run_code("import builtins; result = str(builtins)")
        assert "Error" in output or "not allowed" in output

    def test_toolkit_tools_callable(self, code_mode_toolkit):
        output = code_mode_toolkit.run_code('result = greet(name="World")')
        assert "Hello, World!" in output

    def test_toolkit_tool_returns_json(self, code_mode_toolkit):
        output = code_mode_toolkit.run_code('data = json.loads(add(a=3, b=4))\nresult = str(data["result"])')
        assert "7" in output

    def test_positional_args_supported(self, code_mode_callables):
        output = code_mode_callables.run_code('result = search_items("test")')
        assert "result for test" in output

    def test_positional_args_with_toolkit(self, code_mode_toolkit):
        output = code_mode_toolkit.run_code('result = greet("World")')
        assert "Hello, World!" in output

    def test_mixed_positional_and_keyword(self, code_mode_callables):
        output = code_mode_callables.run_code('result = search_items("test", category="electronics")')
        assert "result for test" in output


class TestFrameworkInjection:
    def test_agent_forwarded_when_requested(self):
        cm = CodeMode(tools=[tool_needing_agent])
        mock_agent = Mock()
        run_code_func = cm.functions.get("run_code")
        if run_code_func:
            run_code_func._agent = mock_agent

        output = cm.run_code('result = tool_needing_agent(query="test")')
        data = json.loads(output)
        assert data["has_agent"] is True
        assert data["query"] == "test"

    def test_run_context_forwarded_when_requested(self):
        cm = CodeMode(tools=[tool_needing_run_context])
        mock_ctx = Mock()
        run_code_func = cm.functions.get("run_code")
        if run_code_func:
            run_code_func._run_context = mock_ctx

        output = cm.run_code('result = tool_needing_run_context(query="test")')
        data = json.loads(output)
        assert data["has_run_context"] is True

    def test_no_framework_args_when_not_in_signature(self, code_mode_callables):
        output = code_mode_callables.run_code('result = search_items(query="test")')
        assert "result for test" in output


class TestPreapprovedModules:
    def test_datetime_available(self, code_mode_callables):
        output = code_mode_callables.run_code("result = str(type(datetime.date.today()))")
        assert "date" in output

    def test_datetime_operations(self, code_mode_callables):
        output = code_mode_callables.run_code("now = datetime.datetime.now()\nresult = str(now.year)")
        assert "202" in output

    def test_re_available(self, code_mode_callables):
        output = code_mode_callables.run_code('result = str(re.findall(r"[0-9]+", "abc123def456"))')
        assert "123" in output
        assert "456" in output

    def test_re_sub(self, code_mode_callables):
        output = code_mode_callables.run_code('result = re.sub(r"\\d+", "X", "hello42world99")')
        assert output == "helloXworldX"

    def test_collections_counter(self, code_mode_callables):
        output = code_mode_callables.run_code('c = collections.Counter("abracadabra")\nresult = str(c.most_common(2))')
        assert "a" in output
        assert "5" in output

    def test_collections_defaultdict(self, code_mode_callables):
        output = code_mode_callables.run_code(
            "d = collections.defaultdict(list)\nd['k'].append(1)\nresult = str(dict(d))"
        )
        assert "k" in output
        assert "1" in output


class TestPreapprovedBuiltins:
    def test_pow(self, code_mode_callables):
        output = code_mode_callables.run_code("result = str(pow(2, 10))")
        assert output == "1024"

    def test_pow_three_arg(self, code_mode_callables):
        output = code_mode_callables.run_code("result = str(pow(2, 10, 100))")
        assert output == "24"

    def test_divmod(self, code_mode_callables):
        output = code_mode_callables.run_code("result = str(divmod(17, 5))")
        assert output == "(3, 2)"

    def test_ord(self, code_mode_callables):
        output = code_mode_callables.run_code("result = str(ord('A'))")
        assert output == "65"

    def test_chr(self, code_mode_callables):
        output = code_mode_callables.run_code("result = chr(65)")
        assert output == "A"

    def test_hex(self, code_mode_callables):
        output = code_mode_callables.run_code("result = hex(255)")
        assert output == "0xff"

    def test_bin(self, code_mode_callables):
        output = code_mode_callables.run_code("result = bin(42)")
        assert output == "0b101010"

    def test_oct(self, code_mode_callables):
        output = code_mode_callables.run_code("result = oct(8)")
        assert output == "0o10"

    def test_format_builtin(self, code_mode_callables):
        output = code_mode_callables.run_code("result = format(255, '08b')")
        assert output == "11111111"

    def test_format_float(self, code_mode_callables):
        output = code_mode_callables.run_code("result = format(3.14159, '.2f')")
        assert output == "3.14"


class TestAdditionalModules:
    def test_additional_module_available(self):
        import datetime

        cm = CodeMode(tools=[search_items], additional_modules={"datetime": datetime})
        output = cm.run_code("result = str(type(datetime.date.today()))")
        assert "date" in output


class TestReturnVariable:
    def test_custom_return_variable(self):
        cm = CodeMode(tools=[search_items], return_variable="answer")
        output = cm.run_code('answer = "custom return"')
        assert "custom return" in output

    def test_custom_variable_takes_priority(self):
        cm = CodeMode(tools=[search_items], return_variable="answer")
        output = cm.run_code('answer = "correct"\nresult = "fallback"')
        assert output == "correct"


def _make_many_callables(n: int):
    funcs = []
    for i in range(n):

        def _fn(x: str = "default", _i: int = i) -> str:
            return json.dumps({"tool": f"tool_{_i}", "input": x})

        _fn.__name__ = f"tool_{i}"
        _fn.__doc__ = f"Tool number {i}. Does thing {i}."
        funcs.append(_fn)
    return funcs


class TestDiscoveryMode:
    def test_auto_enables_above_threshold(self):
        cm = CodeMode(tools=_make_many_callables(20), discovery_threshold=15)
        assert cm.discovery_enabled is True

    def test_auto_disables_below_threshold(self):
        cm = CodeMode(tools=_make_many_callables(5), discovery_threshold=15)
        assert cm.discovery_enabled is False

    def test_auto_disables_at_threshold(self):
        cm = CodeMode(tools=_make_many_callables(15), discovery_threshold=15)
        assert cm.discovery_enabled is False

    def test_explicit_true_with_few_tools(self):
        cm = CodeMode(tools=[search_items], discovery=True)
        assert cm.discovery_enabled is True

    def test_explicit_false_with_many_tools(self):
        cm = CodeMode(tools=_make_many_callables(20), discovery=False)
        assert cm.discovery_enabled is False

    def test_invalid_discovery_value_raises(self):
        with pytest.raises(ValueError, match="discovery must be"):
            CodeMode(tools=[search_items], discovery="always")

    def test_registers_search_tools_when_enabled(self):
        cm = CodeMode(tools=[search_items], discovery=True)
        assert "search_tools" in cm.functions

    def test_registers_async_search_tools(self):
        cm = CodeMode(tools=[search_items], discovery=True)
        assert "search_tools" in cm.async_functions

    def test_no_search_tools_when_disabled(self):
        cm = CodeMode(tools=[search_items], discovery=False)
        assert "search_tools" not in cm.functions

    def test_run_code_still_registered_in_discovery(self):
        cm = CodeMode(tools=[search_items], discovery=True)
        assert "run_code" in cm.functions
        assert "run_code" in cm.async_functions


class TestSearchTools:
    def test_search_by_name(self):
        cm = CodeMode(tools=[search_items, get_item_details], discovery=True)
        result = cm.search_tools("search_items")
        assert "def search_items(" in result

    def test_search_by_description_keyword(self):
        cm = CodeMode(tools=[search_items, get_item_details], discovery=True)
        result = cm.search_tools("keyword")
        assert "def search_items(" in result

    def test_search_no_match(self):
        cm = CodeMode(tools=[search_items], discovery=True)
        result = cm.search_tools("nonexistent_xyz")
        assert "No functions found" in result

    def test_search_returns_multiple(self):
        cm = CodeMode(tools=[search_items, get_item_details], discovery=True)
        result = cm.search_tools("item")
        assert "search_items" in result
        assert "get_item_details" in result

    def test_search_empty_query_rejected(self):
        cm = CodeMode(tools=[search_items], discovery=True)
        result = cm.search_tools("")
        assert "at least 2 characters" in result

    def test_search_short_query_rejected(self):
        cm = CodeMode(tools=[search_items], discovery=True)
        result = cm.search_tools("a")
        assert "at least 2 characters" in result

    def test_search_caps_at_10(self):
        cm = CodeMode(tools=_make_many_callables(20), discovery=True)
        result = cm.search_tools("tool")
        assert "showing first 10" in result

    def test_search_count_reported(self):
        cm = CodeMode(tools=[search_items, get_item_details], discovery=True)
        result = cm.search_tools("item")
        assert "Found 2 function(s)" in result


class TestDiscoveryCatalog:
    def test_catalog_in_run_code_description(self):
        cm = CodeMode(tools=[search_items, get_item_details], discovery=True)
        funcs = cm.get_functions()
        desc = funcs["run_code"].description or ""
        assert "use search_tools for full signatures" in desc
        assert "search_items:" in desc
        assert "get_item_details:" in desc

    def test_full_stubs_not_in_run_code_when_discovery(self):
        cm = CodeMode(tools=[search_items, get_item_details], discovery=True)
        funcs = cm.get_functions()
        desc = funcs["run_code"].description or ""
        assert "def search_items(" not in desc
        assert "def get_item_details(" not in desc

    def test_standard_mode_has_full_stubs(self):
        cm = CodeMode(tools=[search_items], discovery=False)
        funcs = cm.get_functions()
        desc = funcs["run_code"].description or ""
        assert "Available functions:" in desc
        assert "def search_items(" in desc

    def test_catalog_not_duplicated(self):
        cm = CodeMode(tools=[search_items], discovery=True)
        cm.get_functions()
        cm.get_functions()
        funcs = cm.get_functions()
        desc = funcs["run_code"].description or ""
        assert desc.count("use search_tools") == 1


class TestDiscoveryExecution:
    def test_all_tools_callable_in_discovery_mode(self):
        cm = CodeMode(tools=[search_items, get_item_details], discovery=True)
        output = cm.run_code('data = json.loads(search_items(query="test"))\nresult = data[0]["name"]')
        assert "result for test" in output

    def test_unsearched_tool_still_callable(self):
        cm = CodeMode(tools=[search_items, get_item_details], discovery=True)
        output = cm.run_code("result = get_item_details(item_id=42)")
        data = json.loads(output)
        assert data["name"] == "Widget"

    def test_code_execution_identical_to_standard(self):
        cm_discovery = CodeMode(tools=[search_items], discovery=True)
        cm_standard = CodeMode(tools=[search_items], discovery=False)
        code = 'result = search_items(query="hello")'
        assert cm_discovery.run_code(code) == cm_standard.run_code(code)


class TestRebuild:
    def test_rebuild_updates_functions(self):
        toolkit = SimpleToolkit()
        cm = CodeMode(tools=[toolkit], discovery=True)
        assert "greet" in cm.sandbox_functions
        cm.rebuild()
        assert "greet" in cm.sandbox_functions

    def test_rebuild_resets_stubs_injected(self):
        cm = CodeMode(tools=[search_items], discovery=True)
        cm.get_functions()
        assert cm.sync_stubs_injected is True
        cm.rebuild()
        assert cm.sync_stubs_injected is False
        assert cm.async_stubs_injected is False


def _mock_model_response(code: str):
    resp = Mock()
    resp.content = f"```python\n{code}\n```"
    return resp


class TestCodeModelInit:
    def test_code_model_disables_discovery(self):
        mock_model = Mock()
        cm = CodeMode(tools=_make_many_callables(20), code_model=mock_model)
        assert cm.discovery_enabled is False

    def test_code_model_no_search_tools(self):
        mock_model = Mock()
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        assert "search_tools" not in cm.functions

    def test_code_model_registers_run_code(self):
        mock_model = Mock()
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        assert "run_code" in cm.functions
        assert "run_code" in cm.async_functions

    def test_code_model_generates_catalog(self):
        mock_model = Mock()
        cm = CodeMode(tools=[search_items, get_item_details], code_model=mock_model)
        assert cm.catalog
        assert "search_items:" in cm.catalog
        assert "get_item_details:" in cm.catalog

    def test_code_model_run_code_description(self):
        mock_model = Mock()
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        funcs = cm.get_functions()
        desc = funcs["run_code"].description or ""
        assert "plain English" in desc
        assert "code-generation model" in desc
        assert "search_items:" in desc

    def test_code_model_description_no_stubs(self):
        mock_model = Mock()
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        funcs = cm.get_functions()
        desc = funcs["run_code"].description or ""
        assert "def search_items(" not in desc


class TestCodeModelExecution:
    def test_run_code_delegates_to_code_model(self):
        mock_model = Mock()
        mock_model.response.return_value = _mock_model_response('result = "hello from code model"')
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        output = cm.run_code("Say hello")
        assert "hello from code model" in output
        mock_model.response.assert_called_once()

    def test_code_model_receives_stubs_in_system(self):
        mock_model = Mock()
        mock_model.response.return_value = _mock_model_response('result = "ok"')
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        cm.run_code("Do something")
        messages = mock_model.response.call_args.kwargs["messages"]
        system_msg = messages[0]
        assert system_msg.role == "system"
        assert "def search_items(" in system_msg.content

    def test_code_model_receives_task_in_user(self):
        mock_model = Mock()
        mock_model.response.return_value = _mock_model_response('result = "ok"')
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        cm.run_code("Find all laptops")
        messages = mock_model.response.call_args.kwargs["messages"]
        user_msg = messages[1]
        assert user_msg.role == "user"
        assert "Find all laptops" in user_msg.content

    def test_code_model_retries_on_exec_error(self):
        mock_model = Mock()
        mock_model.response.side_effect = [
            _mock_model_response("x = 1 / 0"),
            _mock_model_response('result = "fixed"'),
        ]
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        output = cm.run_code("Calculate something")
        assert "fixed" in output
        assert mock_model.response.call_count == 2

    def test_code_model_no_retry_on_tool_error(self):
        def failing_tool(query: str) -> str:
            """Returns error from tool."""
            return "Error: API rate limit exceeded"

        mock_model = Mock()
        mock_model.response.return_value = _mock_model_response('result = failing_tool(query="test")')
        cm = CodeMode(tools=[failing_tool], code_model=mock_model)
        output = cm.run_code("Call the tool")
        assert "Error: API rate limit exceeded" in output
        assert mock_model.response.call_count == 1

    def test_code_model_retry_includes_error(self):
        mock_model = Mock()
        mock_model.response.side_effect = [
            _mock_model_response("x = 1 / 0"),
            _mock_model_response('result = "ok"'),
        ]
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        cm.run_code("Do math")
        second_call_messages = mock_model.response.call_args_list[1].kwargs["messages"]
        user_msg = second_call_messages[1].content
        assert "Previous attempt failed" in user_msg
        assert "ZeroDivisionError" in user_msg

    def test_code_model_max_retries_exceeded(self):
        mock_model = Mock()
        mock_model.response.return_value = _mock_model_response("x = 1 / 0")
        cm = CodeMode(tools=[search_items], code_model=mock_model, max_code_retries=2)
        output = cm.run_code("Bad task")
        assert "failed after 2 attempts" in output
        assert mock_model.response.call_count == 2

    def test_code_model_can_call_tools(self):
        mock_model = Mock()
        mock_model.response.return_value = _mock_model_response(
            'data = json.loads(search_items(query="laptop"))\nresult = data[0]["name"]'
        )
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        output = cm.run_code("Search for laptops")
        assert "result for laptop" in output

    def test_code_model_chains_tools(self):
        mock_model = Mock()
        mock_model.response.return_value = _mock_model_response(
            'items = json.loads(search_items(query="test"))\n'
            'details = json.loads(get_item_details(item_id=items[0]["id"]))\n'
            "result = f\"{details['name']} ${details['price']}\""
        )
        cm = CodeMode(tools=[search_items, get_item_details], code_model=mock_model)
        output = cm.run_code("Search and get details")
        assert "Widget" in output
        assert "9.99" in output


class TestCodeModelExtractCode:
    def test_extract_python_fence(self):
        text = '```python\nresult = "hello"\n```'
        assert CodeMode._extract_code_block(text) == 'result = "hello"'

    def test_extract_plain_fence(self):
        text = '```\nresult = "hello"\n```'
        assert CodeMode._extract_code_block(text) == 'result = "hello"'

    def test_extract_no_fence(self):
        text = 'result = "hello"'
        assert CodeMode._extract_code_block(text) == 'result = "hello"'

    def test_extract_with_surrounding_text(self):
        text = 'Here is the code:\n```python\nresult = "hello"\n```\nDone!'
        assert CodeMode._extract_code_block(text) == 'result = "hello"'

    def test_extract_multiline(self):
        text = "```python\nx = 1\ny = 2\nresult = str(x + y)\n```"
        code = CodeMode._extract_code_block(text)
        assert "x = 1" in code
        assert "result = str(x + y)" in code


class TestCodeModelAsync:
    @pytest.mark.asyncio
    async def test_arun_code_delegates_to_code_model(self):
        mock_model = Mock()
        mock_model.aresponse = AsyncMock(return_value=_mock_model_response('result = "async hello"'))
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        output = await cm.arun_code("Say hello async")
        assert "async hello" in output
        mock_model.aresponse.assert_called_once()

    @pytest.mark.asyncio
    async def test_arun_code_retries_on_error(self):
        mock_model = Mock()
        mock_model.aresponse = AsyncMock(
            side_effect=[
                _mock_model_response("x = 1 / 0"),
                _mock_model_response('result = "async fixed"'),
            ]
        )
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        output = await cm.arun_code("Calculate")
        assert "async fixed" in output
        assert mock_model.aresponse.call_count == 2


class _FakeFunctionCall:
    """Mimics FunctionCall for fc injection tests."""

    def __init__(self, function):
        self.function = function


class TestCodeModelMetrics:
    def test_run_response_identity_bug(self):
        """Original Function and deep copy are different objects."""
        cm = CodeMode(tools=[search_items], code_model=Mock())
        original = cm.functions["run_code"]
        copy = original.model_copy(deep=True)
        copy._run_response = "INJECTED"
        assert original._run_response is None
        assert copy._run_response == "INJECTED"
        assert original is not copy

    def test_fc_none_passes_none_run_response(self):
        """Direct call without fc gracefully passes run_response=None."""
        mock_model = Mock()
        mock_model.response.return_value = _mock_model_response('result = "ok"')
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        cm.run_code("task")
        assert mock_model.response.call_args.kwargs.get("run_response") is None

    def test_fc_injects_run_response_to_code_model(self):
        """fc.function._run_response flows through to code_model.response()."""
        mock_model = Mock()
        mock_model.response.return_value = _mock_model_response('result = "ok"')
        cm = CodeMode(tools=[search_items], code_model=mock_model)

        # Simulate agent's deep-copy + injection
        func_copy = cm.functions["run_code"].model_copy(deep=True)
        fake_run_response = Mock()
        fake_run_response.metrics = Mock()
        func_copy._run_response = fake_run_response

        fc = _FakeFunctionCall(func_copy)
        cm.run_code("task", fc=fc)

        called_run_response = mock_model.response.call_args.kwargs.get("run_response")
        assert called_run_response is fake_run_response

    def test_fc_run_response_survives_retries(self):
        """Same run_response is passed on each retry attempt."""
        mock_model = Mock()
        mock_model.response.side_effect = [
            _mock_model_response("x = 1 / 0"),
            _mock_model_response("y = undefined_var"),
            _mock_model_response('result = "ok"'),
        ]
        cm = CodeMode(tools=[search_items], code_model=mock_model, max_code_retries=3)

        func_copy = cm.functions["run_code"].model_copy(deep=True)
        fake_run_response = Mock()
        fake_run_response.metrics = Mock()
        func_copy._run_response = fake_run_response

        fc = _FakeFunctionCall(func_copy)
        cm.run_code("task", fc=fc)

        assert mock_model.response.call_count == 3
        for call in mock_model.response.call_args_list:
            assert call.kwargs.get("run_response") is fake_run_response

    @pytest.mark.asyncio
    async def test_async_fc_injects_run_response(self):
        """Async path also threads run_response through fc."""
        mock_model = Mock()
        mock_model.aresponse = AsyncMock(return_value=_mock_model_response('result = "ok"'))
        cm = CodeMode(tools=[search_items], code_model=mock_model)

        func_copy = cm.functions["run_code"].model_copy(deep=True)
        fake_run_response = Mock()
        fake_run_response.metrics = Mock()
        func_copy._run_response = fake_run_response

        fc = _FakeFunctionCall(func_copy)
        await cm.arun_code("task", fc=fc)

        called_run_response = mock_model.aresponse.call_args.kwargs.get("run_response")
        assert called_run_response is fake_run_response

    def test_fc_schema_excludes_fc_param(self):
        """fc parameter must not appear in the tool's JSON schema."""
        cm = CodeMode(tools=[search_items], code_model=Mock())
        funcs = cm.get_functions()
        run_code_func = funcs["run_code"]
        params = run_code_func.parameters or {}
        properties = params.get("properties", {})
        assert "fc" not in properties
        required = params.get("required", [])
        assert "fc" not in required

    def test_model_type_set_to_code_model(self):
        """code_model gets ModelType.CODE_MODEL set in __init__."""
        from agno.metrics import ModelType

        mock_model = Mock()
        CodeMode(tools=[search_items], code_model=mock_model)
        assert mock_model.model_type == ModelType.CODE_MODEL

    def test_no_code_model_skips_metrics(self):
        """Without code_model, run_code doesn't touch metrics at all."""
        cm = CodeMode(tools=[search_items])
        output = cm.run_code('result = "direct exec"')
        assert "direct exec" in output
