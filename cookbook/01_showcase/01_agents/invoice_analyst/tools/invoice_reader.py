"""
Invoice Reader Tool
===================

Reads invoice documents and prepares them for vision-based extraction.
Supports PDF files and images (PNG, JPG, JPEG).
"""

import base64
from pathlib import Path
from typing import Optional

from agno.utils.log import logger

# Optional PDF to image conversion
try:
    from pdf2image import convert_from_path

    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning(
        "pdf2image not installed. PDF support requires: pip install pdf2image"
    )

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow not installed. Image support requires: pip install Pillow")


# ============================================================================
# Invoice Reader Tool
# ============================================================================
def read_invoice(
    file_path: str,
    max_pages: int = 3,
    dpi: int = 200,
) -> dict:
    """Read an invoice document and prepare it for vision-based extraction.

    Supports:
    - PDF files (converted to images)
    - Image files (PNG, JPG, JPEG)

    Args:
        file_path: Path to the invoice file.
        max_pages: Maximum number of pages to process for PDFs.
        dpi: Resolution for PDF to image conversion.

    Returns:
        Dictionary with:
        - images: List of base64-encoded images
        - metadata: File information
        - error: Error message if any
    """
    path = Path(file_path)

    if not path.exists():
        return {"error": f"File not found: {file_path}", "images": [], "metadata": {}}

    suffix = path.suffix.lower()

    # Handle PDF files
    if suffix == ".pdf":
        return _read_pdf_invoice(path, max_pages, dpi)

    # Handle image files
    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}:
        return _read_image_invoice(path)

    return {
        "error": f"Unsupported file type: {suffix}. Supported: .pdf, .png, .jpg, .jpeg",
        "images": [],
        "metadata": {},
    }


def _read_pdf_invoice(path: Path, max_pages: int, dpi: int) -> dict:
    """Read a PDF invoice and convert to images."""
    if not PDF2IMAGE_AVAILABLE:
        return {
            "error": "PDF support requires pdf2image. Install: pip install pdf2image",
            "images": [],
            "metadata": {},
        }

    try:
        logger.info(f"Converting PDF to images: {path.name} (dpi={dpi})")

        # Convert PDF pages to images
        images = convert_from_path(
            str(path),
            dpi=dpi,
            first_page=1,
            last_page=max_pages,
        )

        # Encode images as base64
        encoded_images = []
        for i, img in enumerate(images):
            import io

            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
            encoded_images.append(
                {"page": i + 1, "data": encoded, "format": "image/png"}
            )

        logger.info(f"Converted {len(encoded_images)} pages from PDF")

        return {
            "images": encoded_images,
            "metadata": {
                "filename": path.name,
                "type": "pdf",
                "pages": len(encoded_images),
                "dpi": dpi,
            },
            "error": None,
        }

    except Exception as e:
        logger.error(f"Error reading PDF {path}: {e}")
        return {"error": f"Error reading PDF: {e}", "images": [], "metadata": {}}


def _read_image_invoice(path: Path) -> dict:
    """Read an image invoice."""
    if not PIL_AVAILABLE:
        return {
            "error": "Image support requires Pillow. Install: pip install Pillow",
            "images": [],
            "metadata": {},
        }

    try:
        logger.info(f"Reading image: {path.name}")

        # Open and encode image
        with Image.open(path) as img:
            # Convert to RGB if necessary
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # Encode as base64
            import io

            buffer = io.BytesIO()
            img_format = "PNG" if path.suffix.lower() == ".png" else "JPEG"
            img.save(buffer, format=img_format)
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")

            mime_type = "image/png" if img_format == "PNG" else "image/jpeg"

            return {
                "images": [{"page": 1, "data": encoded, "format": mime_type}],
                "metadata": {
                    "filename": path.name,
                    "type": "image",
                    "size": img.size,
                    "format": img_format,
                },
                "error": None,
            }

    except Exception as e:
        logger.error(f"Error reading image {path}: {e}")
        return {"error": f"Error reading image: {e}", "images": [], "metadata": {}}


def get_invoice_as_message_content(file_path: str) -> Optional[list]:
    """Get invoice images formatted for LLM message content.

    Args:
        file_path: Path to the invoice file.

    Returns:
        List of content blocks for LLM message, or None if error.
    """
    result = read_invoice(file_path)

    if result.get("error"):
        return None

    content = []

    # Add text description
    metadata = result.get("metadata", {})
    content.append(
        {
            "type": "text",
            "text": f"Invoice document: {metadata.get('filename', 'unknown')} "
            f"({metadata.get('pages', 1)} page(s))",
        }
    )

    # Add images
    for img_data in result.get("images", []):
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img_data["format"],
                    "data": img_data["data"],
                },
            }
        )

    return content
