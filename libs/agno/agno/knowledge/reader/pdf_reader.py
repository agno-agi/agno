import asyncio
import re
from pathlib import Path
from typing import IO, Any, List, Optional, Tuple, Union
from uuid import uuid4

from agno.knowledge.chunking.strategy import ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.http import async_fetch_with_retry, fetch_with_retry
from agno.utils.log import log_error, log_info, logger

try:
    from pypdf import PdfReader as DocumentReader  # noqa: F401
    from pypdf.errors import PdfStreamError
except ImportError:
    raise ImportError("`pypdf` not installed. Please install it via `pip install pypdf`.")


PAGE_START_NUMBERING_FORMAT_DEFAULT = "<start page {page_nr}>"
PAGE_END_NUMBERING_FORMAT_DEFAULT = "<end page {page_nr}>"
PAGE_NUMBERING_CORRECTNESS_RATIO_FOR_REMOVAL = 0.4


def _ocr_reader(page: Any) -> str:
    """A single PDF page object."""
    try:
        import rapidocr_onnxruntime as rapidocr
    except ImportError:
        raise ImportError(
            "`rapidocr_onnxruntime` not installed. Please install it via `pip install rapidocr_onnxruntime`."
        )
    ocr = rapidocr.RapidOCR()
    images_text_list = []

    # Extract and process images
    for image_object in page.images:
        image_data = image_object.data

        # Perform OCR on the image
        ocr_result, elapse = ocr(image_data)

        # Extract text from OCR result
        images_text_list += [item[1] for item in ocr_result] if ocr_result else []

    return "\n".join(images_text_list)


async def _async_ocr_reader(page: Any) -> str:
    """page: A single PDF page object."""
    try:
        import rapidocr_onnxruntime as rapidocr
    except ImportError:
        raise ImportError(
            "`rapidocr_onnxruntime` not installed. Please install it via `pip install rapidocr_onnxruntime`."
        )
    ocr = rapidocr.RapidOCR()

    # Process images in parallel
    async def process_image(image_data: bytes) -> List[str]:
        ocr_result, _ = ocr(image_data)
        return [item[1] for item in ocr_result] if ocr_result else []

    image_tasks = [process_image(image.data) for image in page.images]
    images_results = await asyncio.gather(*image_tasks)

    images_text_list: List = []
    for result in images_results:
        images_text_list.extend(result)

    images_text = "\n".join(images_text_list)
    return images_text


def _clean_page_numbers(
    page_content_list: List[str],
    extra_content: List[str] = [],
    page_start_numbering_format: str = PAGE_START_NUMBERING_FORMAT_DEFAULT,
    page_end_numbering_format: str = PAGE_END_NUMBERING_FORMAT_DEFAULT,
) -> Tuple[List[str], Optional[int]]:
    f"""
    Identifies and removes or reformats page numbers from a list of PDF page contents, based on the most consistent sequential numbering.

    Args:
        page_content_list (List[str]): A list of strings where each string represents the content of a PDF page.
        extra_content (List[str]): A list of strings where each string will be appended after the main content. Can be used for appending image information.
        page_start_numbering_format (str): A format string to prepend to the page content, with `{{page_nr}}` as a placeholder for the page number.
            Defaults to {PAGE_START_NUMBERING_FORMAT_DEFAULT}. Make it an empty string to remove the page number.
        page_end_numbering_format (str): A format string to append to the page content, with `{{page_nr}}` as a placeholder for the page number.
            Defaults to {PAGE_END_NUMBERING_FORMAT_DEFAULT}. Make it an empty string to remove the page number.

    Returns:
        List[str]: The list of page contents with page numbers removed or reformatted based on the detected sequence.
        Optional[Int]: The shift for the page numbering. Can be (-2, -1, 0, 1, 2).

    Notes:
        - The function scans for page numbers using a regular expression that matches digits at the start or end of a string.
        - It evaluates several potential starting points for numbering (-2, -1, 0, 1, 2 shifts) to determine the most consistent sequence.
        - If at least a specified ratio of pages (defined by `PAGE_NUMBERING_CORRECTNESS_RATIO_FOR_REMOVAL`) has correct sequential numbering,
          the page numbers are processed.
        - If page numbers are found, the function will add formatted page numbers to each page's content if `page_start_numbering_format` or
          `page_end_numbering_format` is provided.
    """
    assert len(extra_content) == 0 or len(extra_content) == len(page_content_list), (
        "Please provide an equally sized list of extra content if provided."
    )

    # Regex to match potential page numbers at the start or end of a string
    page_number_regex = re.compile(r"^\s*(\d+)\s*|\s*(\d+)\s*$")

    def find_page_number(content):
        match = page_number_regex.search(content)
        if match:
            return int(match.group(1) or match.group(2))
        return None

    page_numbers = [find_page_number(content) for content in page_content_list]
    if all(x is None or x > 5 for x in page_numbers):
        # This approach won't work reliably for higher page numbers.
        return page_content_list, None

    # Possible range shifts to detect page numbering
    range_shifts = [-2, -1, 0, 1, 2]
    best_match, best_correct_count, best_shift = _identify_best_page_sequence(page_numbers, range_shifts)

    # Check if at least ..% of the pages have correct sequential numbering
    if best_match and best_correct_count / len(page_numbers) >= PAGE_NUMBERING_CORRECTNESS_RATIO_FOR_REMOVAL:
        # Remove the page numbers from the content
        for i, expected_number in enumerate(best_match):
            page_content_list[i] = re.sub(
                rf"^\s*{expected_number}\s*|\s*{expected_number}\s*$", "", page_content_list[i]
            )

            page_start = (
                page_start_numbering_format.format(page_nr=expected_number) + "\n"
                if page_start_numbering_format
                else ""
            )
            page_end = (
                "\n" + page_end_numbering_format.format(page_nr=expected_number) if page_end_numbering_format else ""
            )
            extra_info = "\n" + extra_content[i] if extra_content else ""

            # Add formatted page numbering if configured.
            page_content_list[i] = page_start + page_content_list[i] + extra_info + page_end
    else:
        best_shift = None

    return page_content_list, best_shift


