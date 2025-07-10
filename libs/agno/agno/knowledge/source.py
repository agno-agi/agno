from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from agno.document.reader import Reader
from agno.knowledge.cloud_storage.cloud_storage import CloudStorageConfig


@dataclass
class SourceContent:
    content: Optional[Union[str, bytes]] = None
    type: Optional[str] = None


@dataclass
class Source:
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    content: Optional[Union[str, SourceContent]] = None
    metadata: Optional[Dict[str, Any]] = None
    topics: Optional[List[str]] = None
    config: Optional[CloudStorageConfig] = None
    reader: Optional[Reader] = None
    size: Optional[int] = None
    status: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


# readers: List[Reader] = [
#         "PDFREADER": PDFReader(),
#         "URLREADER": URLReader(),
#         "WEBSITEREADER": WebsiteReader(),
#         "S3READER": S3PDFReader(),
#         "AZUREREADER": AzurePDFReader(),
#     ]


# "UUID": PDF: [
#     "id1": PDFReader(),
#     "id2": PDFURLReader(),
# ]

# URL: [
#     URLReader(),
#     WebsiteReader(),
# ]

# JSON: [
#     JSONReader(),
# ]


# LOAD:

# DocumentStore
# DocumentV2   -> Paths URLS
# Paths
# URLs
# Content


# ADD DOCUMENT
# DocumentV2   -> Paths URLS
# Paths
# URLs
# Content


# VECTOR DB
# DocumentsDB
# DocumentStore

# Manager
