from pathlib import Path
from time import sleep
from typing import IO, Any, List, Union

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import logger

try:
    from pypdf import PdfReader as DocumentReader  # noqa: F401
except ImportError:
    raise ImportError("`pypdf` not installed. Please install it via `pip install pypdf`.")


class PDFReader(Reader):
    """Reader for PDF files"""

    def read(self, pdf: Union[str, Path, IO[Any]]) -> List[Document]:
        doc_name = ""
        try:
            if isinstance(pdf, str):
                doc_name = pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = pdf.name.split(".")[0]
        except Exception:
            doc_name = "pdf"

        logger.info(f"Reading: {doc_name}")
        doc_reader = DocumentReader(pdf)

        documents = [
            Document(
                name=doc_name,
                id=f"{doc_name}_{page_number}",
                meta_data={"page": page_number},
                content=page.extract_text(),
            )
            for page_number, page in enumerate(doc_reader.pages, start=1)
        ]
        if self.chunk:
            chunked_documents = []
            for document in documents:
                chunked_documents.extend(self.chunk_document(document))
            return chunked_documents
        return documents


class PDFUrlReader(Reader):
    """Reader for PDF files from URL"""

    def read(self, url: str) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        from io import BytesIO

        try:
            import httpx
        except ImportError:
            raise ImportError("`httpx` not installed. Please install it via `pip install httpx`.")

        logger.info(f"Reading: {url}")
        # Retry the request up to 3 times with exponential backoff
        for attempt in range(3):
            try:
                response = httpx.get(url)
                break
            except httpx.RequestError as e:
                if attempt == 2:  # Last attempt
                    logger.error(f"Failed to fetch PDF after 3 attempts: {e}")
                    raise
                wait_time = 2**attempt  # Exponential backoff: 1, 2, 4 seconds
                logger.warning(f"Request failed, retrying in {wait_time} seconds...")
                sleep(wait_time)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
            raise

        doc_name = url.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
        doc_reader = DocumentReader(BytesIO(response.content))

        documents = [
            Document(
                name=doc_name,
                id=f"{doc_name}_{page_number}",
                meta_data={"page": page_number},
                content=page.extract_text(),
            )
            for page_number, page in enumerate(doc_reader.pages, start=1)
        ]
        if self.chunk:
            chunked_documents = []
            for document in documents:
                chunked_documents.extend(self.chunk_document(document))
            return chunked_documents
        return documents


class PDFImageReader(Reader):
    """Reader for PDF files with text and images extraction"""

    def read(self, pdf: Union[str, Path, IO[Any]]) -> List[Document]:
        if not pdf:
            raise ValueError("No pdf provided")

        try:
            import rapidocr_onnxruntime as rapidocr
        except ImportError:
            raise ImportError(
                "`rapidocr_onnxruntime` not installed. Please install it via `pip install rapidocr_onnxruntime`."
            )

        doc_name = ""
        try:
            if isinstance(pdf, str):
                doc_name = pdf.split("/")[-1].split(".")[0].replace(" ", "_")
            else:
                doc_name = pdf.name.split(".")[0]
        except Exception:
            doc_name = "pdf"

        logger.info(f"Reading: {doc_name}")
        doc_reader = DocumentReader(pdf)

        # Initialize RapidOCR
        ocr = rapidocr.RapidOCR()

        documents = []
        for page_number, page in enumerate(doc_reader.pages, start=1):
            page_text = page.extract_text() or ""
            images_text_list: List = []

            for image_object in page.images:
                image_data = image_object.data

                # Perform OCR on the image
                ocr_result, elapse = ocr(image_data)

                # Extract text from OCR result
                if ocr_result:
                    images_text_list += [item[1] for item in ocr_result]

            images_text: str = "\n".join(images_text_list)
            content = page_text + "\n" + images_text

            documents.append(
                Document(
                    name=doc_name,
                    id=f"{doc_name}_{page_number}",
                    meta_data={"page": page_number},
                    content=content,
                )
            )

        if self.chunk:
            chunked_documents = []
            for document in documents:
                chunked_documents.extend(self.chunk_document(document))
            return chunked_documents

        return documents


class PDFUrlImageReader(Reader):
    """Reader for PDF files from URL with text and images extraction"""

    def read(self, url: str) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        from io import BytesIO

        try:
            import httpx
            import rapidocr_onnxruntime as rapidocr
        except ImportError:
            raise ImportError(
                "`httpx`, `rapidocr_onnxruntime` not installed. Please install it via `pip install httpx rapidocr_onnxruntime`."
            )

        # Read the PDF from the URL
        logger.info(f"Reading: {url}")
        response = httpx.get(url)

        doc_name = url.split("/")[-1].split(".")[0].replace(" ", "_")
        doc_reader = DocumentReader(BytesIO(response.content))

        # Initialize RapidOCR
        ocr = rapidocr.RapidOCR()

        # Process each page of the PDF
        documents = []
        for page_number, page in enumerate(doc_reader.pages, start=1):
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
            documents.append(
                Document(
                    name=doc_name,
                    id=f"{doc_name}_{page_number}",
                    meta_data={"page": page_number},
                    content=content,
                )
            )

        # Optionally chunk documents
        if self.chunk:
            chunked_documents = []
            for document in documents:
                chunked_documents.extend(self.chunk_document(document))
            return chunked_documents

        return documents
