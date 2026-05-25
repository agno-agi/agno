import json
"""Tests for FileGenerationTools security and edge-case handling."""

import os
import tempfile
from pathlib import Path

import pytest

from agno.tools.file_generation import DOCX_AVAILABLE, PDF_AVAILABLE, FileGenerationTools


def _get_single_file(result):
    assert result.files
    assert len(result.files) == 1
    return result.files[0]


def test_generate_json_file_from_dict():
    """Test JSON file generation from dict input."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = FileGenerationTools(output_directory=tmp_dir)
        result = tools.generate_json_file({"name": "Ada", "role": "Engineer"}, filename="employee")

        file_artifact = _get_single_file(result)
        assert file_artifact.filename == "employee.json"
        assert file_artifact.mime_type == "application/json"
        assert file_artifact.file_type == "json"
        assert file_artifact.filepath is not None

        saved_path = Path(file_artifact.filepath)
        assert saved_path.exists()
        saved_data = json.loads(saved_path.read_text(encoding="utf-8"))
        assert saved_data == {"name": "Ada", "role": "Engineer"}


def test_generate_json_file_from_invalid_json_string():
    """Test JSON file generation when provided invalid JSON string."""
    tools = FileGenerationTools()
    result = tools.generate_json_file("not-json", filename="payload")

    file_artifact = _get_single_file(result)
    assert file_artifact.filename == "payload.json"
    assert file_artifact.mime_type == "application/json"
    decoded = json.loads(file_artifact.content.decode("utf-8"))
    assert decoded == {"content": "not-json"}


def test_generate_csv_file_from_dicts():
    """Test CSV generation from list of dicts."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = FileGenerationTools(output_directory=tmp_dir)
        result = tools.generate_csv_file(
            [
                {"name": "Ava", "score": 10},
                {"name": "Ben", "score": 12},
            ],
            filename="scores",
        )

        file_artifact = _get_single_file(result)
        assert file_artifact.filename == "scores.csv"
        assert file_artifact.mime_type == "text/csv"
        assert file_artifact.file_type == "csv"
        assert file_artifact.filepath is not None

        saved_path = Path(file_artifact.filepath)
        assert saved_path.exists()
        lines = saved_path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "name,score"
        assert "Ava,10" in lines
        assert "Ben,12" in lines


def test_generate_csv_file_from_lists_with_headers():
    """Test CSV generation from list of lists with headers."""
    tools = FileGenerationTools()
    result = tools.generate_csv_file([["Jan", 100], ["Feb", 200]], headers=["month", "sales"])

    file_artifact = _get_single_file(result)
    assert file_artifact.filename.endswith(".csv")
    decoded = file_artifact.content.decode("utf-8")
    assert "month,sales" in decoded
    assert "Jan,100" in decoded
    assert "Feb,200" in decoded


def test_generate_text_file():
    """Test text file generation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = FileGenerationTools(output_directory=tmp_dir)
        result = tools.generate_text_file("Hello there", filename="note")

        file_artifact = _get_single_file(result)
        assert file_artifact.filename == "note.txt"
        assert file_artifact.mime_type == "text/plain"
        assert file_artifact.file_type == "txt"
        assert file_artifact.content.decode("utf-8") == "Hello there"

        saved_path = Path(file_artifact.filepath)
        assert saved_path.exists()
        assert saved_path.read_text(encoding="utf-8") == "Hello there"


def test_generate_pdf_file_when_unavailable():
    """Test PDF generation returns install message when reportlab is missing."""
    if PDF_AVAILABLE:
        pytest.skip("reportlab is installed")

    tools = FileGenerationTools()
    result = tools.generate_pdf_file("Body")
    assert result.content == "PDF generation is not available. Please install reportlab: pip install reportlab"


def test_generate_pdf_file_success():
    """Test PDF generation when reportlab is available."""
    if not PDF_AVAILABLE:
        pytest.skip("reportlab not installed")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = FileGenerationTools(output_directory=tmp_dir)
        result = tools.generate_pdf_file("Heading\n\nBody", filename="report", title="Report")

        file_artifact = _get_single_file(result)
        assert file_artifact.filename == "report.pdf"
        assert file_artifact.mime_type == "application/pdf"
        assert file_artifact.file_type == "pdf"
        assert file_artifact.content[:4] == b"%PDF"
        assert Path(file_artifact.filepath).exists()


def test_generate_docx_file_when_unavailable():
    """Test DOCX generation returns install message when python-docx is missing."""
    if DOCX_AVAILABLE:
        pytest.skip("python-docx is installed")

    tools = FileGenerationTools()
    result = tools.generate_docx_file("Body")
    assert result.content == "DOCX generation is not available. Please install python-docx: pip install python-docx"


def test_generate_docx_file_success():
    """Test DOCX generation when python-docx is available."""
    if not DOCX_AVAILABLE:
        pytest.skip("python-docx not installed")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = FileGenerationTools(output_directory=tmp_dir)
        result = tools.generate_docx_file("Intro\n\nDetails", filename="report", title="Report")

        file_artifact = _get_single_file(result)
        assert file_artifact.filename == "report.docx"
        assert file_artifact.mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert file_artifact.file_type == "docx"
        assert file_artifact.content[:2] == b"PK"
        assert Path(file_artifact.filepath).exists()


def test_relative_traversal_blocked():
    """Relative-traversal filenames must be stripped to bare filename."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        tool._save_file_to_disk("payload", "../../../escape.json")
        assert (Path(tmp_dir) / "escape.json").exists()
        assert not (Path(tmp_dir).parent / "escape.json").exists()


