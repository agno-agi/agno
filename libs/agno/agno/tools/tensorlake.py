import os
import time
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from tensorlake.documentai import DocumentAI
    from tensorlake.documentai.models import (
        ChunkingStrategy,
        EnrichmentOptions,
        ParseStatus,
        ParsingOptions,
        TableOutputMode,
        TableParsingFormat,
    )

except ImportError:
    raise ImportError("`tensorlake` not installed. Please install using `pip install tensorlake`")


class TensorLakeTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_seconds: int = 300,
        **kwargs,
    ):
        """Initialize the TensorLake toolkit.

        Args:
            api_key: TensorLake API key (optional, will use TENSORLAKE_API_KEY env var if not provided)
            timeout_seconds: Default timeout for document processing jobs
        """
        super().__init__(name="tensorlake", **kwargs)

        # Get API key from environment if not provided
        self.api_key = api_key or os.getenv("TENSORLAKE_API_KEY")

        if not self.api_key:
            logger.error("TENSORLAKE_API_KEY not set. Please set the TENSORLAKE_API_KEY environment variable.")

        self.timeout_seconds = timeout_seconds

        # Register the document parsing method
        self.register(self.parse_document_to_markdown)
        logger.info("TensorLake toolkit initialized")

    def _convert_chunking_strategy(self, strategy: str) -> ChunkingStrategy:
        """Convert string chunking strategy to enum."""
        strategy_map = {
            "none": ChunkingStrategy.NONE,
            "page": ChunkingStrategy.PAGE,
            "section": ChunkingStrategy.SECTION,
            "fragment": ChunkingStrategy.FRAGMENT,
        }
        return strategy_map.get(strategy.lower(), ChunkingStrategy.PAGE)

    def _convert_table_parsing_format(self, format_str: str) -> TableParsingFormat:
        """Convert string table parsing format to enum."""
        format_map = {
            "tsr": TableParsingFormat.TSR,
            "vlm": TableParsingFormat.VLM,
        }
        return format_map.get(format_str.lower(), TableParsingFormat.VLM)

    def _convert_table_output_mode(self, mode: str) -> TableOutputMode:
        """Convert string table output mode to enum."""
        mode_map = {
            "markdown": TableOutputMode.MARKDOWN,
            "html": TableOutputMode.HTML,
        }
        return mode_map.get(mode.lower(), TableOutputMode.MARKDOWN)

    def parse_document_to_markdown(
        self,
        document_path: str,
        chunking_strategy: str = "page",
        table_parsing_format: str = "vlm",
        table_output_mode: str = "markdown",
        table_summarization: bool = False,
        table_summarization_prompt: Optional[str] = None,
        figure_summarization: bool = False,
        figure_summarization_prompt: Optional[str] = None,
        page_range: Optional[str] = None,
        disable_layout_detection: bool = False,
        skew_detection: bool = False,
        signature_detection: bool = False,
        remove_strikethrough_lines: bool = False,
        timeout_seconds: Optional[int] = None,
    ) -> str:
        """Parse a document and convert it to markdown format with AI-powered analysis.

        This function can handle various document formats (PDF, DOCX, images) with advanced parsing capabilities.

        Args:
            document_path: Path to the document file, URL, or TensorLake file ID to parse
            chunking_strategy: How to split the document (default: "page"):
                - "none": No chunking is applied, the entire document is treated as a single chunk
                - "page": The document is chunked by page
                - "section": The document is chunked into sections. Title and section headers are used as chunking markers. (ideal for structured docs like research papers)
                - "fragment": Each page element is converted into markdown form (tables, figures, text blocks)
            table_parsing_format: How to parse tables (default: "vlm"):
                - "tsr": Table Structure Recognition (better for clean, grid-like tables)
                - "vlm": Vision Language Model (better for complex/merged cell tables)
            table_output_mode: Table output format (default: "markdown"):
                - "markdown": Tables as markdown (better for LLM processing)
                - "html": Tables as HTML (preserves complex formatting)
            table_summarization: Whether to generate AI summaries of table content
            table_summarization_prompt: Custom prompt for table analysis (optional)
            figure_summarization: Whether to generate AI descriptions of figures/charts
            figure_summarization_prompt: Custom prompt for figure analysis (optional)
            page_range: Specific pages to parse (e.g., '1-5', '1,3,5', '10-end'). None means all pages
            disable_layout_detection: Skip visual layout analysis (faster but less accurate for complex docs)
            skew_detection: Apply rotation correction to scanned documents
            signature_detection: Detect and flag presence of signatures in the document
            remove_strikethrough_lines: Remove crossed-out text from the output
            timeout_seconds: Override default timeout (uses instance timeout if None)

        Returns:
            str: The parsed document in markdown format, or error message if failed
        """
        if not self.api_key:
            return "Error: TENSORLAKE_API_KEY is not configured"

        if not document_path:
            return "Error: No document path provided"

        try:
            # Convert string parameters to enum values
            chunking_strategy_enum = self._convert_chunking_strategy(chunking_strategy)
            table_parsing_format_enum = self._convert_table_parsing_format(table_parsing_format)
            table_output_mode_enum = self._convert_table_output_mode(table_output_mode)

            # Initialize DocumentAI client
            doc_ai = DocumentAI(api_key=self.api_key)

            # Handle different input types
            if os.path.isfile(document_path):
                data = doc_ai.upload(path=document_path)  # Upload local file
            else:
                data = document_path  # Assume it's a file ID, URL, or raw text

            logger.info(f"Processing document: {data}")

            # Configure parsing options (using enums directly)
            parsing_options = ParsingOptions(
                remove_strikethrough_lines=remove_strikethrough_lines,
                signature_detection=signature_detection,
                skew_detection=skew_detection,
                table_output_mode=table_output_mode_enum,
                table_parsing_format=table_parsing_format_enum,
                disable_layout_detection=disable_layout_detection,
                chunking_strategy=chunking_strategy_enum,
            )

            logger.info(f"Parsing Options: {parsing_options}")

            # Configure enrichment options
            enrichment_options = EnrichmentOptions(
                figure_summarization=figure_summarization,
                figure_summarization_prompt=figure_summarization_prompt,
                table_summarization=table_summarization,
                table_summarization_prompt=table_summarization_prompt,
            )

            logger.info(f"Enrichment Options: {enrichment_options}")

            # Start parsing job
            parse_id = doc_ai.parse(
                file=data, parsing_options=parsing_options, enrichment_options=enrichment_options, page_range=page_range
            )
            logger.info(f"Started parsing job with ID: {parse_id}")

            # Poll for completion
            start_time = time.time()
            max_wait_time = timeout_seconds if timeout_seconds is not None else self.timeout_seconds

            while time.time() - start_time < max_wait_time:
                result = doc_ai.get_parsed_result(parse_id)
                logger.info(f"Current status: {result.status}")

                if result.status in [ParseStatus.PENDING, ParseStatus.PROCESSING]:
                    time.sleep(5)  # Wait 5 seconds before checking again
                elif result.status == ParseStatus.SUCCESSFUL:
                    logger.info("Document parsing completed successfully")
                    # Return the parsed content
                    if hasattr(result, "chunks") and result.chunks:
                        content_parts = []
                        for chunk in result.chunks:
                            content_parts.append(f"## Page {chunk.page_number}\n\n{chunk.content}")
                        return "\n\n".join(content_parts)
                    else:
                        return str(result)  # Fallback to string representation
                else:
                    logger.error(f"Document parsing failed with status: {result.status}")
                    return f"Document parsing failed with status: {result.status}"

            # Timeout reached
            timeout_msg = f"Document processing timeout after {max_wait_time} seconds. Job ID: {parse_id}"
            logger.error(timeout_msg)
            return timeout_msg

        except Exception as e:
            error_msg = f"Error processing document: {str(e)}"
            logger.error(error_msg)
            return error_msg
