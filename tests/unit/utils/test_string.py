from agno.utils.string import extract_valid_json


def test_extract_valid_json_with_valid_json():
    content = 'Here is some text {"key": "value"} and more text.'
    expected_json = {"key": "value"}
    extracted_json = extract_valid_json(content)
    assert extracted_json == expected_json


def test_extract_valid_json_with_nested_json():
    content = 'Start {"key": {"nested_key": "nested_value"}} End'
    expected_json = {"key": {"nested_key": "nested_value"}}
    extracted_json = extract_valid_json(content)
    assert extracted_json == expected_json


def test_extract_valid_json_with_multiple_json_objects():
    content = 'First {"key1": "value1"} Second {"key2": "value2"}'
    expected_json = {"key1": "value1"}  # Only the first JSON should be returned
    extracted_json = extract_valid_json(content)
    assert extracted_json == expected_json


def test_extract_valid_json_with_no_json():
    content = "This is a string without JSON."
    extracted_json = extract_valid_json(content)
    assert extracted_json is None


def test_extract_valid_json_with_invalid_json():
    content = "This string contains {invalid JSON}."
    extracted_json = extract_valid_json(content)
    assert extracted_json is None


def test_extract_valid_json_with_json_array():
    content = 'Here is a JSON array: ["item1", "item2"].'
    extracted_json = extract_valid_json(content)
    assert extracted_json is None  # Only JSON objects are extracted


def test_extract_valid_json_with_empty_json():
    content = "Some text {} more text."
    expected_json = {}
    extracted_json = extract_valid_json(content)
    assert extracted_json == expected_json


def test_extract_valid_json_with_multiline_json():
    content = """
    Here is some text {
        "key": "value",
        "another_key": "another_value"
    } and more text.
    """
    expected_json = {"key": "value", "another_key": "another_value"}
    extracted_json = extract_valid_json(content)
    assert extracted_json == expected_json


def test_extract_valid_json_with_json_in_quotes():
    content = 'Text before "{\\"key\\": \\"value\\"}" text after.'
    extracted_json = extract_valid_json(content)
    assert extracted_json is None  # JSON inside quotes should not be parsed
