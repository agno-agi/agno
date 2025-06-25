from dataclasses import dataclass
from typing import List, Union, Optional
from agno.document.reader import Reader


@dataclass
class DocumentContent():
    content: Union[str, bytes]
    type: str

@dataclass
class DocumentV2(): # We will rename this to Document
    name: str
    id: Optional[str] = None
    description: Optional[str] = None
    paths: Optional[Union[str, List[str]]] = None
    urls: Optional[Union[str, List[str]]] = None
    content: Optional[DocumentContent] = None
    metadata: Optional[dict] = None
    reader: Optional[Reader] = None