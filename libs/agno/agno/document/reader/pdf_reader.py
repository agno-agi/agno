import asyncio
from pathlib import Path
import re
from typing import IO, Any, List, Optional, Union
from uuid import uuid4

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.http import async_fetch_with_retry, fetch_with_retry
from agno.utils.log import log_info, logger

try:
    from pypdf import PdfReader as DocumentReader  # noqa: F401
    from pypdf.errors import PdfStreamError
except ImportError:
    raise ImportError("`pypdf` not installed. Please install it via `pip install pypdf`.")


PAGE_START_NUMBERING_FORMAT_DEFAULT = "<start page {page_nr}>"
PAGE_END_NUMBERING_FORMAT_DEFAULT = "<end page {page_nr}>"
PAGE_NUMBERING_CORRECTNESS_RATIO_FOR_REMOVAL = 0.4


def process_image_page(doc_name: str, page_number: int, page: Any) -> Document:
    try:
        import rapidocr_onnxruntime as rapidocr
    except ImportError:
        raise ImportError(
            "`rapidocr_onnxruntime` not installed. Please install it via `pip install rapidocr_onnxruntime`."
        )
    ocr = rapidocr.RapidOCR()
    page_text = page.extract_text() or ""
    images_text_list = []

    # Extract and process images
    for image_object in page.images:
        image_data = image_object.data

        # Perform OCR on the image
        ocr_result, elapse = ocr(image_data)

        # Extract text from OCR result
        if ocr_result:
            images_text_list += [item[1] for item in ocr_result]

    images_text = "\n".join(images_text_list)
    content = page_text + "\n" + images_text

    # Append the document
    return Document(
        name=doc_name,
        id=str(uuid4()),
        meta_data={"page": page_number},
        content=content,
    )


async def async_process_image_page(doc_name: str, page_number: int, page: Any) -> Document:
    try:
        import rapidocr_onnxruntime as rapidocr
    except ImportError:
        raise ImportError(
            "`rapidocr_onnxruntime` not installed. Please install it via `pip install rapidocr_onnxruntime`."
        )
    ocr = rapidocr.RapidOCR()

    page_text = page.extract_text() or ""
    images_text_list: List = []

    # Process images in parallel
    async def process_image(image_data: bytes) -> List[str]:
        ocr_result, _ = ocr(image_data)
        return [item[1] for item in ocr_result] if ocr_result else []

    image_tasks = [process_image(image.data) for image in page.images]
    images_results = await asyncio.gather(*image_tasks)

    for result in images_results:
        images_text_list.extend(result)

    images_text = "\n".join(images_text_list)
    content = page_text + "\n" + images_text

    return Document(
        name=doc_name,
        id=str(uuid4()),
        meta_data={"page": page_number},
        content=content,
    )


class BasePDFReader(Reader):
    def __init__(self, page_start_numbering_format: Optional[str]=None, page_end_numbering_format: Optional[str]=None, **kwargs):
        if page_start_numbering_format is None:
            page_start_numbering_format = PAGE_START_NUMBERING_FORMAT_DEFAULT
        if page_end_numbering_format is None:
            page_end_numbering_format = PAGE_END_NUMBERING_FORMAT_DEFAULT
        
        self.page_start_numbering_format = page_start_numbering_format
        self.page_end_numbering_format = page_end_numbering_format

        super().__init__(**kwargs)

    def _build_chunked_documents(self, documents: List[Document]) -> List[Document]:
        chunked_documents: List[Document] = []
        for document in documents:
            chunked_documents.extend(self.chunk_document(document))
        return chunked_documents


