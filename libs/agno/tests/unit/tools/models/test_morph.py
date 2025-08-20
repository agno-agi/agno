from unittest.mock import MagicMock, mock_open, patch

import pytest

from agno.tools.models.morph import MorphTools


# Fixture for mock OpenAI client
@pytest.fixture
def mock_openai_client():
    client = MagicMock()
    return client


# Fixture for mock MorphTools with mock client
@pytest.fixture
def mock_morph_tools(mock_openai_client):
    with patch("agno.tools.models.morph.OpenAI", return_value=mock_openai_client) as _:
        morph_tools = MorphTools(api_key="fake_test_key")
        morph_tools._morph_client = mock_openai_client
        return morph_tools


# Fixture for successful API response
@pytest.fixture
def mock_successful_response():
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = """def add(a: int, b: int) -> int:
    \"\"\"Add two numbers together.\"\"\"
    return a + b

def multiply(x: int, y: int) -> int:
    \"\"\"Multiply two numbers.\"\"\"
    result = x * y
    return result"""
    mock_response.choices = [mock_choice]
    return mock_response


# Fixture for failed API response (no content)
@pytest.fixture
def mock_failed_response():
    mock_response = MagicMock()
    mock_response.choices = []
    return mock_response


# Test Initialization
def test_morph_tools_init_with_api_key_arg():
    """Test initialization with API key provided as an argument."""
    api_key = "test_api_key_arg"

    with patch("agno.tools.models.morph.OpenAI") as mock_openai_cls:
        mock_client_instance = MagicMock()
        mock_openai_cls.return_value = mock_client_instance

        morph_tools = MorphTools(api_key=api_key)

        assert morph_tools.api_key == api_key
        assert morph_tools.base_url == "https://api.morphllm.com/v1"
        assert morph_tools.model == "morph-v3-large"
        assert morph_tools._morph_client is None  # Client created lazily


def test_morph_tools_init_with_env_var():
    """Test initialization with API key from environment variable."""
    env_api_key = "test_api_key_env"

    with patch("agno.tools.models.morph.getenv", return_value=env_api_key) as mock_getenv:
        morph_tools = MorphTools()

        assert morph_tools.api_key == env_api_key
        mock_getenv.assert_called_once_with("MORPH_API_KEY")


def test_morph_tools_init_no_api_key():
    """Test initialization raises ValueError when no API key is found."""
    with patch("agno.tools.models.morph.getenv", return_value=None) as mock_getenv:
        with pytest.raises(ValueError, match="MORPH_API_KEY not set"):
            MorphTools()

        mock_getenv.assert_called_once_with("MORPH_API_KEY")


# Test edit_file method - Success cases
def test_edit_file_success_with_file_reading(mock_morph_tools, mock_successful_response):
    """Test successful file editing when reading from existing file."""
    target_file = "test_file.py"
    original_content = "def add(a, b):\n    return a + b"
    instructions = "I am adding type hints to the function"
    code_edit = "def add(a: int, b: int) -> int:\n    return a + b"

    mock_morph_tools._morph_client.chat.completions.create.return_value = mock_successful_response

    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=original_content)) as mock_file:
            result = mock_morph_tools.edit_file(target_file=target_file, instructions=instructions, code_edit=code_edit)

    # Verify file operations
    mock_file.assert_any_call(target_file, "r", encoding="utf-8")
    mock_file.assert_any_call(f"{target_file}.backup", "w", encoding="utf-8")
    mock_file.assert_any_call(target_file, "w", encoding="utf-8")

    # Verify API call
    expected_content = (
        f"<instruction>{instructions}</instruction>\n<code>{original_content}</code>\n<update>{code_edit}</update>"
    )
    mock_morph_tools._morph_client.chat.completions.create.assert_called_once_with(
        model="morph-v3-large", messages=[{"role": "user", "content": expected_content}]
    )

    assert "Successfully applied edit" in result
    assert "backup" in result


