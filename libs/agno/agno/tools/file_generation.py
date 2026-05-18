import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.exceptions import PathSecurityError
from agno.media import File
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, log_warning, logger
from agno.utils.path_safety import safe_join_filename, sanitize_filename

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    PDF_AVAILABLE = True
except ImportError as e:
    PDF_AVAILABLE = False
    log_warning(
        f"reportlab not installed. PDF generation will not be available. Install with: pip install reportlab: {str(e)}"
    )


class FileGenerationTools(Toolkit):
    def __init__(
        self,
        enable_json_generation: bool = True,
        enable_csv_generation: bool = True,
        enable_pdf_generation: bool = True,
        enable_txt_generation: bool = True,
        output_directory: Optional[str] = None,
        save_files: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.enable_json_generation = enable_json_generation
        self.enable_csv_generation = enable_csv_generation
        self.enable_pdf_generation = enable_pdf_generation and PDF_AVAILABLE
        self.enable_txt_generation = enable_txt_generation
        self.save_files = save_files

        # Only set up output directory when save_files is enabled
        if self.save_files:
            self.output_directory: Optional[Path] = (
                Path(output_directory).resolve() if output_directory else Path.cwd().resolve()
            )
            self.output_directory.mkdir(parents=True, exist_ok=True)
            log_debug(f"Files will be saved to: {self.output_directory}")
        else:
            self.output_directory = None

        if enable_pdf_generation and not PDF_AVAILABLE:
            logger.warning("PDF generation requested but reportlab is not installed. Disabling PDF generation.")
            self.enable_pdf_generation = False

        tools: List[Any] = []
        if all or enable_json_generation:
            tools.append(self.generate_json_file)
        if all or enable_csv_generation:
            tools.append(self.generate_csv_file)
        if all or (enable_pdf_generation and PDF_AVAILABLE):
            tools.append(self.generate_pdf_file)
        if all or enable_txt_generation:
            tools.append(self.generate_text_file)

        super().__init__(name="file_generation", tools=tools, **kwargs)

    def _save_file_to_disk(self, content: Union[str, bytes], filename: str) -> Tuple[Optional[str], Optional[str]]:
        """Save file to disk within output_directory.

        Returns:
            Tuple of (saved_path, error_message). If successful, error is None.
        """
        try:
            file_path = safe_join_filename(self.output_directory, filename)  # type: ignore[arg-type]
            if isinstance(content, str):
                file_path.write_text(content, encoding="utf-8")
            else:
                file_path.write_bytes(content)
        except (OSError, PathSecurityError) as e:
            log_warning(f"Failed to save file locally: {str(e)}")
            return None, str(e)
        log_debug(f"File saved to: {file_path}")
        return str(file_path), None

    def _create_file_artifact(
        self,
        content: Union[str, bytes],
        filename: Optional[str],
        file_type: str,
        mime_type: str,
        display_name: str,
    ) -> ToolResult:
        """Build a File artifact and optionally save to disk."""
        # Resolve filename: default if empty, ensure correct extension
        if not filename:
            filename = f"generated_file_{str(uuid4())[:8]}.{file_type}"
        elif not filename.endswith(f".{file_type}"):
            filename += f".{file_type}"
        file_name = sanitize_filename(filename)

        # Normalize to bytes for the artifact
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
            count_unit = "characters"
        else:
            content_bytes = content
            count_unit = "bytes"

        file_path: Optional[str] = None
        file_path_error: Optional[str] = None
        if self.save_files and self.output_directory:
            file_path, file_path_error = self._save_file_to_disk(content, file_name)

        file_artifact = File(
            id=str(uuid4()),
            content=content_bytes,
            mime_type=mime_type,
            file_type=file_type,
            filename=file_name,
            size=len(content_bytes),
            filepath=file_path,
        )

        log_debug(f"{display_name} file generated successfully")
        success_msg = f"{display_name} file '{file_name}' generated ({len(content)} {count_unit})"
        if file_path:
            success_msg += f" → {file_path}"
        elif file_path_error:
            success_msg += f" (save failed: {file_path_error})"

        return ToolResult(content=success_msg, files=[file_artifact])

    def generate_json_file(self, data: Union[Dict, List, str], filename: Optional[str] = None) -> ToolResult:
        """Generate a JSON file from the provided data.

        Args:
            data: The data to write to the JSON file. Can be a dictionary, list, or JSON string.
            filename: Optional filename for the generated file. If not provided, a UUID will be used.

        Returns:
            ToolResult: Result containing the generated JSON file as a FileArtifact.
        """
        try:
            log_debug(f"Generating JSON file with data: {type(data)}")

            # Handle different input types
            if isinstance(data, str):
                try:
                    json.loads(data)
                    json_content = data  # Use the original string if it's valid JSON
                except json.JSONDecodeError:
                    # If it's not valid JSON, treat as plain text and wrap it
                    json_content = json.dumps({"content": data}, indent=2)
            else:
                json_content = json.dumps(data, indent=2, ensure_ascii=False)

            return self._create_file_artifact(
                json_content,
                filename,
                file_type="json",
                mime_type="application/json",
                display_name="JSON",
            )

        except Exception as e:
            logger.exception("Failed to generate JSON file")
            return ToolResult(content=f"Error generating JSON file: {e}")

    def generate_csv_file(
        self,
        data: Union[List[List], List[Dict], str],
        filename: Optional[str] = None,
        headers: Optional[List[str]] = None,
    ) -> ToolResult:
        """Generate a CSV file from the provided data.

        Args:
            data: The data to write to the CSV file. Can be a list of lists, list of dictionaries, or CSV string.
            filename: Optional filename for the generated file. If not provided, a UUID will be used.
            headers: Optional headers for the CSV. Used when data is a list of lists.

        Returns:
            ToolResult: Result containing the generated CSV file as a FileArtifact.
        """
        try:
            log_debug(f"Generating CSV file with data: {type(data)}")

            # Create CSV content
            output = io.StringIO()

            if isinstance(data, str):
                # If it's already a CSV string, use it directly
                csv_content = data
            elif isinstance(data, list) and len(data) > 0:
                writer = csv.writer(output)

                if isinstance(data[0], dict):
                    # List of dictionaries - use keys as headers
                    if data:
                        fieldnames = list(data[0].keys())
                        writer.writerow(fieldnames)
                        for row in data:
                            if isinstance(row, dict):
                                writer.writerow([row.get(field, "") for field in fieldnames])
                            else:
                                writer.writerow([str(row)] + [""] * (len(fieldnames) - 1))
                elif isinstance(data[0], list):
                    # List of lists
                    if headers:
                        writer.writerow(headers)
                    writer.writerows(data)
                else:
                    # List of other types
                    if headers:
                        writer.writerow(headers)
                    for item in data:
                        writer.writerow([str(item)])

                csv_content = output.getvalue()
            else:
                csv_content = ""

            return self._create_file_artifact(
                csv_content,
                filename,
                file_type="csv",
                mime_type="text/csv",
                display_name="CSV",
            )

        except Exception as e:
            logger.exception("Failed to generate CSV file")
            return ToolResult(content=f"Error generating CSV file: {e}")

    def generate_pdf_file(
        self, content: str, filename: Optional[str] = None, title: Optional[str] = None
    ) -> ToolResult:
        """Generate a PDF file from the provided content.

        Args:
            content: The text content to write to the PDF file.
            filename: Optional filename for the generated file. If not provided, a UUID will be used.
            title: Optional title for the PDF document.

        Returns:
            ToolResult: Result containing the generated PDF file as a FileArtifact.
        """
        if not PDF_AVAILABLE:
            return ToolResult(
                content="PDF generation is not available. Please install reportlab: pip install reportlab"
            )

        try:
            log_debug(f"Generating PDF file with content length: {len(content)}")

            # Create PDF content in memory
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=1 * inch)

            # Get styles
            styles = getSampleStyleSheet()
            title_style = styles["Title"]
            normal_style = styles["Normal"]

            # Build story (content elements)
            story = []

            if title:
                story.append(Paragraph(title, title_style))
                story.append(Spacer(1, 20))

            # Split content into paragraphs and add to story
            paragraphs = content.split("\n\n")
            for para in paragraphs:
                if para.strip():
                    # Clean the paragraph text for PDF
                    clean_para = para.strip().replace("<", "&lt;").replace(">", "&gt;")
                    story.append(Paragraph(clean_para, normal_style))
                    story.append(Spacer(1, 10))

            # Build PDF
            doc.build(story)
            pdf_content = buffer.getvalue()
            buffer.close()

            return self._create_file_artifact(
                pdf_content,
                filename,
                file_type="pdf",
                mime_type="application/pdf",
                display_name="PDF",
            )

        except Exception as e:
            logger.exception("Failed to generate PDF file")
            return ToolResult(content=f"Error generating PDF file: {e}")

    def generate_text_file(self, content: str, filename: Optional[str] = None) -> ToolResult:
        """Generate a text file from the provided content.

        Args:
            content: The text content to write to the file.
            filename: Optional filename for the generated file. If not provided, a UUID will be used.

        Returns:
            ToolResult: Result containing the generated text file as a FileArtifact.
        """
        try:
            log_debug(f"Generating text file with content length: {len(content)}")

            return self._create_file_artifact(
                content,
                filename,
                file_type="txt",
                mime_type="text/plain",
                display_name="Text",
            )

        except Exception as e:
            logger.exception("Failed to generate text file")
            return ToolResult(content=f"Error generating text file: {e}")
