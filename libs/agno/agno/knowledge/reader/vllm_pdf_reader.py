import asyncio
import base64
import os
import tempfile
import uuid
from typing import List, Optional

import fitz  # type: ignore

from agno.knowledge.document.base import Document
from agno.knowledge.reader.pdf_reader import BasePDFReader
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.utils.log import log_debug, log_error


def img_to_base64(bytes_data: bytes) -> str:
    """Utility: convert raw bytes to a base64-encoded string."""
    return base64.b64encode(bytes_data).decode("utf-8")


class VllmPDFReader(BasePDFReader):
    """
    A multimodal PDF reader for Agno that extracts both text and images
    and generates vision captions using a VLLM/OpenAIChat-compatible model.

    This reader provides:
    - `read()`: synchronous PDF parsing and caption generation
    - `async_read()`: fully asynchronous parsing with concurrent image captioning

    Features:
    - Text is extracted using PyMuPDF (`fitz`)
    - Images are extracted and captioned individually
    - All generated items are returned as `Document` objects
    - Chunking is supported via the BasePDFReader infrastructure
    """

    def __init__(self, vllm: OpenAIChat, chunking_strategy=None, **kwargs):
        """
        Initialize the VLLM PDF reader.

        Args:
            vllm (OpenAIChat):
                A model client capable of producing captions using `.invoke()`.
            chunking_strategy:
                Optional chunking configuration passed to BasePDFReader.
            **kwargs:
                Additional keyword arguments for BasePDFReader.
        """
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)
        self.vllm = vllm

    @classmethod
    def get_supported_content_types(cls):
        """Declare the supported file type for this reader."""
        return ["pdf"]

    def read(self, pdf: str, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        """
        Synchronously parse a PDF file and generate text and image-caption documents.

        Args:
            pdf (str): Path to the PDF file.
            name (str, optional): Override for the document name. Defaults to the PDF filename.
            password (str, optional): Currently unused (no decryption support in this reader).

        Returns:
            List[Document]: A flat list of text and image-caption documents,
            optionally chunked according to the configured chunking strategy.

        Behavior:
            - Reads the PDF sequentially
            - Extracts text from each page
            - Extracts images and generates captions using `vllm.invoke`
            - Any failure in captioning results in a fallback placeholder
        """
        doc_name = name or os.path.basename(pdf)
        log_debug(f"Reading PDF with VLLM (sync): {doc_name}")

        try:
            pdf_reader = fitz.open(pdf)
        except Exception as e:
            log_error(f"Failed to open PDF: {e}")
            return []

        documents: List[Document] = []
        tmp_dir = tempfile.mkdtemp(prefix="pdf_img_")

        for page_index, page in enumerate(pdf_reader):
            text = page.get_text("text") or ""
            if text.strip():
                documents.append(
                    Document(
                        name=doc_name,
                        id=str(uuid.uuid4()),
                        content=text.strip(),
                        meta_data={"type": "text", "page": page_index},
                    )
                )

            for img_ref in page.get_images(full=True):
                xref = img_ref[0]
                image_info = pdf_reader.extract_image(xref)

                img_bytes = image_info["image"]
                img_ext = image_info["ext"]

                img_path = os.path.join(tmp_dir, f"{doc_name}_p{page_index}_{uuid.uuid4()}.{img_ext}")
                with open(img_path, "wb") as f:
                    f.write(img_bytes)

                msg = Message(
                    role="user",
                    content="Describe this image in detail.",
                    images=[{"content": img_bytes, "mime_type": f"image/{img_ext}"}],
                )

                try:
                    assistant_msg = Message(role="assistant", content=None)
                    response = self.vllm.invoke(messages=[msg], assistant_message=assistant_msg)
                    caption = response.content or "(no caption)"
                except Exception as e:
                    log_error(f"Caption generation failed: {e}")
                    caption = "(caption unavailable)"

                documents.append(
                    Document(
                        name=doc_name,
                        id=str(uuid.uuid4()),
                        content=f"[IMAGE CAPTION]\n{caption}",
                        meta_data={"type": "image", "page": page_index, "path": img_path},
                    )
                )

        return self._build_chunked_documents(documents)

    async def async_read(self, pdf: str, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        """
        Asynchronously parse a PDF with full parallelism for image captioning.

        Args:
            pdf (str): Path to the PDF file.
            name (str, optional): Override for the document name.
            password (str, optional): Currently unused.

        Returns:
            List[Document]: A list of text and caption documents, chunked if configured.

        Notes:
            - PyMuPDF (`fitz`) is not async, so PDF loading and extraction is delegated to `asyncio.to_thread`.
            - Each page is processed concurrently.
            - For pages containing multiple images, caption generation is also concurrent.
            - Uses `vllm.invoke()`.
        """
        doc_name = name or os.path.basename(pdf)
        log_debug(f"Reading PDF with VLLM (async): {doc_name}")

        try:
            pdf_reader = await asyncio.to_thread(fitz.open, pdf)
        except Exception as e:
            log_error(f"Failed to open PDF: {e}")
            return []

        tmp_dir = tempfile.mkdtemp(prefix="pdf_img_")

        tasks = [
            self._process_page_async(page_index, page, tmp_dir, doc_name) for page_index, page in enumerate(pdf_reader)
        ]

        pages_docs = await asyncio.gather(*tasks)

        documents: List[Document] = []
        for page_list in pages_docs:
            documents.extend(page_list)

        return self._build_chunked_documents(documents)

    async def _process_page_async(self, page_index, page, tmp_dir, doc_name):
        """
        Process a single PDF page asynchronously:
        - Extract text in a thread
        - Extract images
        - Schedule async captioning tasks

        Returns:
            List[Document]: Text document + zero or more image-caption documents.
        """
        docs: List[Document] = []

        text = await asyncio.to_thread(page.get_text, "text")
        if (text or "").strip():
            docs.append(
                Document(
                    name=doc_name,
                    id=str(uuid.uuid4()),
                    content=text.strip(),
                    meta_data={"type": "text", "page": page_index},
                )
            )

        img_tasks = [
            self._process_image_async(page, page_index, img_ref, tmp_dir, doc_name)
            for img_ref in page.get_images(full=True)
        ]

        if img_tasks:
            docs.extend(await asyncio.gather(*img_tasks))

        return docs

    async def _process_image_async(self, page, page_index, img_ref, tmp_dir, doc_name):
        """
        Extract a single image and generate its caption asynchronously.

        Steps:
            - Extract image bytes (threaded)
            - Save to temporary storage
            - Call `_caption_async()` for vision captioning

        Returns:
            Document: The image-caption document.
        """
        xref = img_ref[0]

        image_info = await asyncio.to_thread(page.parent.extract_image, xref)
        img_bytes = image_info["image"]
        img_ext = image_info["ext"]

        img_path = os.path.join(tmp_dir, f"{doc_name}_p{page_index}_{uuid.uuid4()}.{img_ext}")

        await asyncio.to_thread(self._save_bytes, img_path, img_bytes)

        caption = await self._caption_async(img_bytes, img_ext)

        return Document(
            name=doc_name,
            id=str(uuid.uuid4()),
            content=f"[IMAGE CAPTION]\n{caption}",
            meta_data={"type": "image", "page": page_index, "path": img_path},
        )

    def _save_bytes(self, path, data):
        """Thread-safe helper for writing binary image data to disk."""
        with open(path, "wb") as f:
            f.write(data)

    async def _caption_async(self, img_bytes, img_ext):
        """
        Generate image caption asynchronously using the synchronous `.invoke()` API
        of OpenAIChat. This preserves API compatibility while enabling concurrency.
        """
        msg = Message(
            role="user",
            content="Describe this image in detail.",
            images=[{"content": img_bytes, "mime_type": f"image/{img_ext}"}],
        )

        assistant_msg = Message(role="assistant", content=None)

        try:
            response = await asyncio.to_thread(
                self.vllm.invoke,
                messages=[msg],
                assistant_message=assistant_msg,
            )
            return response.content or "(no caption)"
        except Exception as e:
            log_error(f"Async caption generation failed: {e}")
            return "(caption unavailable)"
