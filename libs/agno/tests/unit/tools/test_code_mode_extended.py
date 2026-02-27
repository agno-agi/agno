import json
from typing import Optional

import pytest

from agno.code_mode import CodeMode
from agno.code_mode.tool import FRAMEWORK_ARG_ATTRS, FRAMEWORK_PARAMS
from agno.tools.function import Function, ToolResult
from agno.utils.code_execution import prepare_python_code


def search_items(query: str, category: Optional[str] = None) -> str:
    """Search items by keyword."""
    return json.dumps([{"id": 1, "name": f"result for {query}"}])


def get_item_details(item_id: int) -> str:
    """Get full details for an item."""
    return json.dumps({"id": item_id, "name": "Widget", "price": 9.99})


def failing_tool(x: str) -> str:
    """A tool that always raises."""
    raise RuntimeError("Tool exploded")


def none_returning_tool(x: str) -> str:
    """A tool that returns None."""
    return None  # type: ignore


def _make_many_callables(n: int):
    funcs = []
    for i in range(n):

        def _fn(x: str = "default", _i: int = i) -> str:
            return json.dumps({"tool": f"tool_{_i}", "input": x})

        _fn.__name__ = f"tool_{i}"
        _fn.__doc__ = f"Tool number {i}. Does thing {i}."
        funcs.append(_fn)
    return funcs


# ── BUG-001: prepare_python_code corrupts string literals ────────


