"""
This reader is used to read any type of file or document.
It will use the file extension to determine the reader to use.
When passed a URL, it will determine what type of file it is and use the appropriate reader.
"""

from typing import Union, Optional, List, Any
from pathlib import Path
from typing import IO

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.document.reader.markdown_reader import MarkdownReader
from agno.document.reader.pdf_reader import PDFReader
from agno.utils.log import logger

class DynamicReader(Reader):
    """
    This reader is used to read any type of file or document.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def read(
        self,
        path: Optional[Path] = None,
        url: Optional[str] = None,
    ) -> List[Document]:
        """
        Read a file or document and return a list of documents.
        """
        documents = []
        if path:
            path = Path(path)
            if path.is_dir():
            #   do a recursive read and call the read function and append the results to the documents list.
                for child in path.iterdir():
                    if child.is_file():
                        res= self.read(path=child)
                        documents.extend(res)
            elif path.is_file():
                if path.suffix == '.md':
                    reader = MarkdownReader()
                    documents.extend(reader.read(file=path))
                elif path.suffix == '.pdf':
                    print("READING PDF", path)
                    reader = PDFReader(chunk=True)
                    documents.extend(reader.read(pdf=path))
                else:
                    raise ValueError(f"Unsupported file type: {path.suffix}")
        return documents
        
    # def read_file(self, file: Path) -> List[Document]:
    #     if file.suffix == '.md':
    #         reader = MarkdownReader()
    #         return reader.read(file=file)
    #     elif file.suffix == '.pdf':
    #         reader = PDFReader(chunk=True)
    #         return reader.read(file=file)
    #     else:
    #         raise ValueError(f"Unsupported file type: {file.suffix}")