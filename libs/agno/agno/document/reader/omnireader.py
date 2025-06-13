from pathlib import Path
from typing import IO, Any, List, Union

from agno.document import Document
from agno.document.reader.base import Reader


class OmniReader(Reader):
    """Reader class that can read all types of documents"""

    def read(self, file: Union[Path, IO[Any]]) -> List[Document]:
        pass

    async def async_read(self, file: Union[Path, IO[Any]]) -> List[Document]:
        pass