class TestPrepareCodeStringCorruption:
    def test_true_in_string_literal(self):
        code = 'result = "the answer is true"'
        processed = prepare_python_code(code)
        assert processed == code, f"String corrupted: {processed!r}"

    def test_false_in_string_literal(self):
        code = 'result = "set active to false"'
        processed = prepare_python_code(code)
        assert processed == code, f"String corrupted: {processed!r}"

    def test_none_in_string_literal(self):
        code = 'result = "none of the above"'
        processed = prepare_python_code(code)
        assert processed == code, f"String corrupted: {processed!r}"

    def test_json_true_inside_python_string(self):
        code = """data = json.loads('{"active": true}')"""
        processed = prepare_python_code(code)
        assert "true" in processed, f"JSON true keyword was capitalized to True, breaking json.loads: {processed!r}"

    def test_variable_name_not_corrupted(self):
        code = "true_count = 5"
        processed = prepare_python_code(code)
        assert processed == code

    def test_standalone_keyword_fixed(self):
        code = "x = true"
        processed = prepare_python_code(code)
        assert processed == "x = True"

    def test_end_to_end_string_corruption(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code('result = "the answer is true"')
        assert output == "the answer is true", f"Output corrupted: {output!r}"


# ── BUG-002: Tool names shadow preapproved modules ───────────────


class TestNameCollisions:
    @pytest.mark.xfail(reason="BUG-002: tool names shadow preapproved modules in namespace")
    def test_tool_named_json_shadows_module(self):
        def json_tool(query: str) -> str:
            """A tool unfortunately named json."""
            return "tool response"

        json_tool.__name__ = "json"
        cm = CodeMode(tools=[json_tool])
        output = cm.run_code('result = json.dumps({"a": 1})')
        assert '"a"' in output, f"json.dumps() broken because tool shadowed the module: {output!r}"

    @pytest.mark.xfail(reason="BUG-002: tool names shadow preapproved modules in namespace")
    def test_tool_named_math_shadows_module(self):
        def math_tool(x: str) -> str:
            """Tool named math."""
            return "42"

        math_tool.__name__ = "math"
        cm = CodeMode(tools=[math_tool])
        output = cm.run_code("result = str(math.sqrt(16))")
        assert "4.0" in output, f"math.sqrt() broken because tool shadowed the module: {output!r}"


# ── SEC-001: Wrapper __globals__ exposes sandbox.py internals ─────


@pytest.mark.xfail(reason="WONTFIX: __globals__ inherent to Python functions. LLM threat model only.")
class TestSandboxEscapeViaGlobals:
    def test_globals_expose_io_module(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = str('io' in search_items.__globals__)")
        assert "Error" in output, f"io module accessible through __globals__: {output!r}"

    def test_globals_expose_unrestricted_builtins(self):
        cm = CodeMode(tools=[search_items])
        code = (
            "bi = search_items.__globals__['__builtins__']\n"
            "has_open = 'open' in bi if isinstance(bi, dict) else hasattr(bi, 'open')\n"
            "result = str(has_open)"
        )
        output = cm.run_code(code)
        assert "Error" in output, f"Unrestricted builtins accessible through __globals__: {output!r}"

    def test_closure_exposes_tool_object(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = str(len(search_items.__closure__))")
        assert "Error" in output, (
            f"__closure__ accessible with {output} cells (includes tool object with modifiable state)"
        )


# ── SEC-002: Subclass walking bypasses import restrictions ────────


@pytest.mark.xfail(reason="WONTFIX: CPython __subclasses__() inherent to pure-Python sandbox. LLM threat model only.")
class TestSandboxEscapeViaSubclasses:
    def test_subclass_list_accessible(self):
        cm = CodeMode(tools=[search_items])
        code = "classes = ().__class__.__bases__[0].__subclasses__()\nresult = str(len(classes))"
        output = cm.run_code(code)
        assert "Error" in output, f"__subclasses__() returned {output} classes, enabling sandbox escape"

    def test_subclass_walking_finds_dangerous_classes(self):
        cm = CodeMode(tools=[search_items])
        code = (
            "found = [c.__name__ for c in ().__class__.__bases__[0].__subclasses__()\n"
            "         if 'wrap_close' in c.__name__ or 'Popen' in c.__name__]\n"
            "result = str(found)"
        )
        output = cm.run_code(code)
        assert "Error" in output or output == "[]", f"Dangerous classes found via __subclasses__(): {output!r}"


# ── SEC-003: Unblocked dangerous modules ─────────────────────────


@pytest.mark.xfail(reason="WONTFIX: Low-risk modules not blocked. Sandbox targets LLM code, not adversarial input.")
class TestUnblockedModules:
    def test_pickle_not_blocked(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("import pickle\nresult = str(type(pickle))")
        assert "not allowed" in output or "Error" in output, f"pickle importable in sandbox: {output!r}"

    def test_tempfile_not_blocked(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("import tempfile\nresult = str(type(tempfile))")
        assert "not allowed" in output or "Error" in output, f"tempfile importable in sandbox: {output!r}"

    def test_sqlite3_not_blocked(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("import sqlite3\nresult = str(type(sqlite3))")
        assert "not allowed" in output or "Error" in output, f"sqlite3 importable in sandbox: {output!r}"

    def test_marshal_not_blocked(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("import marshal\nresult = str(type(marshal))")
        assert "not allowed" in output or "Error" in output, f"marshal importable in sandbox: {output!r}"


def test_known_blocked_modules_stay_blocked():
    cm = CodeMode(tools=[search_items])
    for mod in ["os", "sys", "subprocess", "socket", "shutil"]:
        output = cm.run_code(f"import {mod}\nresult = 'imported'")
        assert "not allowed" in output or "Error" in output, f"{mod} should be blocked: {output!r}"


# ── Builtin restrictions ─────────────────────────────────────────


class TestBuiltinRestrictions:
    def test_eval_not_available(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code('result = eval("1+1")')
        assert "Error" in output

    def test_exec_not_available(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code('exec("x = 1")\nresult = str(x)')
        assert "Error" in output

    def test_compile_not_available(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code('c = compile("x=1", "<s>", "exec")')
        assert "Error" in output

    def test_open_not_available(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code('f = open("/etc/passwd")')
        assert "Error" in output

    def test_getattr_not_available(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = str(getattr(search_items, '_fn'))")
        assert "Error" in output

    def test___import___uses_restricted_version(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("os = __import__('os')\nresult = str(os)")
        assert "not allowed" in output or "Error" in output


# ── Tool exception handling ──────────────────────────────────────


class TestToolExceptions:
    def test_tool_raising_exception(self):
        cm = CodeMode(tools=[failing_tool])
        output = cm.run_code('result = failing_tool(x="test")')
        assert "RuntimeError" in output or "exploded" in output

    def test_tool_raising_in_loop(self):
        def sometimes_fails(n: int) -> str:
            """Fails on n=3."""
            if n == 3:
                raise ValueError("Bad value 3")
            return json.dumps({"n": n})

        cm = CodeMode(tools=[sometimes_fails])
        code = "results = []\nfor i in range(5):\n    results.append(sometimes_fails(n=i))\nresult = str(len(results))"
        output = cm.run_code(code)
        assert "ValueError" in output or "Bad value 3" in output

    def test_tool_returning_none(self):
        cm = CodeMode(tools=[none_returning_tool])
        output = cm.run_code('result = none_returning_tool(x="test")')
        assert output is not None  # should not crash


# ── Namespace isolation ──────────────────────────────────────────


class TestNamespaceIsolation:
    def test_variables_dont_persist(self):
        cm = CodeMode(tools=[search_items])
        cm.run_code("secret = 42")
        output = cm.run_code("result = str(secret)")
        assert "Error" in output, f"Variable leaked between calls: {output!r}"

    def test_tools_available_across_calls(self):
        cm = CodeMode(tools=[search_items])
        out1 = cm.run_code('result = search_items(query="first")')
        out2 = cm.run_code('result = search_items(query="second")')
        assert "first" in out1
        assert "second" in out2

    def test_module_state_persists(self):
        import json as real_json

        cm = CodeMode(tools=[search_items])
        cm.run_code("json._test_leak = 42")
        output = cm.run_code("result = str(json._test_leak)")
        if hasattr(real_json, "_test_leak"):
            del real_json._test_leak
        # Module objects are shared — state leaks. Known limitation.
        assert "42" in output

    def test_media_doesnt_leak_across_calls(self):
        from agno.media import Image

        def image_tool(prompt: str) -> ToolResult:
            """Returns an image."""
            return ToolResult(
                content=f"Image for: {prompt}",
                images=[Image(url="https://example.com/img.png")],
            )

        cm = CodeMode(tools=[image_tool])
        cm.run_code('result = image_tool(prompt="sunset")')
        result2 = cm.run_code('result = "no images"')
        assert isinstance(result2, str)
        assert "no images" in result2


# ── Falsy result handling ────────────────────────────────────────


class TestFalsyResultValues:
    def test_result_zero(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = 0")
        assert output == "0"

    def test_result_zero_float(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = 0.0")
        assert output == "0.0"

    def test_result_false(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = False")
        assert output == "False"

    def test_result_empty_list(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = []")
        assert output == "[]"

    def test_result_empty_dict(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = {}")
        assert output == "{}"

    def test_result_empty_string(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code('result = ""')
        # Empty string is not None, so str("") = "" should be returned
        # But "\n".join([""]) = "" which is falsy — check if it falls through
        assert "no output" not in output.lower(), f"Empty string result was lost, got fallback message: {output!r}"

    def test_result_none_uses_fallback(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code('result = None\nprint("fallback")')
        assert "fallback" in output


# ── Empty / degenerate inputs ────────────────────────────────────


class TestDegenerateInputs:
    def test_empty_tools_list(self):
        cm = CodeMode(tools=[])
        output = cm.run_code("result = str(2 + 2)")
        assert "4" in output

    def test_empty_code_string(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("")
        assert output is not None

    def test_whitespace_only_code(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("   \n\n  ")
        assert output is not None


# ── Sandbox language features ────────────────────────────────────


class TestSandboxLanguageFeatures:
    def test_dict_comprehension(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = str({k: k**2 for k in range(3)})")
        assert "4" in output

    def test_lambda(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("square = lambda x: x**2\nresult = str(square(7))")
        assert "49" in output

    def test_nested_function(self):
        cm = CodeMode(tools=[search_items])
        code = "def double(x):\n    return x * 2\nresult = str(double(21))"
        output = cm.run_code(code)
        assert "42" in output

    def test_class_definition(self):
        cm = CodeMode(tools=[search_items])
        code = (
            "class Counter:\n"
            "    def __init__(self):\n"
            "        self.n = 0\n"
            "    def inc(self):\n"
            "        self.n += 1\n"
            "        return self.n\n"
            "c = Counter()\nc.inc()\nc.inc()\nresult = str(c.inc())"
        )
        output = cm.run_code(code)
        assert "3" in output

    def test_try_except(self):
        cm = CodeMode(tools=[search_items])
        code = "try:\n    x = 1 / 0\nexcept ZeroDivisionError:\n    result = 'caught'"
        output = cm.run_code(code)
        assert "caught" in output

    def test_generator_expression(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = str(sum(i for i in range(10)))")
        assert "45" in output

    def test_walrus_operator(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("result = str((n := 10) + n)")
        assert "20" in output

    def test_unpacking(self):
        cm = CodeMode(tools=[search_items])
        output = cm.run_code("a, b, *rest = [1, 2, 3, 4, 5]\nresult = str(rest)")
        assert "[3, 4, 5]" in output


# ── Extract code block edge cases ────────────────────────────────


class TestExtractCodeBlockEdgeCases:
    def test_multiple_blocks_takes_first(self):
        text = "Step 1:\n```python\nx = 1\n```\nStep 2:\n```python\nresult = x + 1\n```"
        code = CodeMode._extract_code_block(text)
        assert code == "x = 1"

    def test_empty_code_block(self):
        text = "```python\n```"
        code = CodeMode._extract_code_block(text)
        assert code == ""

    def test_no_fence_returns_raw(self):
        text = "x = 1\nresult = x + 1"
        code = CodeMode._extract_code_block(text)
        assert "x = 1" in code
        assert "result = x + 1" in code


# ── Discovery threshold boundary ─────────────────────────────────


class TestDiscoveryBoundary:
    def test_exactly_at_threshold(self):
        cm = CodeMode(tools=_make_many_callables(15), discovery_threshold=15)
        assert cm.discovery_enabled is False

    def test_one_above_threshold(self):
        cm = CodeMode(tools=_make_many_callables(16), discovery_threshold=15)
        assert cm.discovery_enabled is True

    def test_threshold_zero_always_enables(self):
        cm = CodeMode(tools=[search_items], discovery_threshold=0)
        assert cm.discovery_enabled is True

    def test_threshold_very_high(self):
        cm = CodeMode(tools=_make_many_callables(50), discovery_threshold=1000)
        assert cm.discovery_enabled is False


# ── Async direct execution (no code_model) ────────────────────────


class TestAsyncDirectExecution:
    @pytest.mark.asyncio
    async def test_arun_code_result_variable(self):
        cm = CodeMode(tools=[search_items])
        output = await cm.arun_code('result = "async direct"')
        assert output == "async direct"

    @pytest.mark.asyncio
    async def test_arun_code_calls_tools(self):
        cm = CodeMode(tools=[search_items])
        output = await cm.arun_code('data = json.loads(search_items(query="async"))\nresult = data[0]["name"]')
        assert "result for async" in output

    @pytest.mark.asyncio
    async def test_arun_code_chains_tools(self):
        cm = CodeMode(tools=[search_items, get_item_details])
        code = (
            'items = json.loads(search_items(query="chain"))\n'
            'details = json.loads(get_item_details(item_id=items[0]["id"]))\n'
            "result = f\"{details['name']} ${details['price']}\""
        )
        output = await cm.arun_code(code)
        assert "Widget" in output
        assert "9.99" in output

    @pytest.mark.asyncio
    async def test_arun_code_syntax_error(self):
        cm = CodeMode(tools=[search_items])
        output = await cm.arun_code("def broken(")
        assert "SyntaxError" in output

    @pytest.mark.asyncio
    async def test_arun_code_runtime_error(self):
        cm = CodeMode(tools=[search_items])
        output = await cm.arun_code("x = 1 / 0")
        assert "ZeroDivisionError" in output

    @pytest.mark.asyncio
    async def test_arun_code_print_captured(self):
        cm = CodeMode(tools=[search_items])
        output = await cm.arun_code('print("async print")')
        assert "async print" in output

    @pytest.mark.asyncio
    async def test_arun_code_loop_execution(self):
        cm = CodeMode(tools=[get_item_details])
        code = (
            "names = []\n"
            "for i in range(3):\n"
            "    data = json.loads(get_item_details(item_id=i))\n"
            '    names.append(data["name"])\n'
            'result = ", ".join(names)'
        )
        output = await cm.arun_code(code)
        assert "Widget" in output

    @pytest.mark.asyncio
    async def test_arun_code_with_async_tool(self):
        async def async_search(query: str) -> str:
            """Async search tool."""
            return json.dumps([{"id": 1, "name": f"async result for {query}"}])

        cm = CodeMode(tools=[async_search])
        output = await cm.arun_code('data = json.loads(async_search(query="test"))\nresult = data[0]["name"]')
        assert "async result for test" in output

    @pytest.mark.asyncio
    async def test_arun_code_media_returned(self):
        from agno.media import Image

        def image_tool(prompt: str) -> ToolResult:
            """Returns an image."""
            return ToolResult(
                content=f"Image for: {prompt}",
                images=[Image(url="https://example.com/img.png")],
            )

        cm = CodeMode(tools=[image_tool])
        output = await cm.arun_code('result = image_tool(prompt="sunset")')
        assert isinstance(output, ToolResult)
        assert "Image for: sunset" in output.content
        assert len(output.images) == 1

    @pytest.mark.asyncio
    async def test_arun_code_max_length_enforced(self):
        cm = CodeMode(tools=[search_items], max_code_length=10)
        output = await cm.arun_code("x = 1\n" * 100)
        assert "exceeds maximum length" in output


# ── Framework arg mapping completeness ────────────────────────────


def _tool_needing_team(query: str, team: Optional[object] = None) -> str:
    """Tool needing team reference."""
    return json.dumps({"query": query, "has_team": team is not None})


def _tool_needing_images(query: str, images: Optional[object] = None) -> str:
    """Tool needing images."""
    return json.dumps({"query": query, "has_images": images is not None})


def _tool_needing_videos(query: str, videos: Optional[object] = None) -> str:
    """Tool needing videos."""
    return json.dumps({"query": query, "has_videos": videos is not None})


def _tool_needing_audios(query: str, audios: Optional[object] = None) -> str:
    """Tool needing audios."""
    return json.dumps({"query": query, "has_audios": audios is not None})


def _tool_needing_files(query: str, files: Optional[object] = None) -> str:
    """Tool needing files."""
    return json.dumps({"query": query, "has_files": files is not None})


def _tool_needing_agent_and_team(query: str, agent: Optional[object] = None, team: Optional[object] = None) -> str:
    """Tool needing both agent and team."""
    return json.dumps({"query": query, "has_agent": agent is not None, "has_team": team is not None})


class TestFrameworkArgMappingComplete:
    """Verify all 7 FRAMEWORK_ARG_ATTRS entries are injected correctly."""

    def _inject_and_run(self, tool_fn, attr_name, code):
        from unittest.mock import Mock

        cm = CodeMode(tools=[tool_fn])
        run_code_func = cm.functions.get("run_code")
        if run_code_func:
            setattr(run_code_func, attr_name, Mock())
        return cm.run_code(code)

    def test_team_injected(self):
        output = self._inject_and_run(_tool_needing_team, "_team", 'result = _tool_needing_team(query="test")')
        data = json.loads(output)
        assert data["has_team"] is True

    def test_images_injected(self):
        output = self._inject_and_run(_tool_needing_images, "_images", 'result = _tool_needing_images(query="test")')
        data = json.loads(output)
        assert data["has_images"] is True

    def test_videos_injected(self):
        output = self._inject_and_run(_tool_needing_videos, "_videos", 'result = _tool_needing_videos(query="test")')
        data = json.loads(output)
        assert data["has_videos"] is True

    def test_audios_injected(self):
        output = self._inject_and_run(_tool_needing_audios, "_audios", 'result = _tool_needing_audios(query="test")')
        data = json.loads(output)
        assert data["has_audios"] is True

    def test_files_injected(self):
        output = self._inject_and_run(_tool_needing_files, "_files", 'result = _tool_needing_files(query="test")')
        data = json.loads(output)
        assert data["has_files"] is True

    def test_multiple_framework_args_simultaneously(self):
        from unittest.mock import Mock

        cm = CodeMode(tools=[_tool_needing_agent_and_team])
        run_code_func = cm.functions.get("run_code")
        if run_code_func:
            run_code_func._agent = Mock()
            run_code_func._team = Mock()
        output = cm.run_code('result = _tool_needing_agent_and_team(query="test")')
        data = json.loads(output)
        assert data["has_agent"] is True
        assert data["has_team"] is True

    def test_framework_params_excluded_from_stubs(self):
        cm = CodeMode(tools=[_tool_needing_agent_and_team])
        stub = cm.stub_map.get("_tool_needing_agent_and_team", "")
        sig_part = stub.split("(")[1].split(")")[0] if "(" in stub else ""
        assert "agent" not in sig_part
        assert "team" not in sig_part
        assert "query" in sig_part

    def test_no_injection_when_attr_not_set(self):
        cm = CodeMode(tools=[_tool_needing_team])
        # Don't set _team on run_code_func
        output = cm.run_code('result = _tool_needing_team(query="test")')
        data = json.loads(output)
        assert data["has_team"] is False


# ── Extracted helpers ─────────────────────────────────────────────


class TestBuildCodegenMessages:
    def test_basic_task(self):
        from unittest.mock import Mock

        mock_model = Mock()
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        messages = cm._build_codegen_messages("Find laptops")
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        assert "Find laptops" in messages[1].content
        assert "def search_items(" in messages[0].content

    def test_with_error_context(self):
        from unittest.mock import Mock

        mock_model = Mock()
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        messages = cm._build_codegen_messages("Find laptops", error="NameError: x not defined")
        user_content = messages[1].content
        assert "Find laptops" in user_content
        assert "Previous attempt failed" in user_content
        assert "NameError: x not defined" in user_content

    def test_system_includes_code_model_system_prefix(self):
        from unittest.mock import Mock

        mock_model = Mock()
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        messages = cm._build_codegen_messages("task")
        assert messages[0].content.startswith("You are a Python code generator")

    def test_no_error_no_previous_attempt(self):
        from unittest.mock import Mock

        mock_model = Mock()
        cm = CodeMode(tools=[search_items], code_model=mock_model)
        messages = cm._build_codegen_messages("task")
        assert "Previous attempt failed" not in messages[1].content


class TestUnwrapToolResult:
    def test_unwraps_tool_result(self):
        from agno.code_mode.sandbox import _unwrap_tool_result

        tr = ToolResult(content="hello")
        assert _unwrap_tool_result(tr, None) == "hello"

    def test_returns_none_for_non_tool_result(self):
        from agno.code_mode.sandbox import _unwrap_tool_result

        assert _unwrap_tool_result("just a string", None) is None
        assert _unwrap_tool_result(42, None) is None
        assert _unwrap_tool_result(None, None) is None

    def test_collects_media_when_collector_provided(self):
        from agno.code_mode.sandbox import _unwrap_tool_result
        from agno.media import Image

        collector = {"images": [], "videos": [], "audios": [], "files": []}
        tr = ToolResult(content="img", images=[Image(url="https://example.com/a.png")])
        result = _unwrap_tool_result(tr, collector)
        assert result == "img"
        assert len(collector["images"]) == 1

    def test_no_media_collection_without_collector(self):
        from agno.code_mode.sandbox import _unwrap_tool_result

        tr = ToolResult(content="no collector")
        result = _unwrap_tool_result(tr, None)
        assert result == "no collector"


class TestPrepareFunction:
    def test_returns_deep_copy(self):
        from agno.code_mode.stubs import _prepare_function

        original = Function.from_callable(search_items)
        prepared = _prepare_function(original)
        assert prepared is not original
        assert prepared.name == original.name

    def test_processes_entrypoint(self):
        from agno.code_mode.stubs import _prepare_function

        func = Function.from_callable(search_items)
        func.skip_entrypoint_processing = False
        prepared = _prepare_function(func)
        assert prepared.parameters is not None

    def test_skips_processing_when_flagged(self):
        from agno.code_mode.stubs import _prepare_function

        func = Function.from_callable(search_items)
        func.skip_entrypoint_processing = True
        # Should not raise even if entrypoint is already processed
        prepared = _prepare_function(func)
        assert prepared.name == "search_items"


class TestToolResultFallbackPath:
    """Verify extract_result handles ToolResult in the fallback (last user var) path."""

    def test_tool_result_in_last_var(self):
        from agno.media import Image

        def img_tool(prompt: str) -> ToolResult:
            """Returns image."""
            return ToolResult(
                content=f"Generated: {prompt}",
                images=[Image(url="https://example.com/img.png")],
            )

        cm = CodeMode(tools=[img_tool])
        # Store ToolResult in non-result variable — hits fallback path
        output = cm.run_code('x = img_tool(prompt="cat")')
        assert "Generated: cat" in (output.content if isinstance(output, ToolResult) else output)


# ── Regression tests for codex-review fixes ──────────────────────


class TestDescriptionIdempotent:
    def test_description_not_duplicated_after_multiple_calls(self):
        cm = CodeMode(tools=[search_items])
        funcs1 = cm.get_functions()
        desc1 = funcs1["run_code"].description
        funcs2 = cm.get_functions()
        desc2 = funcs2["run_code"].description
        assert desc1 == desc2
        assert desc2.count("def search_items(") == 1


class TestStubTripleQuoteEscape:
    def test_docstring_with_triple_quotes(self):
        def tool_with_quotes(x: str) -> str:
            '''Returns """triple quoted""" text.'''
            return x

        cm = CodeMode(tools=[tool_with_quotes])
        stub = cm.stub_map.get("tool_with_quotes", "")
        assert '"""' not in stub.split("\n", 1)[1] or "'''" in stub


class TestToolNameShadowingWarning:
    def test_tool_named_json_warns(self, capsys):
        def json(query: str) -> str:
            """A badly named tool."""
            return query

        cm = CodeMode(tools=[json])
        cm.run_code('result = "test"')

        captured = capsys.readouterr()
        assert "shadows" in captured.out


class TestClassConstants:
    """Verify class-level constants are accessible and correct."""

    def test_framework_params_includes_all(self):
        expected = {"self", "fc", "agent", "team", "run_context", "images", "videos", "audios", "files"}
        assert FRAMEWORK_PARAMS == frozenset(expected)

    def test_framework_arg_attrs_keys_subset_of_params(self):
        for key in FRAMEWORK_ARG_ATTRS:
            assert key in FRAMEWORK_PARAMS

    def test_blocked_modules_is_frozenset(self):
        assert isinstance(CodeMode.BLOCKED_MODULES, frozenset)
        assert "os" in CodeMode.BLOCKED_MODULES
        assert "json" not in CodeMode.BLOCKED_MODULES

    def test_preapproved_modules_are_real_modules(self):
        import collections as col_mod
        import datetime as dt_mod
        import json as json_mod
        import math as math_mod
        import re as re_mod

        assert CodeMode.PREAPPROVED_MODULES["json"] is json_mod
        assert CodeMode.PREAPPROVED_MODULES["math"] is math_mod
        assert CodeMode.PREAPPROVED_MODULES["datetime"] is dt_mod
        assert CodeMode.PREAPPROVED_MODULES["re"] is re_mod
        assert CodeMode.PREAPPROVED_MODULES["collections"] is col_mod

    def test_exec_error_prefix_format(self):
        assert CodeMode.EXEC_ERROR_PREFIX.startswith("[[")
        assert CodeMode.EXEC_ERROR_PREFIX.endswith(" ")

    def test_constants_accessible_from_instance(self):
        cm = CodeMode(tools=[search_items])
        assert cm.BLOCKED_MODULES is CodeMode.BLOCKED_MODULES
