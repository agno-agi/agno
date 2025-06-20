from dataclasses import dataclass
from typing import List, Union, Optional
from agno.document.reader import Reader

@dataclass
class DocumentV2(): # We will rename this to Document
    name: str
    paths: Optional[Union[str, List[str]]] = None
    urls: Optional[Union[str, List[str]]] = None
    metadata: Optional[dict] = None
    reader: Optional[Reader] = None