class PDFReader(BasePDFReader):
    """Reader for PDF files"""

    def read(self, pdf: Union[str, Path, IO[Any]]) -> List[Document]:
        try:
            if isinstance(pdf, str):
                doc_name = pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = pdf.name.split(".")[0]
        except Exception:
            doc_name = "pdf"

        log_info(f"Reading: {doc_name}")

        try:
            doc_reader = DocumentReader(pdf)
        except PdfStreamError as e:
            logger.error(f"Error reading PDF: {e}")
            return []

        pdf_content = []
        for page in doc_reader.pages:
            pdf_content.append(page.extract_text())
        
        pdf_content, shift = _remove_page_numbers(page_content=pdf_content,
            page_start_numbering_format=self.page_start_numbering_format,
            page_end_numbering_format=self.page_end_numbering_format
        )
        shift = shift if shift is not None else 1

        documents: List[Document] = []
        for page_number, page_content in enumerate(pdf_content, start=shift):
            documents.append(
                Document(
                    name=doc_name,
                    id=str(uuid4()),
                    meta_data={"page": page_number},
                    content=page_content,
                )
            )

        if self.chunk:
            return self._build_chunked_documents(documents)
        return documents

    async def async_read(self, pdf: Union[str, Path, IO[Any]]) -> List[Document]:
        try:
            if isinstance(pdf, str):
                doc_name = pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = pdf.name.split(".")[0]
        except Exception:
            doc_name = "pdf"

        log_info(f"Reading: {doc_name}")

        try:
            doc_reader = DocumentReader(pdf)
        except PdfStreamError as e:
            logger.error(f"Error reading PDF: {e}")
            return []

        async def _process_document(doc_name: str, page_number: int, page: Any) -> Document:
            return Document(
                name=doc_name,
                id=str(uuid4()),
                meta_data={"page": page_number},
                content=page.extract_text(),
            )

        # Process pages in parallel using asyncio.gather
        documents = await asyncio.gather(
            *[
                _process_document(doc_name, page_number, page)
                for page_number, page in enumerate(doc_reader.pages, start=1)
            ]
        )

        if self.chunk:
            return self._build_chunked_documents(documents)
        return documents


