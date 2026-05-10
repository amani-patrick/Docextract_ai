"""Health check endpoints."""

import sys
import platform
# pyrefly: ignore[missing-import]
from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter()

START_TIME = datetime.now(timezone.utc)


@router.get("/health", summary="Health check")
async def health():
    uptime_seconds = (datetime.now(timezone.utc) - START_TIME).total_seconds()
    return {
        "status": "healthy",
        "service": "DocuExtract AI",
        "version": "1.0.0",
        "uptime_seconds": round(uptime_seconds, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.system(),
    }


@router.get("/health/engines", summary="Check OCR engine availability")
async def engine_health():
    engines = {}

    # Check PaddleOCR
    try:
        # pyrefly: ignore [import-not-found, missing-import]
        import paddleocr  # noqa    
        engines["paddleocr"] = {"available": True, "version": getattr(paddleocr, "__version__", "unknown")}
    except ImportError:
        engines["paddleocr"] = {"available": False, "reason": "Not installed"}

    # Check pytesseract
    try:
        # pyrefly: ignore [missing-import]
        import pytesseract
        version = pytesseract.get_tesseract_version()
        engines["tesseract"] = {"available": True, "version": str(version)}
    except Exception as e:
        engines["tesseract"] = {"available": False, "reason": str(e)}

    # Check pdf2image
    try:
        # pyrefly: ignore [missing-import]
        import pdf2image  # noqa
        engines["pdf2image"] = {"available": True}
    except ImportError:
        engines["pdf2image"] = {"available": False, "reason": "Not installed — install pdf2image + poppler"}

    # Check PyMuPDF
    try:
        # pyrefly: ignore [missing-import]
        import fitz  # noqa
        engines["pymupdf"] = {"available": True, "version": fitz.version[0]}
    except ImportError:
        engines["pymupdf"] = {"available": False, "reason": "Not installed"}

    any_ocr = engines.get("paddleocr", {}).get("available") or engines.get("tesseract", {}).get("available")
    any_pdf = engines.get("pdf2image", {}).get("available") or engines.get("pymupdf", {}).get("available")

    return {
        "engines": engines,
        "ready": {
            "ocr": any_ocr,
            "pdf_support": any_pdf,
            "fully_operational": any_ocr and any_pdf,
        }
    }
