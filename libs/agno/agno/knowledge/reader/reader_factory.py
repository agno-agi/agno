import os
from typing import Any, Callable, Dict, List, Optional

from agno.knowledge.reader.base import Reader


class ReaderFactory:
    """Factory for creating and managing document readers with lazy loading."""

    # Cache for instantiated readers
    _reader_cache: Dict[str, Reader] = {}

    # Static metadata for readers - avoids instantiation just to get metadata
    READER_METADATA: Dict[str, Dict[str, str]] = {
        "pdf": {
            "name": "PdfReader",
            "description": "Processes PDF documents with OCR support for images and text extraction",
        },
        "csv": {
            "name": "CsvReader",
            "description": "Parses CSV files with custom delimiter support",
        },
        "excel": {
            "name": "ExcelReader",
            "description": "Processes Excel workbooks (.xlsx and .xls) with sheet filtering and row-based chunking",
        },
        "field_labeled_csv": {
            "name": "FieldLabeledCsvReader",
            "description": "Converts CSV rows to field-labeled text format for enhanced readability and context",
        },
        "docx": {
            "name": "DocxReader",
            "description": "Extracts text content from Microsoft Word documents (.docx and .doc formats)",
        },
        "pptx": {
            "name": "PptxReader",
            "description": "Extracts text content from Microsoft PowerPoint presentations (.pptx format)",
        },
        "json": {
            "name": "JsonReader",
            "description": "Processes JSON data structures and API responses with nested object handling",
        },
        "markdown": {
            "name": "MarkdownReader",
            "description": "Processes Markdown documentation with header-aware chunking and formatting preservation",
        },
        "text": {
            "name": "TextReader",
            "description": "Handles plain text files with customizable chunking strategies and encoding detection",
        },
        "website": {
            "name": "WebsiteReader",
            "description": "Scrapes and extracts content from web pages with HTML parsing and text cleaning",
        },
        "firecrawl": {
            "name": "FirecrawlReader",
            "description": "Advanced web scraping and crawling with JavaScript rendering and structured data extraction",
        },
        "tavily": {
            "name": "TavilyReader",
            "description": "Extracts content from URLs using Tavily's Extract API with markdown or text output",
        },
        "youtube": {
            "name": "YouTubeReader",
            "description": "Extracts transcripts and metadata from YouTube videos and playlists",
        },
        "arxiv": {
            "name": "ArxivReader",
            "description": "Downloads and processes academic papers from ArXiv with PDF parsing and metadata extraction",
        },
        "wikipedia": {
            "name": "WikipediaReader",
            "description": "Fetches and processes Wikipedia articles with section-aware chunking and link resolution",
        },
        "web_search": {
            "name": "WebSearchReader",
            "description": "Executes web searches and processes results with relevance ranking and content extraction",
        },
    }

    @classmethod
    def _get_pdf_reader(cls, **kwargs) -> Reader:
        """Get PDF reader instance."""
        from agno.knowledge.reader.pdf_reader import PDFReader

        config: Dict[str, Any] = {
            "name": "PDF Reader",
            "description": "Processes PDF documents with OCR support for images and text extraction",
        }
        config.update(kwargs)
        return PDFReader(**config)

    @classmethod
    def _get_csv_reader(cls, **kwargs) -> Reader:
        """Get CSV reader instance."""
        from agno.knowledge.reader.csv_reader import CSVReader

        config: Dict[str, Any] = {
            "name": "CSV Reader",
            "description": "Parses CSV files with custom delimiter support",
        }
        config.update(kwargs)
        return CSVReader(**config)

    @classmethod
    def _get_excel_reader(cls, **kwargs) -> Reader:
        """Get Excel reader instance."""
        from agno.knowledge.reader.excel_reader import ExcelReader

        config: Dict[str, Any] = {
            "name": "Excel Reader",
            "description": "Processes Excel workbooks (.xlsx and .xls) with sheet filtering and row-based chunking",
        }
        config.update(kwargs)
        return ExcelReader(**config)

    @classmethod
    def _get_field_labeled_csv_reader(cls, **kwargs) -> Reader:
        """Get Field Labeled CSV reader instance."""
        from agno.knowledge.reader.field_labeled_csv_reader import FieldLabeledCSVReader

        config: Dict[str, Any] = {
            "name": "Field Labeled CSV Reader",
            "description": "Converts CSV rows to field-labeled text format for enhanced readability and context",
        }
        config.update(kwargs)
        return FieldLabeledCSVReader(**config)

    @classmethod
    def _get_docx_reader(cls, **kwargs) -> Reader:
        """Get Docx reader instance."""
        from agno.knowledge.reader.docx_reader import DocxReader

        config: Dict[str, Any] = {
            "name": "Docx Reader",
            "description": "Extracts text content from Microsoft Word documents (.docx and .doc formats)",
        }
        config.update(kwargs)
        return DocxReader(**config)

    @classmethod
    def _get_pptx_reader(cls, **kwargs) -> Reader:
        """Get PPTX reader instance."""
        from agno.knowledge.reader.pptx_reader import PPTXReader

        config: Dict[str, Any] = {
            "name": "PPTX Reader",
            "description": "Extracts text content from Microsoft PowerPoint presentations (.pptx format)",
        }
        config.update(kwargs)
        return PPTXReader(**config)

    @classmethod
    def _get_json_reader(cls, **kwargs) -> Reader:
        """Get JSON reader instance."""
        from agno.knowledge.reader.json_reader import JSONReader

        config: Dict[str, Any] = {
            "name": "JSON Reader",
            "description": "Processes JSON data structures and API responses with nested object handling",
        }
        config.update(kwargs)
        return JSONReader(**config)

    @classmethod
    def _get_markdown_reader(cls, **kwargs) -> Reader:
        """Get Markdown reader instance."""
        from agno.knowledge.reader.markdown_reader import MarkdownReader

        config: Dict[str, Any] = {
            "name": "Markdown Reader",
            "description": "Processes Markdown documentation with header-aware chunking and formatting preservation",
        }
        config.update(kwargs)
        return MarkdownReader(**config)

    @classmethod
    def _get_text_reader(cls, **kwargs) -> Reader:
        """Get Text reader instance."""
        from agno.knowledge.reader.text_reader import TextReader

        config: Dict[str, Any] = {
            "name": "Text Reader",
            "description": "Handles plain text files with customizable chunking strategies and encoding detection",
        }
        config.update(kwargs)
        return TextReader(**config)

    @classmethod
    def _get_website_reader(cls, **kwargs) -> Reader:
        """Get Website reader instance."""
        from agno.knowledge.reader.website_reader import WebsiteReader

        config: Dict[str, Any] = {
            "name": "Website Reader",
            "description": "Scrapes and extracts content from web pages with HTML parsing and text cleaning",
        }
        config.update(kwargs)
        return WebsiteReader(**config)

    @classmethod
    def _get_firecrawl_reader(cls, **kwargs) -> Reader:
        """Get Firecrawl reader instance."""
        from agno.knowledge.reader.firecrawl_reader import FirecrawlReader

        config: Dict[str, Any] = {
            "api_key": kwargs.get("api_key") or os.getenv("FIRECRAWL_API_KEY"),
            "mode": "crawl",
            "name": "Firecrawl Reader",
            "description": "Advanced web scraping and crawling with JavaScript rendering and structured data extraction",
        }
        config.update(kwargs)
        return FirecrawlReader(**config)

    @classmethod
    def _get_tavily_reader(cls, **kwargs) -> Reader:
        """Get Tavily reader instance."""
        from agno.knowledge.reader.tavily_reader import TavilyReader

        config: Dict[str, Any] = {
            "api_key": kwargs.get("api_key") or os.getenv("TAVILY_API_KEY"),
            "extract_format": "markdown",
            "extract_depth": "basic",
            "name": "Tavily Reader",
            "description": "Extracts content from URLs using Tavily's Extract API with markdown or text output",
        }
        config.update(kwargs)
        return TavilyReader(**config)

    @classmethod
    def _get_youtube_reader(cls, **kwargs) -> Reader:
        """Get YouTube reader instance."""
        from agno.knowledge.reader.youtube_reader import YouTubeReader

        config: Dict[str, Any] = {
            "name": "YouTube Reader",
            "description": "Extracts transcripts and metadata from YouTube videos and playlists",
        }
        config.update(kwargs)
        return YouTubeReader(**config)

    @classmethod
    def _get_arxiv_reader(cls, **kwargs) -> Reader:
        """Get Arxiv reader instance."""
        from agno.knowledge.reader.arxiv_reader import ArxivReader

        config: Dict[str, Any] = {
            "name": "Arxiv Reader",
            "description": "Downloads and processes academic papers from ArXiv with PDF parsing and metadata extraction",
        }
        config.update(kwargs)
        return ArxivReader(**config)

    @classmethod
    def _get_wikipedia_reader(cls, **kwargs) -> Reader:
        """Get Wikipedia reader instance."""
        from agno.knowledge.reader.wikipedia_reader import WikipediaReader

        config: Dict[str, Any] = {
            "name": "Wikipedia Reader",
            "description": "Fetches and processes Wikipedia articles with section-aware chunking and link resolution",
        }
        config.update(kwargs)
        return WikipediaReader(**config)

    @classmethod
    def _get_web_search_reader(cls, **kwargs) -> Reader:
        """Get Web Search reader instance."""
        from agno.knowledge.reader.web_search_reader import WebSearchReader

        config: Dict[str, Any] = {
            "name": "Web Search Reader",
            "description": "Executes web searches and processes results with relevance ranking and content extraction",
        }
        config.update(kwargs)
        return WebSearchReader(**config)

    @classmethod
    def _get_reader_method(cls, reader_key: str) -> Callable[[], Reader]:
        """Get the appropriate reader method for the given key."""
        method_name = f"_get_{reader_key}_reader"
        if not hasattr(cls, method_name):
            raise ValueError(f"Unknown reader: {reader_key}")
        return getattr(cls, method_name)

    @classmethod
    def get_reader_class(cls, reader_key: str) -> type:
        """Get the reader CLASS without instantiation.

        This is useful for accessing class methods like get_supported_chunking_strategies()
        without the overhead of creating an instance.

        Args:
            reader_key: The reader key (e.g., 'pdf', 'csv', 'markdown')

        Returns:
            The reader class (not an instance)

        Raises:
            ValueError: If the reader key is unknown
            ImportError: If the reader's dependencies are not installed
        """
        # Map reader keys to their import paths
        reader_class_map: Dict[str, tuple] = {
            "pdf": ("agno.knowledge.reader.pdf_reader", "PDFReader"),
            "csv": ("agno.knowledge.reader.csv_reader", "CSVReader"),
            "excel": ("agno.knowledge.reader.excel_reader", "ExcelReader"),
            "field_labeled_csv": ("agno.knowledge.reader.field_labeled_csv_reader", "FieldLabeledCSVReader"),
            "docx": ("agno.knowledge.reader.docx_reader", "DocxReader"),
            "pptx": ("agno.knowledge.reader.pptx_reader", "PPTXReader"),
            "json": ("agno.knowledge.reader.json_reader", "JSONReader"),
            "markdown": ("agno.knowledge.reader.markdown_reader", "MarkdownReader"),
            "text": ("agno.knowledge.reader.text_reader", "TextReader"),
            "website": ("agno.knowledge.reader.website_reader", "WebsiteReader"),
            "firecrawl": ("agno.knowledge.reader.firecrawl_reader", "FirecrawlReader"),
            "tavily": ("agno.knowledge.reader.tavily_reader", "TavilyReader"),
            "youtube": ("agno.knowledge.reader.youtube_reader", "YouTubeReader"),
            "arxiv": ("agno.knowledge.reader.arxiv_reader", "ArxivReader"),
            "wikipedia": ("agno.knowledge.reader.wikipedia_reader", "WikipediaReader"),
            "web_search": ("agno.knowledge.reader.web_search_reader", "WebSearchReader"),
        }

        if reader_key not in reader_class_map:
            raise ValueError(f"Unknown reader: {reader_key}")

        module_path, class_name = reader_class_map[reader_key]

        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    @classmethod
    def get_reader_key_for_class_name(cls, class_name: str) -> Optional[str]:
        """Map a reader class name back to its reader key.

        Args:
            class_name: The reader class name (e.g., "PDFReader", "CSVReader")

        Returns:
            The reader key (e.g., "pdf", "csv") or None if not found.
        """
        reader_class_map: Dict[str, tuple] = {
            "pdf": ("agno.knowledge.reader.pdf_reader", "PDFReader"),
            "csv": ("agno.knowledge.reader.csv_reader", "CSVReader"),
            "excel": ("agno.knowledge.reader.excel_reader", "ExcelReader"),
            "field_labeled_csv": ("agno.knowledge.reader.field_labeled_csv_reader", "FieldLabeledCSVReader"),
            "docx": ("agno.knowledge.reader.docx_reader", "DocxReader"),
            "pptx": ("agno.knowledge.reader.pptx_reader", "PPTXReader"),
            "json": ("agno.knowledge.reader.json_reader", "JSONReader"),
            "markdown": ("agno.knowledge.reader.markdown_reader", "MarkdownReader"),
            "text": ("agno.knowledge.reader.text_reader", "TextReader"),
            "website": ("agno.knowledge.reader.website_reader", "WebsiteReader"),
            "firecrawl": ("agno.knowledge.reader.firecrawl_reader", "FirecrawlReader"),
            "tavily": ("agno.knowledge.reader.tavily_reader", "TavilyReader"),
            "youtube": ("agno.knowledge.reader.youtube_reader", "YouTubeReader"),
            "arxiv": ("agno.knowledge.reader.arxiv_reader", "ArxivReader"),
            "wikipedia": ("agno.knowledge.reader.wikipedia_reader", "WikipediaReader"),
            "web_search": ("agno.knowledge.reader.web_search_reader", "WebSearchReader"),
        }
        for key, (_, cls_name) in reader_class_map.items():
            if cls_name == class_name:
                return key
        return None

    @classmethod
    def create_reader(cls, reader_key: str, **kwargs) -> Reader:
        """Create a reader instance with the given key and optional overrides."""
        if reader_key in cls._reader_cache:
            return cls._reader_cache[reader_key]

        # Get the reader method and create the instance
        reader_method = cls._get_reader_method(reader_key)
        reader = reader_method(**kwargs)

        # Cache the reader
        cls._reader_cache[reader_key] = reader

        return reader

    @classmethod
    def get_reader_for_extension(cls, extension: str) -> Reader:
        """Get the appropriate reader for a file extension."""
        extension = extension.lower()

        if extension in [".pdf", "application/pdf"]:
            return cls.create_reader("pdf")
        elif extension in [".csv", "text/csv"]:
            return cls.create_reader("csv")
        elif extension in [
            ".xlsx",
            ".xls",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        ]:
            return cls.create_reader("excel")
        elif extension in [".docx", ".doc", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
            return cls.create_reader("docx")
        elif extension == ".pptx":
            return cls.create_reader("pptx")
        elif extension == ".json":
            return cls.create_reader("json")
        elif extension in [".md", ".markdown"]:
            return cls.create_reader("markdown")
        elif extension in [".txt", ".text"]:
            return cls.create_reader("text")
        else:
            # Default to text reader for unknown extensions
            return cls.create_reader("text")

    @classmethod
    def get_reader_for_url(cls, url: str) -> Reader:
        """Get the appropriate reader for a URL."""
        url_lower = url.lower()

        # Check for YouTube URLs
        if any(domain in url_lower for domain in ["youtube.com", "youtu.be"]):
            return cls.create_reader("youtube")

        # Default to website reader
        return cls.create_reader("website")

    @classmethod
    def get_all_reader_keys(cls) -> List[str]:
        """Get all available reader keys in priority order."""
        # Extract reader keys from method names

        PREFIX = "_get_"
        SUFFIX = "_reader"

        reader_keys = []
        for attr_name in dir(cls):
            if attr_name.startswith(PREFIX) and attr_name.endswith(SUFFIX):
                reader_key = attr_name[len(PREFIX) : -len(SUFFIX)]  # Remove "_get_" prefix and "_reader" suffix
                reader_keys.append(reader_key)

        # Define priority order for URL readers
        url_reader_priority = [
            "website",
            "firecrawl",
            "tavily",
            "youtube",
        ]

        # Sort with URL readers in priority order, others alphabetically
        def sort_key(reader_key):
            if reader_key in url_reader_priority:
                return (0, url_reader_priority.index(reader_key))
            else:
                return (1, reader_key)

        reader_keys.sort(key=sort_key)
        return reader_keys

    @classmethod
    def create_all_readers(cls) -> Dict[str, Reader]:
        """Create all readers and return them as a dictionary."""
        readers = {}
        for reader_key in cls.get_all_reader_keys():
            readers[reader_key] = cls.create_reader(reader_key)
        return readers

    @classmethod
    def clear_cache(cls):
        """Clear the reader cache."""
        cls._reader_cache.clear()

    @classmethod
    def register_reader(
        cls,
        key: str,
        reader_method,
        name: str,
        description: str,
        extensions: Optional[List[str]] = None,
    ):
        """Register a new reader type."""
        # Add the reader method to the class
        method_name = f"_get_{key}_reader"
        setattr(cls, method_name, classmethod(reader_method))
