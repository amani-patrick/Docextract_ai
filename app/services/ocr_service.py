"""
Core OCR service.
Primary engine: PaddleOCR (best accuracy, supports rotated text, multilingual)
Fallback engine: pytesseract (simpler scans, always available)
PDF support: pdf2image → per-page images → OCR each page
"""

import os
import logging
import time
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image
import numpy as np

from app.models.responses import TextBlock, BoundingBox

logger = logging.getLogger("docuextract.ocr")

# ── Lazy-load heavy OCR engines ────────────────────────────────────────────────
_paddle_ocr = None
_tesseract_available = False


def _get_paddle():
    global _paddle_ocr
    if _paddle_ocr is None:
        try:
            from paddleocr import PaddleOCR
            _paddle_ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            logger.info("PaddleOCR engine loaded")
        except ImportError:
            logger.warning("PaddleOCR not installed — will use pytesseract only")
    return _paddle_ocr


def _tesseract_available_check() -> bool:
    global _tesseract_available
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        _tesseract_available = True
    except Exception:
        _tesseract_available = False
    return _tesseract_available


# ── PDF → images ───────────────────────────────────────────────────────────────
def pdf_to_images(pdf_path: str, dpi: int = 200) -> list[Image.Image]:
    """
    Convert each PDF page to a PIL Image.
    Uses pdf2image (poppler). Falls back to PyMuPDF if poppler unavailable.
    """
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path, dpi=dpi)
        logger.info(f"pdf2image: converted {len(images)} pages at {dpi}dpi")
        return images
    except Exception as e:
        logger.warning(f"pdf2image failed ({e}), trying PyMuPDF...")
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            images = []
            for page in doc:
                mat = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
            doc.close()
            logger.info(f"PyMuPDF: converted {len(images)} pages")
            return images
        except Exception as e2:
            raise RuntimeError(f"Cannot convert PDF to images. Install pdf2image+poppler or pymupdf. Errors: {e} | {e2}")


# ── Per-image OCR ──────────────────────────────────────────────────────────────
def ocr_image_paddle(image: Image.Image, page_num: int = 1) -> list[TextBlock]:
    """Run PaddleOCR on a PIL image, return TextBlock list."""
    ocr = _get_paddle()
    if ocr is None:
        return ocr_image_tesseract(image, page_num)

    img_array = np.array(image)
    result = ocr.ocr(img_array, cls=True)

    blocks = []
    if not result or result[0] is None:
        return blocks

    for line in result[0]:
        try:
            bbox_pts, (text, conf) = line
            # bbox_pts: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            xs = [p[0] for p in bbox_pts]
            ys = [p[1] for p in bbox_pts]
            bbox = BoundingBox(
                x1=min(xs), y1=min(ys),
                x2=max(xs), y2=max(ys),
                page=page_num,
            )
            blocks.append(TextBlock(
                text=text.strip(),
                confidence=round(float(conf), 4),
                bbox=bbox,
            ))
        except Exception as e:
            logger.debug(f"Skipping malformed OCR line: {e}")

    return blocks


def ocr_image_tesseract(image: Image.Image, page_num: int = 1) -> list[TextBlock]:
    """Fallback: pytesseract OCR with bounding box data."""
    try:
        import pytesseract
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except Exception as e:
        logger.error(f"Tesseract OCR failed: {e}")
        return []

    blocks = []
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        conf = int(data["conf"][i])
        if not text or conf < 0:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        blocks.append(TextBlock(
            text=text,
            confidence=round(conf / 100, 4),
            bbox=BoundingBox(x1=x, y1=y, x2=x + w, y2=y + h, page=page_num),
        ))
    return blocks


# ── Image preprocessing ────────────────────────────────────────────────────────
def preprocess_image(image: Image.Image) -> Image.Image:
    """
    Enhance image for better OCR accuracy:
    - Convert to RGB
    - Upscale small images
    - (Optional) deskew, denoise — add cv2 steps here if needed
    """
    image = image.convert("RGB")
    w, h = image.size
    if max(w, h) < 1000:
        scale = 1500 / max(w, h)
        image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        logger.debug(f"Upscaled image from {w}x{h} → {image.size}")
    return image


# ── Main entry point ───────────────────────────────────────────────────────────
def extract_blocks_from_file(
    file_path: str,
    engine: str = "paddle",  # "paddle" | "tesseract" | "auto"
) -> tuple[list[TextBlock], int]:
    """
    Given a file path (PDF or image), return (all_text_blocks, page_count).
    Handles multi-page PDFs by OCR-ing each page.
    """
    suffix = Path(file_path).suffix.lower()
    all_blocks: list[TextBlock] = []

    if suffix == ".pdf":
        images = pdf_to_images(file_path)
        page_count = len(images)
        for page_num, image in enumerate(images, start=1):
            image = preprocess_image(image)
            if engine == "tesseract":
                blocks = ocr_image_tesseract(image, page_num)
            else:
                blocks = ocr_image_paddle(image, page_num)
            all_blocks.extend(blocks)
    else:
        image = Image.open(file_path)
        image = preprocess_image(image)
        if engine == "tesseract":
            blocks = ocr_image_tesseract(image, page_num=1)
        else:
            blocks = ocr_image_paddle(image, page_num=1)
        all_blocks = blocks
        page_count = 1

    logger.info(f"OCR complete: {len(all_blocks)} blocks across {page_count} page(s)")
    return all_blocks, page_count
