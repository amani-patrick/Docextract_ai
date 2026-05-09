"""
/api/v1/extract — Document extraction endpoint.
Accepts: PDF, PNG, JPG, TIFF, BMP, WEBP
Returns: Structured JSON with fields, tables, raw blocks.
"""

import os
import time
import uuid
import shutil
import logging
# import json 
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from app.models.responses import ExtractionResult, DocumentType, ErrorResponse
from app.services.ocr_service import extract_blocks_from_file
from app.services.table_extractor import extract_tables
from app.services.field_extractor import extract_fields

logger = logging.getLogger("docuextract.router")
router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
MAX_FILE_SIZE_MB = 50


def _validate_file(file: UploadFile) -> None:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )


def _cleanup(path: str):
    try:
        os.remove(path)
    except Exception:
        pass


@router.post(
    "/extract",
    response_model=ExtractionResult,
    summary="Extract structured data from a document",
    description="""
Upload a PDF or image file to extract structured fields, tables, and raw OCR text.

**Supported document types:**
- `invoice` — invoice number, dates, totals, line items
- `receipt` — store, total, payment method, transaction ID
- `form` — generic key:value pair extraction
- `contract` — parties, dates, contract value, governing law
- `id_card` — name, ID number, DOB, nationality
- `bank_statement` — account details, balances, period
- `purchase_order` — PO number, vendor, ship-to, total
- `auto` — auto-detect document type (recommended)

**Custom document types** can be registered via `POST /api/v1/finetune/register`.
""",
)
async def extract_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF or image file to process"),
    document_type: DocumentType = Form(
        default=DocumentType.AUTO,
        description="Document type. Use 'auto' to auto-detect."
    ),
    ocr_engine: str = Form(
        default="paddle",
        description="OCR engine: 'paddle' (default, best accuracy) or 'tesseract' (fallback)"
    ),
    extract_tables_flag: bool = Form(
        default=True,
        description="Whether to extract tables from the document"
    ),
):
    _validate_file(file)

    # Save uploaded file to temp location
    suffix = Path(file.filename or "doc").suffix.lower()
    tmp_path = f"/tmp/docuextract_{uuid.uuid4()}{suffix}"
    file_size = 0

    try:
        with open(tmp_path, "wb") as f:
            chunk_size = 1024 * 1024  # 1MB chunks
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Maximum size: {MAX_FILE_SIZE_MB}MB"
                    )
    except HTTPException:
        _cleanup(tmp_path)
        raise

    # Schedule cleanup regardless of outcome
    background_tasks.add_task(_cleanup, tmp_path)

    # ── OCR ────────────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        blocks, page_count = extract_blocks_from_file(
            tmp_path,
            engine=ocr_engine if ocr_engine in ("paddle", "tesseract") else "paddle"
        )
    except Exception as e:
        logger.exception("OCR failed")
        raise HTTPException(status_code=422, detail=f"OCR processing failed: {str(e)}")

    # ── Field extraction ───────────────────────────────────────────────────────
    try:
        fields, detected_type, field_confidence = extract_fields(
            blocks,
            doc_type=document_type.value,
            auto_detect=(document_type == DocumentType.AUTO),
        )
    except Exception as e:
        logger.exception("Field extraction failed")
        fields, detected_type, field_confidence = {}, "unknown", 0.0

    # ── Table extraction ───────────────────────────────────────────────────────
    tables = []
    if extract_tables_flag:
        try:
            tables = extract_tables(blocks)
        except Exception as e:
            logger.warning(f"Table extraction failed (non-fatal): {e}")

    processing_time_ms = round((time.perf_counter() - t0) * 1000, 1)

    return ExtractionResult(
        document_type=document_type.value,
        detected_type=detected_type,
        confidence_score=field_confidence,
        page_count=page_count,
        processing_time_ms=processing_time_ms,
        fields=fields,
        tables=tables,
        raw_blocks=blocks,
        filename=file.filename or "unknown",
        file_size_bytes=file_size,
    )


@router.post(
    "/extract/batch",
    summary="Batch extract from multiple documents",
    description="Upload up to 10 files for sequential extraction. Returns a list of results."
)
async def extract_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(..., description="Up to 10 PDF or image files"),
    document_type: DocumentType = Form(default=DocumentType.AUTO),
):
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files per batch request.")

    results = []
    for f in files:
        try:
            result = await extract_document(
                background_tasks=background_tasks,
                file=f,
                document_type=document_type,
                ocr_engine="paddle",
                extract_tables_flag=True,
            )
            results.append({"filename": f.filename, "status": "success", "data": result})
        except HTTPException as e:
            results.append({"filename": f.filename, "status": "error", "detail": e.detail})
        except Exception as e:
            results.append({"filename": f.filename, "status": "error", "detail": str(e)})

    return {"batch_size": len(files), "results": results}