def _identify_best_page_sequence(page_numbers, range_shifts):
    best_match = None
    best_shift: Optional[int] = None
    best_correct_count = 0

    for shift in range_shifts:
        expected_numbers = [i + shift for i in range(len(page_numbers))]
        # Check if expected number occurs (or that the expected "2" occurs in an incorrectly merged number like 25,
        # where 2 is the page number and 5 is part of the PDF content).
        correct_count = sum(
            1
            for actual, expected in zip(page_numbers, expected_numbers)
            if actual == expected or str(actual).startswith(str(expected)) or str(actual).endswith(str(expected))
        )

        if correct_count > best_correct_count:
            best_correct_count = correct_count
            best_match = expected_numbers
            best_shift = shift

    return best_match, best_correct_count, best_shift


class BasePDFReader(Reader):
    def __init__(
        self,
        split_on_pages: bool = True,
        page_start_numbering_format: Optional[str] = None,
        page_end_numbering_format: Optional[str] = None,
        password: Optional[str] = None,
        **kwargs,
    ):
        if page_start_numbering_format is None:
            page_start_numbering_format = PAGE_START_NUMBERING_FORMAT_DEFAULT
        if page_end_numbering_format is None:
            page_end_numbering_format = PAGE_END_NUMBERING_FORMAT_DEFAULT

        self.split_on_pages = split_on_pages
        self.page_start_numbering_format = page_start_numbering_format
        self.page_end_numbering_format = page_end_numbering_format
        self.password = password

        if self.chunking_strategy is None:
            from agno.knowledge.chunking.document import DocumentChunking

            self.chunking_strategy = DocumentChunking(chunk_size=5000)
        super().__init__(**kwargs)

    @classmethod
    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for PDF readers."""
        return [
            ChunkingStrategyType.DOCUMENT_CHUNKING,
            ChunkingStrategyType.FIXED_SIZE_CHUNKING,
            ChunkingStrategyType.AGENTIC_CHUNKING,
            ChunkingStrategyType.SEMANTIC_CHUNKING,
            ChunkingStrategyType.RECURSIVE_CHUNKING,
        ]

    def _build_chunked_documents(self, documents: List[Document]) -> List[Document]:
        chunked_documents: List[Document] = []
        for document in documents:
            chunked_documents.extend(self.chunk_document(document))
        return chunked_documents

    def _decrypt_pdf(self, doc_reader: DocumentReader, doc_name: str, password: Optional[str] = None) -> bool:
        if not doc_reader.is_encrypted:
            return True

        # Use provided password or fall back to instance password
        pdf_password = password or self.password
        if not pdf_password:
            logger.error(f"PDF {doc_name} is password protected but no password provided")
            return False

        try:
            decrypted_pdf = doc_reader.decrypt(pdf_password)
            if decrypted_pdf:
                log_info(f"Successfully decrypted PDF {doc_name} with user password")
                return True
            else:
                log_error(f"Failed to decrypt PDF {doc_name}: incorrect password")
                return False
        except Exception as e:
            log_error(f"Error decrypting PDF {doc_name}: {e}")
            return False

    def _create_documents(self, pdf_content: List[str], doc_name: str, use_uuid_for_id: bool, page_number_shift):
        if self.split_on_pages:
            shift = page_number_shift if page_number_shift is not None else 1
            documents: List[Document] = []
            for page_number, page_content in enumerate(pdf_content, start=shift):
                documents.append(
                    Document(
                        name=doc_name,
                        id=(str(uuid4()) if use_uuid_for_id else f"{doc_name}_{page_number}"),
                        meta_data={"page": page_number},
                        content=page_content,
                    )
                )
        else:
            pdf_content_str = "\n".join(pdf_content)
            document = Document(
                name=doc_name,
                id=str(uuid4()) if use_uuid_for_id else doc_name,
                meta_data={},
                content=pdf_content_str,
            )
            documents = [document]

        if self.chunk:
            return self._build_chunked_documents(documents)

        return documents

    def _pdf_reader_to_documents(
        self,
        doc_reader: DocumentReader,
        doc_name,
        read_images=False,
        use_uuid_for_id=False,
    ):
        pdf_content = []
        pdf_images_text = []
        for page in doc_reader.pages:
            pdf_content.append(page.extract_text())
            if read_images:
                pdf_images_text.append(_ocr_reader(page))

        pdf_content, shift = _clean_page_numbers(
            page_content_list=pdf_content,
            extra_content=pdf_images_text,
            page_start_numbering_format=self.page_start_numbering_format,
            page_end_numbering_format=self.page_end_numbering_format,
        )
        return self._create_documents(pdf_content, doc_name, use_uuid_for_id, shift)

    async def _async_pdf_reader_to_documents(
        self,
        doc_reader: DocumentReader,
        doc_name: str,
        read_images=False,
        use_uuid_for_id=False,
    ):
        async def _read_pdf_page(page, read_images) -> Tuple[str, str]:
            # We tried "asyncio.to_thread(page.extract_text)", but it maintains state internally, which leads to issues.
            page_text = page.extract_text()

            if read_images:
                pdf_images_text = await _async_ocr_reader(page)
            else:
                pdf_images_text = ""

            return page_text, pdf_images_text

        # Process pages in parallel using asyncio.gather
        pdf_content: List[Tuple[str, str]] = await asyncio.gather(
            *[_read_pdf_page(page, read_images) for page in doc_reader.pages]
        )

        pdf_content_clean, shift = _clean_page_numbers(
            page_content_list=[x[0] for x in pdf_content],
            extra_content=[x[1] for x in pdf_content],
            page_start_numbering_format=self.page_start_numbering_format,
            page_end_numbering_format=self.page_end_numbering_format,
        )

        return self._create_documents(pdf_content_clean, doc_name, use_uuid_for_id, shift)


class PDFReader(BasePDFReader):
    """Reader for PDF files"""

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.PDF]

    def read(
        self, pdf: Union[str, Path, IO[Any]], name: Optional[str] = None, password: Optional[str] = None
    ) -> List[Document]:
        try:
            if name:
                doc_name = name
            elif isinstance(pdf, str):
                doc_name = pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = pdf.name.split(".")[0]
        except Exception:
            doc_name = "pdf"

        log_info(f"Reading: {doc_name}")

        try:
            DocumentReader(pdf)
        except PdfStreamError as e:
            logger.error(f"Error reading PDF: {e}")
            return []

        try:
            if isinstance(pdf, str):
                doc_name = name or pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = name or pdf.name.split(".")[0]
        except Exception:
            doc_name = name or "pdf"

        log_info(f"Reading: {doc_name}")

        try:
            pdf_reader = DocumentReader(pdf)
        except PdfStreamError as e:
            logger.error(f"Error reading PDF: {e}")
            return []

        # Handle PDF decryption
        if not self._decrypt_pdf(pdf_reader, doc_name, password):
            return []

        # Read and chunk.
        return self._pdf_reader_to_documents(pdf_reader, doc_name, use_uuid_for_id=True)

    async def async_read(
        self,
        pdf: Optional[Union[str, Path, IO[Any]]] = None,
        name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Document]:
        if pdf is None:
            log_error("No pdf provided")
            return []

        try:
            if isinstance(pdf, str):
                doc_name = name or pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = pdf.name.split(".")[0]
        except Exception:
            doc_name = name or "pdf"

        log_info(f"Reading: {doc_name}")

        try:
            pdf_reader = DocumentReader(pdf)
        except PdfStreamError as e:
            logger.error(f"Error reading PDF: {e}")
            return []

        # Handle PDF decryption
        if not self._decrypt_pdf(pdf_reader, doc_name, password):
            return []

        # Read and chunk.
        return await self._async_pdf_reader_to_documents(pdf_reader, doc_name, use_uuid_for_id=True)


class PDFUrlReader(BasePDFReader):
    """Reader for PDF files from URL"""

    def __init__(self, proxy: Optional[str] = None, password: Optional[str] = None, **kwargs):
        super().__init__(password=password, **kwargs)
        self.proxy = proxy

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.URL]

    def read(self, url: str, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        from io import BytesIO

        log_info(f"Reading: {url}")

        # Retry the request up to 3 times with exponential backoff
        response = fetch_with_retry(url, proxy=self.proxy)

        doc_name = name or url.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
        pdf_reader = DocumentReader(BytesIO(response.content))

        # Handle PDF decryption
        if not self._decrypt_pdf(pdf_reader, doc_name, password):
            return []

        # Read and chunk.
        return self._pdf_reader_to_documents(pdf_reader, doc_name, use_uuid_for_id=False)

    async def async_read(self, url: str, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        from io import BytesIO

        import httpx

        log_info(f"Reading: {url}")

        client_args = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(**client_args) as client:  # type: ignore
            response = await async_fetch_with_retry(url, client=client)

        doc_name = name or url.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
        pdf_reader = DocumentReader(BytesIO(response.content))

        # Handle PDF decryption
        if not self._decrypt_pdf(pdf_reader, doc_name, password):
            return []

        # Read and chunk.
        return await self._async_pdf_reader_to_documents(pdf_reader, doc_name, use_uuid_for_id=False)


class PDFImageReader(BasePDFReader):
    """Reader for PDF files with text and images extraction"""

    def read(
        self, pdf: Union[str, Path, IO[Any]], name: Optional[str] = None, password: Optional[str] = None
    ) -> List[Document]:
        if not pdf:
            raise ValueError("No pdf provided")

        try:
            if isinstance(pdf, str):
                doc_name = name or pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = pdf.name.split(".")[0]
        except Exception:
            doc_name = "pdf"

        log_info(f"Reading: {doc_name}")
        pdf_reader = DocumentReader(pdf)

        # Handle PDF decryption
        if not self._decrypt_pdf(pdf_reader, doc_name, password):
            return []

        # Read and chunk.
        return self._pdf_reader_to_documents(pdf_reader, doc_name, read_images=True, use_uuid_for_id=False)

    async def async_read(
        self, pdf: Union[str, Path, IO[Any]], name: Optional[str] = None, password: Optional[str] = None
    ) -> List[Document]:
        if not pdf:
            raise ValueError("No pdf provided")

        try:
            if isinstance(pdf, str):
                doc_name = name or pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = pdf.name.split(".")[0]
        except Exception:
            doc_name = "pdf"

        log_info(f"Reading: {doc_name}")
        pdf_reader = DocumentReader(pdf)

        # Handle PDF decryption
        if not self._decrypt_pdf(pdf_reader, doc_name, password):
            return []

        # Read and chunk.
        return await self._async_pdf_reader_to_documents(pdf_reader, doc_name, read_images=True, use_uuid_for_id=False)


class PDFUrlImageReader(BasePDFReader):
    """Reader for PDF files from URL with text and images extraction"""

    def __init__(self, proxy: Optional[str] = None, password: Optional[str] = None, **kwargs):
        super().__init__(password=password, **kwargs)
        self.proxy = proxy

    def read(self, url: str, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        from io import BytesIO

        import httpx

        # Read the PDF from the URL
        log_info(f"Reading: {url}")
        response = httpx.get(url, proxy=self.proxy) if self.proxy else httpx.get(url)

        doc_name = name or url.split("/")[-1].split(".")[0].replace(" ", "_")
        pdf_reader = DocumentReader(BytesIO(response.content))

        # Handle PDF decryption
        if not self._decrypt_pdf(pdf_reader, doc_name, password):
            return []

        # Read and chunk.
        return self._pdf_reader_to_documents(pdf_reader, doc_name, read_images=True, use_uuid_for_id=False)

    async def async_read(self, url: str, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        from io import BytesIO

        import httpx

        log_info(f"Reading: {url}")

        client_args = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(**client_args) as client:  # type: ignore
            response = await client.get(url)
            response.raise_for_status()

        doc_name = name or url.split("/")[-1].split(".")[0].replace(" ", "_")
        pdf_reader = DocumentReader(BytesIO(response.content))

        # Handle PDF decryption
        if not self._decrypt_pdf(pdf_reader, doc_name, password):
            return []

        # Read and chunk.
        return await self._async_pdf_reader_to_documents(pdf_reader, doc_name, read_images=True, use_uuid_for_id=False)
