import csv
import io
import os
from pathlib import Path
from time import sleep
from typing import IO, Any, List, Union
from urllib.parse import urlparse

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import logger


class CSVReader(Reader):
    """Reader for CSV files"""

    def read(self, file: Union[Path, IO[Any]], delimiter: str = ",", quotechar: str = '"') -> List[Document]:
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                logger.info(f"Reading: {file}")
                file_content = file.open(newline="", mode="r", encoding="utf-8")
            else:
                logger.info(f"Reading uploaded file: {file.name}")
                file.seek(0)
                file_content = io.StringIO(file.read().decode("utf-8"))  # type: ignore

            csv_name = Path(file.name).stem if isinstance(file, Path) else file.name.split(".")[0]
            csv_content = ""
            with file_content as csvfile:
                csv_reader = csv.reader(csvfile, delimiter=delimiter, quotechar=quotechar)
                for row in csv_reader:
                    csv_content += ", ".join(row) + "\n"

            documents = [
                Document(
                    name=csv_name,
                    id=csv_name,
                    content=csv_content,
                )
            ]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents
            return documents
        except Exception as e:
            logger.error(f"Error reading: {file.name if isinstance(file, IO) else file}: {e}")
            return []


class CSVUrlReader(Reader):
    """Reader for CSV files"""

    def read(self, url: str) -> List[Document]:
        if not url:
            raise ValueError("No URL provided")

        try:
            import httpx
        except ImportError:
            raise ImportError("`httpx` not installed")

        logger.info(f"Reading: {url}")
        # Retry the request up to 3 times with exponential backoff
        for attempt in range(3):
            try:
                response = httpx.get(url)
                break
            except httpx.RequestError as e:
                if attempt == 2:  # Last attempt
                    logger.error(f"Failed to fetch CSV after 3 attempts: {e}")
                    raise
                wait_time = 2**attempt  # Exponential backoff: 1, 2, 4 seconds
                logger.warning(f"Request failed, retrying in {wait_time} seconds...")
                sleep(wait_time)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
            raise

        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path) or "data.csv"

        file_obj = io.BytesIO(response.content)
        file_obj.name = filename

        documents = CSVReader().read(file=file_obj)

        file_obj.close()

        return documents
