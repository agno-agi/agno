from typing import List, Optional

from pydantic import BaseModel

from agno.utils.string import parse_response_model_str, url_safe_string


def test_url_safe_string_spaces():
    """Test conversion of spaces to dashes"""
    assert url_safe_string("hello world") == "hello-world"


def test_url_safe_string_camel_case():
    """Test conversion of camelCase to kebab-case"""
    assert url_safe_string("helloWorld") == "hello-world"


def test_url_safe_string_snake_case():
    """Test conversion of snake_case to kebab-case"""
    assert url_safe_string("hello_world") == "hello-world"


def test_url_safe_string_special_chars():
    """Test removal of special characters"""
    assert url_safe_string("hello@world!") == "helloworld"


def test_url_safe_string_consecutive_dashes():
    """Test handling of consecutive dashes"""
    assert url_safe_string("hello--world") == "hello-world"


def test_url_safe_string_mixed_cases():
    """Test a mix of different cases and separators"""
    assert url_safe_string("hello_World Test") == "hello-world-test"


def test_url_safe_string_preserve_dots():
    """Test preservation of dots"""
    assert url_safe_string("hello.world") == "hello.world"


def test_url_safe_string_complex():
    """Test a complex string with multiple transformations"""
    assert (
        url_safe_string("Hello World_Example-String.With@Special#Chars")
        == "hello-world-example-string.withspecialchars"
    )


class MockModel(BaseModel):
    name: str
    value: Optional[str] = None
    description: Optional[str] = None


def test_parse_direct_json():
    """Test parsing a clean JSON string directly"""
    content = '{"name": "test", "value": "123"}'
    result = parse_response_model_str(content, MockModel)
    assert result is not None
    assert result.name == "test"
    assert result.value == "123"


def test_parse_json_with_markdown_block():
    """Test parsing JSON from a markdown code block"""
    content = """Some text before
    ```json
    {
        "name": "test",
        "value": "123"
    }
    ```
    Some text after"""
    result = parse_response_model_str(content, MockModel)
    assert result is not None
    assert result.name == "test"
    assert result.value == "123"


def test_parse_json_with_generic_code_block():
    """Test parsing JSON from a generic markdown code block"""
    content = """Some text before
    ```
    {
        "name": "test",
        "value": "123"
    }
    ```
    Some text after"""
    result = parse_response_model_str(content, MockModel)
    assert result is not None
    assert result.name == "test"
    assert result.value == "123"


def test_parse_json_with_control_characters():
    """Test parsing JSON with control characters"""
    content = '{\n\t"name": "test",\r\n\t"value": "123"\n}'
    result = parse_response_model_str(content, MockModel)
    assert result is not None
    assert result.name == "test"
    assert result.value == "123"


def test_parse_json_with_markdown_formatting():
    """Test parsing JSON with markdown formatting"""
    content = '{*"name"*: "test", `"value"`: "123"}'
    result = parse_response_model_str(content, MockModel)
    assert result is not None
    assert result.name == "test"
    assert result.value == "123"


def test_parse_json_with_quotes_in_values():
    """Test parsing JSON with quotes in values"""
    content = '{"name": "test "quoted" text", "value": "some "quoted" value"}'
    result = parse_response_model_str(content, MockModel)
    assert result is not None
    assert result.name == 'test "quoted" text'
    assert result.value == 'some "quoted" value'


def test_parse_json_with_missing_required_field():
    """Test parsing JSON with missing required field"""
    content = '{"value": "123"}'  # Missing required 'name' field
    result = parse_response_model_str(content, MockModel)
    assert result is None


def test_parse_invalid_json():
    """Test parsing invalid JSON"""
    content = '{"name": "test", value: "123"}'  # Missing quotes around value
    result = parse_response_model_str(content, MockModel)
    assert result is None


def test_parse_empty_string():
    """Test parsing empty string"""
    content = ""
    result = parse_response_model_str(content, MockModel)
    assert result is None


def test_parse_non_json_string():
    """Test parsing non-JSON string"""
    content = "Just some regular text"
    result = parse_response_model_str(content, MockModel)
    assert result is None


def test_parse_json_with_code_blocks_in_fields():
    """Test parsing JSON with code blocks in field values"""
    content = """
    ```json
    {
        "name": "test",
        "value": "```python
    def hello():
        print('Hello, world!')
    ```",
        "description": "A function that prints hello"
    }
    ```
    """
    result = parse_response_model_str(content, MockModel)
    assert result is not None
    assert result.name == "test"
    assert "def hello()" in result.value
    assert "print('Hello, world!')" in result.value
    assert result.description == "A function that prints hello"


def test_parse_complex_markdown():
    """Test parsing JSON embedded in complex markdown"""
    content = """# Title
    Here's some text with *formatting* and a code block:

    ```json
    {
        "name": "test",
        "value": "123",
        "description": "A \"quoted\" description"
    }
    ```

    And some more text after."""
    result = parse_response_model_str(content, MockModel)
    assert result is not None
    assert result.name == "test"
    assert result.value == "123"
    assert result.description == 'A "quoted" description'


def test_parse_nested_json():
    """Test parsing nested JSON"""

    class Step(BaseModel):
        step: str
        description: str

    class Steps(BaseModel):
        steps: List[Step]

    content = """
    ```json
    {
        "steps": [
            {
                "step": "1",
                "description": "Step 1 description"
            },
            {
                "step": "2",
                "description": "Step 2 description"
            }
        ]
    }
    ```"""
    result = parse_response_model_str(content, Steps)
    assert result is not None
    assert result.steps[0].step == "1"
    assert result.steps[0].description == "Step 1 description"
    assert result.steps[1].step == "2"
    assert result.steps[1].description == "Step 2 description"
