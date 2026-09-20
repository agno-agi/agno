"""Unit tests for agno.utils.code_execution.prepare_python_code."""

import json

from agno.utils.code_execution import prepare_python_code


def test_rewrites_bare_lowercase_constants():
    assert prepare_python_code("x = true") == "x = True"
    assert prepare_python_code("y = [true, false, none]") == "y = [True, False, None]"
    assert prepare_python_code("if true:\n    z = none") == "if True:\n    z = None"


def test_keeps_keywords_inside_string_literals():
    # A literal is data: rewriting its contents changes what the program says.
    assert prepare_python_code('print("Result is true")') == 'print("Result is true")'
    assert prepare_python_code("print('Result is true')") == "print('Result is true')"
    assert prepare_python_code('msg = """set to none if missing"""') == 'msg = """set to none if missing"""'
    assert prepare_python_code("msg = '''set to none if missing'''") == "msg = '''set to none if missing'''"


def test_keeps_escaped_quote_inside_literal():
    code = r'''msg = "he said \"true\" loudly"'''
    assert prepare_python_code(code) == code
    compile(code, "<generated>", "exec")


def test_keeps_query_string_literal():
    code = 'url = "https://api.test/x?flag=true"'
    assert prepare_python_code(code) == code


def test_json_payload_stays_parseable():
    payload = '{"ok": true, "note": "none"}'
    code = "data = json.loads('''" + payload + "''')"
    assert prepare_python_code(code) == code
    assert json.loads(payload) == {"ok": True, "note": "none"}


def test_keeps_keywords_inside_comments():
    assert prepare_python_code("# keep true here\nx = true") == "# keep true here\nx = True"
    assert prepare_python_code("x = true  # true in comment") == "x = True  # true in comment"
    assert prepare_python_code("log.info('# none of this')") == "log.info('# none of this')"


def test_leaves_identifiers_alone():
    assert prepare_python_code("true_count = 1") == "true_count = 1"
    assert prepare_python_code("is_true = none if none else true") == "is_true = None if None else True"


def test_string_prefixes_are_still_literals():
    assert prepare_python_code('text = f"{x} true"\nb = true') == 'text = f"{x} true"\nb = True'
    assert prepare_python_code('blob = rb"raw true"\nx = none') == 'blob = rb"raw true"\nx = None'


def test_apostrophe_in_a_literal_does_not_leak():
    assert prepare_python_code('label = "it\'s" + true') == 'label = "it\'s" + True'


def test_still_fixes_code_after_an_unterminated_literal():
    # A dangling quote cannot be tokenised, so the rest is treated as code.
    assert prepare_python_code('s = "unterminated\nx = true') == 's = "unterminated\nx = True'