def test_absolute_path_blocked():
    """Absolute-path filenames must be stripped to bare filename."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        tool._save_file_to_disk("payload", "/tmp/test_absolute_xyz_unique.json")
        assert (Path(tmp_dir) / "test_absolute_xyz_unique.json").exists()
        assert not Path("/tmp/test_absolute_xyz_unique.json").exists()


def test_nested_path_stripped():
    """Nested-path filenames must be flattened to the bare filename."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        tool._save_file_to_disk("payload", "subdir/file.json")
        assert (Path(tmp_dir) / "file.json").exists()
        assert not (Path(tmp_dir) / "subdir").exists()


def test_normal_filename_unchanged():
    """Normal filenames should pass through unchanged."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        tool._save_file_to_disk("payload", "report.json")
        assert (Path(tmp_dir) / "report.json").exists()


def test_filename_with_dots_in_name():
    """Filenames with dots in the middle are valid and must be preserved intact."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        tool._save_file_to_disk("payload", "q1.report.json")
        assert (Path(tmp_dir) / "q1.report.json").exists()


def test_empty_filename_returns_error():
    """Empty filename must return error in tuple."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        path, error = tool._save_file_to_disk("payload", "")
        assert path is None
        assert error is not None
        assert "Invalid filename" in error


def test_dot_filename_returns_error():
    """Filename '.' must return error in tuple."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        path, error = tool._save_file_to_disk("payload", ".")
        assert path is None
        assert error is not None
        assert "Invalid filename" in error


def test_dotdot_filename_returns_error():
    """Filename '..' must return error in tuple."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        path, error = tool._save_file_to_disk("payload", "..")
        assert path is None
        assert error is not None
        assert "Invalid filename" in error


def test_only_traversal_returns_error():
    """Filename '../' (path-only) must return error in tuple."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        path, error = tool._save_file_to_disk("payload", "../")
        assert path is None
        assert error is not None
        assert "Invalid filename" in error


def test_symlink_pointing_outside_returns_error():
    """Symlink within output_directory pointing outside must return error."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        outside_dir = Path(tmp_dir) / "outside"
        outside_dir.mkdir()
        inside_dir = Path(tmp_dir) / "inside"
        inside_dir.mkdir()
        try:
            (inside_dir / "escape").symlink_to(outside_dir)
        except OSError:
            pytest.skip("Symlink creation not permitted on this platform")

        tool = FileGenerationTools(output_directory=str(inside_dir), save_files=True)
        path, error = tool._save_file_to_disk("payload", "escape")
        assert path is None
        assert error is not None
        assert "resolves outside" in error


def test_default_output_directory_saves_to_cwd():
    """When save_files=True and output_directory is not set, files save to cwd()."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_dir)
            tool = FileGenerationTools(save_files=True)
            result = tool.generate_json_file({"x": 1}, filename="report.json")
            assert result.files is not None
            assert result.files[0].filepath is not None
            assert Path(result.files[0].filepath).exists()
            assert Path(result.files[0].filepath).parent.resolve() == Path(tmp_dir).resolve()
        finally:
            os.chdir(original_cwd)