class PDFUrlReader(BasePDFReader):
    """Reader for PDF files from URL"""

    def __init__(self, proxy: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.proxy = proxy

    def read(self, url: str) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        from io import BytesIO

        log_info(f"Reading: {url}")

        # Retry the request up to 3 times with exponential backoff
        response = fetch_with_retry(url, proxy=self.proxy)

        doc_name = url.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
        doc_reader = DocumentReader(BytesIO(response.content))

        documents = []
        for page_number, page in enumerate(doc_reader.pages, start=1):
            documents.append(
                Document(
                    name=doc_name,
                    id=f"{doc_name}_{page_number}",
                    meta_data={"page": page_number},
                    content=page.extract_text(),
                )
            )
        if self.chunk:
            return self._build_chunked_documents(documents)
        return documents

    async def async_read(self, url: str) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        from io import BytesIO

        import httpx

        log_info(f"Reading: {url}")

        client_args = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(**client_args) as client:  # type: ignore
            response = await async_fetch_with_retry(url, client=client)

        doc_name = url.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
        doc_reader = DocumentReader(BytesIO(response.content))

        async def _process_document(doc_name: str, page_number: int, page: Any) -> Document:
            return Document(
                name=doc_name,
                id=f"{doc_name}_{page_number}",
                meta_data={"page": page_number},
                content=page.extract_text(),
            )

        # Process pages in parallel using asyncio.gather
        documents = await asyncio.gather(
            *[
                _process_document(doc_name, page_number, page)
                for page_number, page in enumerate(doc_reader.pages, start=1)
            ]
        )

        if self.chunk:
            return self._build_chunked_documents(documents)
        return documents


class PDFImageReader(BasePDFReader):
    """Reader for PDF files with text and images extraction"""

    def read(self, pdf: Union[str, Path, IO[Any]]) -> List[Document]:
        if not pdf:
            raise ValueError("No pdf provided")

        try:
            if isinstance(pdf, str):
                doc_name = pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = pdf.name.split(".")[0]
        except Exception:
            doc_name = "pdf"

        log_info(f"Reading: {doc_name}")
        doc_reader = DocumentReader(pdf)

        documents = []
        for page_number, page in enumerate(doc_reader.pages, start=1):
            documents.append(process_image_page(doc_name, page_number, page))

        if self.chunk:
            return self._build_chunked_documents(documents)

        return documents

    async def async_read(self, pdf: Union[str, Path, IO[Any]]) -> List[Document]:
        if not pdf:
            raise ValueError("No pdf provided")

        try:
            if isinstance(pdf, str):
                doc_name = pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = pdf.name.split(".")[0]
        except Exception:
            doc_name = "pdf"

        log_info(f"Reading: {doc_name}")
        doc_reader = DocumentReader(pdf)

        documents = await asyncio.gather(
            *[
                async_process_image_page(doc_name, page_number, page)
                for page_number, page in enumerate(doc_reader.pages, start=1)
            ]
        )

        if self.chunk:
            return self._build_chunked_documents(documents)
        return documents


class PDFUrlImageReader(BasePDFReader):
    """Reader for PDF files from URL with text and images extraction"""

    def __init__(self, proxy: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.proxy = proxy

    def read(self, url: str) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        from io import BytesIO

        import httpx

        # Read the PDF from the URL
        log_info(f"Reading: {url}")
        response = httpx.get(url, proxy=self.proxy) if self.proxy else httpx.get(url)

        doc_name = url.split("/")[-1].split(".")[0].replace(" ", "_")
        doc_reader = DocumentReader(BytesIO(response.content))

        documents = []
        for page_number, page in enumerate(doc_reader.pages, start=1):
            documents.append(process_image_page(doc_name, page_number, page))

        # Optionally chunk documents
        if self.chunk:
            return self._build_chunked_documents(documents)

        return documents

    async def async_read(self, url: str) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        from io import BytesIO

        import httpx

        log_info(f"Reading: {url}")

        client_args = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(**client_args) as client:  # type: ignore
            response = await client.get(url)
            response.raise_for_status()

        doc_name = url.split("/")[-1].split(".")[0].replace(" ", "_")
        doc_reader = DocumentReader(BytesIO(response.content))

        documents = await asyncio.gather(
            *[
                async_process_image_page(doc_name, page_number, page)
                for page_number, page in enumerate(doc_reader.pages, start=1)
            ]
        )

        if self.chunk:
            return self._build_chunked_documents(documents)
        return documents

def _remove_page_numbers(
        page_content_list: List[str],
        page_start_numbering_format: str,
        page_end_numbering_format: str
    ) -> Tuple[List[str], Optional[int]]:
    """
    Identifies and removes page numbers from a list of PDF page contents, based on the most consistent sequential numbering.

    This function analyzes potential page numbers located at the beginning or end of each page's content.
    It attempts to find the most likely starting point of page numbering by checking several possible starting indices
    and ranges of numbers. The function removes page numbers if the sequence meets a predefined threshold of correctness.
    Additionally, it can add formatted page numbering based on provided templates.



    Args:
        page_content_list (List[str]): A list of strings where each string represents the content of a PDF page.
        page_start_numbering_format (str): A format string to prepend to the page content, with `{page_nr}` as a placeholder for the page number.
        page_end_numbering_format (str): A format string to append to the page content, with `{page_nr}` as a placeholder for the page number.

    Returns:
        List[str]: The list of page contents with page numbers removed or reformatted based on the detected sequence.
        Optional[Int]: The shift for the page numbering. Can be (-2, -1, 0, 1, 2).

    Notes:
        - The function scans for page numbers using a regular expression that matches digits at the start or end of a string.
        - It evaluates several potential starting points for numbering (-2, -1, 0, 1, 2 shifts) to determine the most consistent sequence.
        - If at least a specified ratio of pages (defined by `PAGE_NUMBERING_CORRECTNESS_RATIO_FOR_REMOVAL`) has correct sequential numbering, 
          the page numbers are removed.
        - The function can optionally add formatted page numbers to each page's content if `page_start_numbering_format` or 
          `page_end_numbering_format` is provided.
    """
    # Regex to match potential page numbers at the start or end of a string
    page_number_regex = re.compile(r'^\s*(\d+)\s*|\s*(\d+)\s*$')

    def find_page_number(content):
        match = page_number_regex.search(content)
        if match:
            return int(match.group(1) or match.group(2))
        return None

    page_numbers = [find_page_number(content) for content in page_content_list]

    # Possible range shifts to detect page numbering
    range_shifts = [-2, -1, 0, 1, 2]
    best_match = None
    best_shift = None
    best_correct_count = 0

    for shift in range_shifts:
        expected_numbers = [i + shift for i in range(len(page_numbers))]
        # Check if expected number occurs (or that the expected "2" occurs in an incorrectly merged number like 25,
        # where 2 is the page number and 5 is part of the PDF content).
        correct_count = sum(1 for actual, expected in zip(page_numbers, expected_numbers) if actual == expected or str(expected) in str(actual))

        if correct_count > best_correct_count:
            best_correct_count = correct_count
            best_match = expected_numbers
            best_shift = shift

    # Check if at least ..% of the pages have correct sequential numbering
    if best_match and best_correct_count / len(page_numbers) >= PAGE_NUMBERING_CORRECTNESS_RATIO_FOR_REMOVAL:
        # Remove the page numbers from the content
        for i, expected_number in enumerate(best_match):
            page_content_list[i] = re.sub(f'^\s*{expected_number}\s*|\s*{expected_number}\s*$', '', page_content_list[i])

            # Add formatted page numbering if configured.
            page_content_list[i] = (
                (page_start_numbering_format.format(page_nr=expected_number) + " " if page_start_numbering_format else "") +
                page_content_list[i] +
                (" " + page_end_numbering_format.format(page_nr=expected_number) if page_end_numbering_format else "")
            )

    return page_content_list, best_shift
