import os
from typing import Dict, List, Optional, Type

from agno.document.reader.base import Reader
from agno.utils.log import log_info


class ReaderFactory:
    """Factory for creating and managing document readers with lazy loading."""
    
    # Registry of reader classes with their configurations
    _reader_registry: Dict[str, Dict] = {
        # File readers
        "pdf": {
            "class": "agno.document.reader.pdf_reader.PDFReader",
            "config": {"chunk": True, "chunk_size": 100},
            "extensions": [".pdf"],
            "name": "PDF Reader",
            "description": "Reads PDF files"
        },
        "csv": {
            "class": "agno.document.reader.csv_reader.CSVReader", 
            "config": {"name": "CSV Reader", "description": "Reads CSV files"},
            "extensions": [".csv"],
            "name": "CSV Reader",
            "description": "Reads CSV files"
        },
        "docx": {
            "class": "agno.document.reader.docx_reader.DocxReader",
            "config": {"name": "Docx Reader", "description": "Reads Docx files"},
            "extensions": [".docx", ".doc"],
            "name": "Docx Reader", 
            "description": "Reads Docx files"
        },
        "json": {
            "class": "agno.document.reader.json_reader.JSONReader",
            "config": {"name": "JSON Reader", "description": "Reads JSON files"},
            "extensions": [".json"],
            "name": "JSON Reader",
            "description": "Reads JSON files"
        },
        "markdown": {
            "class": "agno.document.reader.markdown_reader.MarkdownReader",
            "config": {"name": "Markdown Reader", "description": "Reads Markdown files"},
            "extensions": [".md", ".markdown"],
            "name": "Markdown Reader",
            "description": "Reads Markdown files"
        },
        "text": {
            "class": "agno.document.reader.text_reader.TextReader",
            "config": {"name": "Text Reader", "description": "Reads Text files"},
            "extensions": [".txt", ".text"],
            "name": "Text Reader",
            "description": "Reads Text files"
        },
        
        # URL readers
        "url": {
            "class": "agno.document.reader.url_reader.URLReader",
            "config": {"name": "URL Reader", "description": "Reads URLs"},
            "name": "URL Reader",
            "description": "Reads URLs"
        },
        "website": {
            "class": "agno.document.reader.website_reader.WebsiteReader",
            "config": {"name": "Website Reader", "description": "Reads Website files"},
            "name": "Website Reader",
            "description": "Reads Website files"
        },
        "firecrawl": {
            "class": "agno.document.reader.firecrawl_reader.FirecrawlReader",
            "config": {
                "api_key": None,  # Will be set from env
                "mode": "crawl",
                "name": "Firecrawl Reader",
                "description": "Crawls websites"
            },
            "name": "Firecrawl Reader",
            "description": "Crawls websites"
        },
        "youtube": {
            "class": "agno.document.reader.youtube_reader.YouTubeReader",
            "config": {"name": "YouTube Reader", "description": "Reads YouTube videos"},
            "name": "YouTube Reader",
            "description": "Reads YouTube videos"
        },
        
        # URL file readers
        "pdf_url": {
            "class": "agno.document.reader.pdf_reader.PDFUrlReader",
            "config": {"name": "PDF URL Reader", "description": "Reads PDF URLs"},
            "name": "PDF URL Reader",
            "description": "Reads PDF URLs"
        },
        "csv_url": {
            "class": "agno.document.reader.csv_reader.CSVUrlReader",
            "config": {"name": "CSV URL Reader", "description": "Reads CSV URLs"},
            "name": "CSV URL Reader",
            "description": "Reads CSV URLs"
        }
    }
    
    # Cache for instantiated readers
    _reader_cache: Dict[str, Reader] = {}
    
    @classmethod
    def _import_reader_class(cls, class_path: str) -> Type[Reader]:
        """Import a reader class from its module path."""
        try:
            module_path, class_name = class_path.rsplit('.', 1)
            module = __import__(module_path, fromlist=[class_name])
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Could not import reader class {class_path}: {e}")
    
    @classmethod
    def _get_reader_config(cls, reader_key: str) -> Dict:
        """Get configuration for a specific reader."""
        if reader_key not in cls._reader_registry:
            raise ValueError(f"Unknown reader: {reader_key}")
        return cls._reader_registry[reader_key].copy()
    
    @classmethod
    def create_reader(cls, reader_key: str, **kwargs) -> Reader:
        """Create a reader instance with the given key and optional overrides."""
        if reader_key in cls._reader_cache:
            return cls._reader_cache[reader_key]
        
        config = cls._get_reader_config(reader_key)
        class_path = config["class"]
        
        # Import the reader class
        reader_class = cls._import_reader_class(class_path)
        
        # Merge default config with kwargs
        reader_config = config["config"].copy()
        reader_config.update(kwargs)
        
        # Handle special cases
        if reader_key == "firecrawl" and reader_config.get("api_key") is None:
            reader_config["api_key"] = os.getenv("FIRECRAWL_API_KEY")
        
        # Create the reader instance
        reader = reader_class(**reader_config)
        
        # Cache the reader
        cls._reader_cache[reader_key] = reader
        
        return reader
    
    @classmethod
    def get_reader_for_extension(cls, extension: str) -> Reader:
        """Get the appropriate reader for a file extension."""
        extension = extension.lower()
        
        # Find reader by extension
        for reader_key, config in cls._reader_registry.items():
            if "extensions" in config and extension in config["extensions"]:
                return cls.create_reader(reader_key)
        
        # Default to text reader for unknown extensions
        return cls.create_reader("text")
    
    @classmethod
    def get_reader_for_url(cls, url: str) -> Reader:
        """Get the appropriate reader for a URL."""
        url_lower = url.lower()
        
        # Check for YouTube URLs
        if any(domain in url_lower for domain in ["youtube.com", "youtu.be"]):
            return cls.create_reader("youtube")
        
        # Default to URL reader
        return cls.create_reader("url")
    
    @classmethod
    def get_reader_for_url_file(cls, extension: str) -> Reader:
        """Get the appropriate reader for a URL file extension."""
        extension = extension.lower()
        
        if extension == ".pdf":
            return cls.create_reader("pdf_url")
        elif extension == ".csv":
            return cls.create_reader("csv_url")
        else:
            return cls.create_reader("url")
    
    @classmethod
    def get_all_reader_keys(cls) -> List[str]:
        """Get all available reader keys."""
        return list(cls._reader_registry.keys())
    
    @classmethod
    def get_reader_info(cls, reader_key: str) -> Dict:
        """Get information about a reader without instantiating it."""
        config = cls._get_reader_config(reader_key)
        return {
            "key": reader_key,
            "name": config["name"],
            "description": config["description"],
            "extensions": config.get("extensions", []),
            "class": config["class"]
        }
    
    @classmethod
    def get_all_readers_info(cls) -> List[Dict]:
        """Get information about all available readers."""
        return [cls.get_reader_info(key) for key in cls.get_all_reader_keys()]
    
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
    def register_reader(cls, key: str, class_path: str, config: Dict, 
                       name: str, description: str, extensions: Optional[List[str]] = None):
        """Register a new reader type."""
        cls._reader_registry[key] = {
            "class": class_path,
            "config": config,
            "name": name,
            "description": description,
            "extensions": extensions or []
        } 