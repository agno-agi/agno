"""Tests for FileGenerationTools security and edge-case handling."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

import pytest

from agno.tools import file_generation as file_generation_module
from agno.tools.file_generation import DOCX_AVAILABLE, PDF_AVAILABLE, FileGenerationTools


def _get_single_file(result):
    assert result.files
    assert len(result.files) == 1
    return result.files[0]


class FakeS3Client:
    def __init__(self, presigned_url: Optional[str] = None, presign_error: Optional[Exception] = None):
        self.presigned_url = presigned_url
        self.presign_error = presign_error
        self.put_object_calls = []
        self.generate_presigned_url_calls = []

    def put_object(self, **kwargs: Any):
        self.put_object_calls.append(kwargs)

    def generate_presigned_url(self, client_method: str, **kwargs: Any):
        self.generate_presigned_url_calls.append({"client_method": client_method, **kwargs})
        if self.presign_error:
            raise self.presign_error
        return self.presigned_url


class FakeBoto3:
    def __init__(self, s3_client: FakeS3Client):
        self.s3_client = s3_client
        self.client_calls = []

    def client(self, service_name: str, **kwargs: Any):
        self.client_calls.append({"service_name": service_name, **kwargs})
        return self.s3_client


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


def test_s3_upload_sets_presigned_url_on_file_artifact(monkeypatch):
    """S3-backed generated files should expose a browser-renderable HTTPS URL."""
    s3_client = FakeS3Client(presigned_url="https://signed.example.com/generated/page.html?expires=900")
    fake_boto3 = FakeBoto3(s3_client)
    monkeypatch.setattr(file_generation_module, "BOTO3_AVAILABLE", True)
    monkeypatch.setattr(file_generation_module, "boto3", fake_boto3, raising=False)

    tools = FileGenerationTools(
        s3_bucket="render-bucket",
        s3_prefix="generated",
        region_name="us-west-2",
        s3_presigned_url_expires_in=900,
    )
    result = tools.generate_html_file("<h1>Hello</h1>", filename="page")

    file_artifact = _get_single_file(result)
    assert file_artifact.filename == "page.html"
    assert file_artifact.url == "https://signed.example.com/generated/page.html?expires=900"
    assert file_artifact.content == b"<h1>Hello</h1>"
    assert file_artifact.mime_type == "text/html"
    assert file_artifact.file_type == "html"
    assert file_artifact.filepath is None
    assert "uploaded to s3://render-bucket/generated/page.html" in result.content
    assert "render URL available" in result.content

    assert s3_client.put_object_calls == [
        {
            "Bucket": "render-bucket",
            "Key": "generated/page.html",
            "Body": b"<h1>Hello</h1>",
            "ContentType": "text/html",
        }
    ]
    assert s3_client.generate_presigned_url_calls == [
        {
            "client_method": "get_object",
            "Params": {"Bucket": "render-bucket", "Key": "generated/page.html"},
            "ExpiresIn": 900,
        }
    ]


def test_s3_upload_can_return_url_without_inline_content(monkeypatch):
    """S3-backed generated files can avoid embedding bytes in the run response."""
    s3_client = FakeS3Client(presigned_url="https://signed.example.com/generated/report.txt?expires=900")
    fake_boto3 = FakeBoto3(s3_client)
    monkeypatch.setattr(file_generation_module, "BOTO3_AVAILABLE", True)
    monkeypatch.setattr(file_generation_module, "boto3", fake_boto3, raising=False)

    tools = FileGenerationTools(
        s3_bucket="render-bucket",
        s3_prefix="generated",
        include_content=False,
    )
    result = tools.generate_text_file("Hello there", filename="report")

    file_artifact = _get_single_file(result)
    assert file_artifact.filename == "report.txt"
    assert file_artifact.url == "https://signed.example.com/generated/report.txt?expires=900"
    assert file_artifact.content is None
    assert file_artifact.size == len("Hello there")
    assert file_artifact.filepath is None
    assert s3_client.put_object_calls[0]["Body"] == b"Hello there"


def test_s3_upload_still_succeeds_when_presigned_url_generation_fails(monkeypatch):
    """Upload success should not be lost if only the render URL cannot be signed."""
    s3_client = FakeS3Client(presign_error=RuntimeError("signing disabled"))
    fake_boto3 = FakeBoto3(s3_client)
    monkeypatch.setattr(file_generation_module, "BOTO3_AVAILABLE", True)
    monkeypatch.setattr(file_generation_module, "boto3", fake_boto3, raising=False)

    tools = FileGenerationTools(s3_bucket="render-bucket", s3_prefix="generated")
    result = tools.generate_text_file("Hello there", filename="note")

    file_artifact = _get_single_file(result)
    assert file_artifact.filename == "note.txt"
    assert file_artifact.url is None
    assert file_artifact.content == b"Hello there"
    assert "uploaded to s3://render-bucket/generated/note.txt" in result.content
    assert "render URL failed: signing disabled" in result.content


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
