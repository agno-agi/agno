import base64
import os
import tempfile
import uuid
from typing import List, Optional

import fitz # type: ignore

from agno.knowledge.document.base import Document
from agno.knowledge.reader.pdf_reader import BasePDFReader
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.utils.log import log_debug, log_error


def img_to_base64(bytes_data: bytes) -> str:
    return base64.b64encode(bytes_data).decode("utf-8")


class VllmPDFReader(BasePDFReader):
    """
    Multimodal PDF reader for Agno using VLLM.
    Extracts text + images + vision captions.
    """

    def __init__(self, vllm: OpenAIChat, chunking_strategy=None, **kwargs):
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)
        self.vllm = vllm

    @classmethod
    def get_supported_content_types(cls):
        return ["pdf"]

    def read(self, pdf: str, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        doc_name = name or os.path.basename(pdf)
        log_debug(f"Reading PDF with VLLM: {doc_name}")

        try:
            pdf_reader = fitz.open(pdf)
        except Exception as e:
            log_error(f"Failed to open PDF: {e}")
            return []

        documents: List[Document] = []
        tmp_dir = tempfile.mkdtemp(prefix="pdf_img_")

        for page_index, page in enumerate(pdf_reader):
            text = page.get_text("text") or ""
            text = text.strip()
            if text:
                documents.append(
                    Document(
                        name=doc_name,
                        id=str(uuid.uuid4()),
                        content=text,
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
                    log_error(f"VLLM caption generation failed: {e}")
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