def test_edit_file_success_with_provided_original_code(mock_morph_tools, mock_successful_response):
    """Test successful file editing when original code is provided."""
    target_file = "test_file.py"
    file_content = "def old_function():\n    pass"
    provided_original = "def add(a, b):\n    return a + b"
    instructions = "I am adding type hints to the function"
    code_edit = "def add(a: int, b: int) -> int:\n    return a + b"

    mock_morph_tools._morph_client.chat.completions.create.return_value = mock_successful_response

    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=file_content)) as mock_file:
            result = mock_morph_tools.edit_file(
                target_file=target_file, instructions=instructions, code_edit=code_edit, original_code=provided_original
            )

    # Verify API call uses provided original code
    expected_content = (
        f"<instruction>{instructions}</instruction>\n<code>{provided_original}</code>\n<update>{code_edit}</update>"
    )
    mock_morph_tools._morph_client.chat.completions.create.assert_called_once_with(
        model="morph-v3-large", messages=[{"role": "user", "content": expected_content}]
    )

    # Verify backup uses actual file content, not provided original
    handle = mock_file()
    backup_write_calls = [call for call in handle.write.call_args_list if call[0][0] == file_content]
    assert len(backup_write_calls) == 1

    assert "Successfully applied edit" in result


def test_edit_file_no_response_content(mock_morph_tools, mock_failed_response):
    """Test edit_file when API returns no content."""
    target_file = "test_file.py"
    original_content = "def test(): pass"

    mock_morph_tools._morph_client.chat.completions.create.return_value = mock_failed_response

    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=original_content)):
            result = mock_morph_tools.edit_file(
                target_file=target_file, instructions="test instruction", code_edit="test edit"
            )

    assert f"Failed to apply edit to {target_file}: No response from Morph API" in result


def test_edit_file_write_error(mock_morph_tools, mock_successful_response):
    """Test edit_file when writing back to file fails."""
    target_file = "test_file.py"
    original_content = "def test(): pass"
    write_error = "Disk full"

    mock_morph_tools._morph_client.chat.completions.create.return_value = mock_successful_response

    def mock_open_side_effect(file_path, mode, **kwargs):
        if mode == "r":
            return mock_open(read_data=original_content)()
        elif file_path.endswith(".backup"):
            return mock_open()()
        else:  # Writing to target file
            raise Exception(write_error)

    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", side_effect=mock_open_side_effect):
            result = mock_morph_tools.edit_file(
                target_file=target_file, instructions="test instruction", code_edit="test edit"
            )

    assert f"Successfully applied edit but failed to write back to {target_file}: {write_error}" in result


# Test edge cases
def test_edit_file_empty_original_code(mock_morph_tools, mock_successful_response):
    """Test edit_file with empty original code."""
    target_file = "empty_file.py"
    original_content = ""

    mock_morph_tools._morph_client.chat.completions.create.return_value = mock_successful_response

    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=original_content)):
            result = mock_morph_tools.edit_file(
                target_file=target_file, instructions="I am adding a new function", code_edit="def new_function(): pass"
            )

    assert "Successfully applied edit" in result


# Test toolkit structure
def test_morph_tools_toolkit_structure():
    """Test that MorphTools properly inherits from Toolkit and has correct structure."""
    morph_tools = MorphTools(api_key="test_key")

    assert morph_tools.name == "morph_tools"
    assert len(morph_tools.tools) == 1
    assert morph_tools.tools[0] == morph_tools.edit_file
    assert hasattr(morph_tools, "edit_file")
    assert callable(morph_tools.edit_file)


# Test method signature matches current implementation
def test_edit_file_method_signature():
    """Test that edit_file method has the correct signature."""
    import inspect

    morph_tools = MorphTools(api_key="test_key")
    sig = inspect.signature(morph_tools.edit_file)

    expected_params = ["target_file", "instructions", "code_edit", "original_code"]
    actual_params = list(sig.parameters.keys())

    assert actual_params == expected_params

    # Check that original_code has default None
    assert sig.parameters["original_code"].default is None


def test_edit_file_always_writes_to_file(mock_morph_tools, mock_successful_response):
    """Test that edit_file always writes to file in current implementation."""
    target_file = "test_file.py"
    original_content = "def test(): pass"

    mock_morph_tools._morph_client.chat.completions.create.return_value = mock_successful_response

    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=original_content)) as mock_file:
            result = mock_morph_tools.edit_file(
                target_file=target_file, instructions="test instruction", code_edit="test edit"
            )

    # Verify that backup file was created (indicates file writing occurred)
    mock_file.assert_any_call(f"{target_file}.backup", "w", encoding="utf-8")
    # Verify that original file was written to
    mock_file.assert_any_call(target_file, "w", encoding="utf-8")

    assert "Successfully applied edit" in result
    assert "backup" in result
