"""Pydantic models for all API request/response schemas."""

from pydantic import BaseModel, Field
from typing import Any, Optional
from enum import Enum


class DocumentType(str, Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    FORM = "form"
    CONTRACT = "contract"
    ID_CARD = "id_card"
    BANK_STATEMENT = "bank_statement"
    PURCHASE_ORDER = "purchase_order"
    AUTO = "auto" #auto detect 


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    page: int = 1


class TextBlock(BaseModel):
    text: str
    confidence: float
    bbox: BoundingBox
    block_type: str = "text"  # text | table_cell | header | footer


class TableCell(BaseModel):
    row: int
    col: int
    text: str
    confidence: float
    merged: bool = False


class ExtractedTable(BaseModel):
    table_index: int
    page: int
    headers: list[str]
    rows: list[list[str]]
    raw_cells: list[TableCell]
    confidence: float


class ExtractionResult(BaseModel):
    document_type: str
    detected_type: str
    confidence_score: float = Field(..., ge=0, le=1)
    page_count: int
    processing_time_ms: float

    # Structured fields (document-type specific)
    fields: dict[str, Any]

    # Tables
    tables: list[ExtractedTable] = []

    # Raw OCR blocks (for debugging / custom parsing)
    raw_blocks: list[TextBlock] = []

    # File info
    filename: str
    file_size_bytes: int


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[str] = None


class FineTuneRequest(BaseModel):
    document_type: str = Field(..., description="Custom document type name, e.g. 'medical_prescription'")
    field_definitions: dict[str, str] = Field(
        ...,
        description="Map of field_name → regex_or_description, e.g. {'patient_name': 'Name of patient after Patient:'}"
    )
    sample_texts: list[str] = Field(
        ...,
        description="Sample raw OCR text strings from your document type (5–50 examples)"
    )


class FineTuneResponse(BaseModel):
    document_type: str
    fields_registered: list[str]
    pattern_count: int
    status: str
    message: str