def test_control_char_filename_returns_error():
    """Filenames containing control characters must return error in tuple."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        path, error = tool._save_file_to_disk("payload", "report\nhacked.json")
        assert path is None
        assert error is not None
        assert "Invalid" in error


def test_whitespace_only_filename_returns_error():
    """Whitespace-only filenames must return error in tuple."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        path, error = tool._save_file_to_disk("payload", "   ")
        assert path is None
        assert error is not None
        assert "Invalid filename" in error


def test_trailing_dot_space_trimmed():
    """Trailing dots and spaces in the filename must be stripped."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        path, error = tool._save_file_to_disk("payload", "report.json. ")
        assert error is None
        assert (Path(tmp_dir) / "report.json").exists()


def test_generate_json_file_traversal_via_public_api():
    """Public-API integration: traversal via generate_json_file lands safely inside output_directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        tool.generate_json_file({"x": 1}, filename="../../../escape")
        assert (Path(tmp_dir) / "escape.json").exists()
        assert not (Path(tmp_dir).parent / "escape.json").exists()


def test_generate_csv_file_control_char_returns_error():
    """Public-API integration: control char in filename produces an error ToolResult (caught by except Exception)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        result = tool.generate_csv_file([{"a": 1}], filename="\n")
        assert "Error" in result.content


def test_pure_dot_filename_returns_error():
    """Filename '...' must return error after rstrip('. ')."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        path, error = tool._save_file_to_disk("payload", "...")
        assert path is None
        assert error is not None
        assert "Invalid filename" in error


def test_url_encoded_traversal_sanitized_inside_output_directory():
    """URL-encoded traversal ('%2e%2e/...') is sanitized inside output_directory.

    Note: ``%2e%2e`` is NOT decoded by pathlib — it's a literal segment.
    ``Path(filename).name`` therefore takes ``escape``, and the file lands
    inside ``output_directory`` instead of escaping it. The original test
    name (``..._rejected``) was misleading because the input is sanitized,
    not rejected (no PathSecurityError raised).
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        tool._save_file_to_disk("payload", "%2e%2e/escape")
        assert (Path(tmp_dir) / "escape").exists()
        assert not (Path(tmp_dir).parent / "escape").exists()


def test_filename_sanitized_in_artifact_traversal():
    """Test that File.filename reflects the sanitized basename, not the original input."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        result = tool.generate_json_file({"x": 1}, filename="../../../escape")
        assert result.files is not None
        artifact = result.files[0]
        # Single source of truth: filename matches the basename of filepath.
        assert artifact.filename == "escape.json"
        assert artifact.filepath is not None
        assert Path(artifact.filepath).name == artifact.filename


def test_filename_sanitized_with_default_output_directory():
    """Test that File.filename is sanitized and file is saved to cwd when save_files=True."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_dir)
            tool = FileGenerationTools(save_files=True)
            result = tool.generate_json_file({"x": 1}, filename="subdir/report.json")
            assert result.files is not None
            artifact = result.files[0]
            assert artifact.filename == "report.json"
            assert artifact.filepath is not None
            assert Path(artifact.filepath).name == "report.json"
        finally:
            os.chdir(original_cwd)


@pytest.mark.parametrize(
    "evil",
    [
        "report\r\nFAKE.json",
        "report\x00.json",
        "CON",
        "C:\\Windows\\evil.json",
        "\\\\server\\share\\evil",
    ],
)
def test_no_output_directory_rejects_dangerous_filename(evil):
    """No-output-directory branch must apply the same rules as the disk branch."""
    tool = FileGenerationTools()
    result = tool.generate_json_file({"x": 1}, filename=evil)
    # Wrapped in `except Exception` by the public method — surfaces as error content.
    assert "Error" in result.content
    assert result.files is None


def test_filename_sanitized_subdir_collapsed():
    """File.filename matches the on-disk basename when subdir is stripped."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tool = FileGenerationTools(output_directory=tmp_dir, save_files=True)
        result = tool.generate_json_file({"x": 1}, filename="subdir/report.json")
        assert result.files is not None
        artifact = result.files[0]
        assert artifact.filename == "report.json"
        assert artifact.filepath is not None
        assert Path(artifact.filepath).name == "report.json"
