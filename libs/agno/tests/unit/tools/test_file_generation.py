import json
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
