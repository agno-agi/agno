from dataclasses import dataclass
from typing import List, Optional, Union

from agno.document.reader import Reader
from agno.knowledge.cloud_storage.cloud_storage import CloudStorageConfig


@dataclass
class DocumentContent:
    content: Union[str, bytes]
    type: Optional[str] = None


@dataclass
class DocumentV2:  # We will rename this to Document
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    content: Optional[DocumentContent] = None
    metadata: Optional[dict] = None
    topics: Optional[List[str]] = None
    config: Optional[CloudStorageConfig] = None
    reader: Optional[Reader] = None
    size: Optional[int] = None


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