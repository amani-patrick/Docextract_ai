"""
DocuExtract AI — Test Suite
Run: pytest tests/ -v --cov=app
"""

import io
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.field_extractor import (
    detect_document_type,
    extract_fields,
    register_custom_type,
    _load_custom_registry,
)
from app.models.responses import TextBlock, BoundingBox

client = TestClient(app)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def make_block(text: str, x1=0, y1=0, x2=100, y2=20, page=1, conf=0.95) -> TextBlock:
    return TextBlock(
        text=text,
        confidence=conf,
        bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, page=page),
    )


INVOICE_TEXT_BLOCKS = [
    make_block("ACME Corp", x1=50, y1=10),
    make_block("Invoice #: INV-2024-0042", x1=50, y1=40),
    make_block("Date: 15/03/2024", x1=50, y1=60),
    make_block("Due Date: 30/03/2024", x1=50, y1=80),
    make_block("Bill To: Wayne Enterprises", x1=50, y1=120),
    make_block("Subtotal: $1,200.00", x1=50, y1=300),
    make_block("VAT 15%: $180.00", x1=50, y1=320),
    make_block("Total Due: $1,380.00", x1=50, y1=340),
]

RECEIPT_TEXT_BLOCKS = [
    make_block("SHOPRITE CHECKERS", x1=50, y1=10),
    make_block("Date: 04/05/2026", x1=50, y1=30),
    make_block("Time: 14:32", x1=50, y1=50),
    make_block("Total: R 245.50", x1=50, y1=200),
    make_block("Payment Method: Credit Card", x1=50, y1=220),
    make_block("Transaction ID: TXN-88291", x1=50, y1=240),
]


# ── Health endpoint tests ──────────────────────────────────────────────────────

def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "uptime_seconds" in data


def test_engine_health_endpoint():
    resp = client.get("/health/engines")
    assert resp.status_code == 200
    data = resp.json()
    assert "engines" in data
    assert "ready" in data


# ── Document type detection tests ─────────────────────────────────────────────

def test_detect_invoice():
    text = "Invoice #INV-001\nBill to: Client Corp\nAmount Due: $500\nRemit payment by 30 days"
    doc_type, confidence = detect_document_type(text)
    assert doc_type == "invoice"
    assert confidence > 0.3


def test_detect_receipt():
    text = "Thank you for your purchase\nTotal: $45.00\nChange: $5.00\nReceipt #12345"
    doc_type, confidence = detect_document_type(text)
    assert doc_type == "receipt"


def test_detect_contract():
    text = "This Agreement is made between Party A and Party B\nGoverning law: State of New York\nWhereas both parties agree"
    doc_type, confidence = detect_document_type(text)
    assert doc_type == "contract"


def test_detect_unknown_falls_back_to_form():
    text = "random text without any known document keywords xyz 123"
    doc_type, confidence = detect_document_type(text)
    assert doc_type == "form"


# ── Field extraction tests ─────────────────────────────────────────────────────

def test_extract_invoice_fields():
    fields, detected, confidence = extract_fields(INVOICE_TEXT_BLOCKS, "invoice")
    assert detected == "invoice"
    assert fields.get("invoice_number") == "INV-2024-0042"
    assert fields.get("date") == "15/03/2024"
    assert fields.get("due_date") == "30/03/2024"
    assert fields.get("total") is not None
    assert "1,380.00" in fields.get("total", "")


def test_extract_receipt_fields():
    fields, detected, confidence = extract_fields(RECEIPT_TEXT_BLOCKS, "receipt")
    assert fields.get("total") is not None
    assert fields.get("payment_method") is not None
    assert fields.get("transaction_id") is not None


def test_auto_detect_invoice():
    fields, detected, confidence = extract_fields(INVOICE_TEXT_BLOCKS, "auto")
    assert detected == "invoice"


# ── Table extraction tests ─────────────────────────────────────────────────────

def test_table_extraction_basic():
    from app.services.table_extractor import extract_tables

    # Simulate a table: 2 rows × 3 cols
    table_blocks = [
        # Row 1 (headers) at y≈10
        make_block("Description", x1=50, y1=5, x2=200, y2=20),
        make_block("Qty", x1=250, y1=5, x2=310, y2=20),
        make_block("Price", x1=360, y1=5, x2=450, y2=20),
        # Row 2 at y≈35
        make_block("Web Design", x1=50, y1=30, x2=200, y2=45),
        make_block("1", x1=250, y1=30, x2=310, y2=45),
        make_block("$800.00", x1=360, y1=30, x2=450, y2=45),
        # Row 3 at y≈60
        make_block("Hosting Setup", x1=50, y1=55, x2=200, y2=70),
        make_block("1", x1=250, y1=55, x2=310, y2=70),
        make_block("$200.00", x1=360, y1=55, x2=450, y2=70),
    ]

    tables = extract_tables(table_blocks)
    assert len(tables) >= 1
    t = tables[0]
    assert len(t.headers) >= 2
    assert len(t.rows) >= 1


# ── Custom type registration tests ────────────────────────────────────────────

def test_register_custom_type():
    pattern_map = register_custom_type(
        doc_type="test_prescription",
        field_definitions={
            "patient_name": r"Patient\s*[:\-]?\s*([A-Za-z\s]+)",
            "medication": r"Rx\s*[:\-]?\s*(.+)",
            "dosage": "Dosage",  # hint-style
        },
        sample_texts=["Patient: John Doe\nRx: Amoxicillin 500mg\nDosage: 3x daily"],
    )
    assert "patient_name" in pattern_map
    assert "medication" in pattern_map
    assert "dosage" in pattern_map

    # Verify it's persisted
    registry = _load_custom_registry()
    assert "test_prescription" in registry


def test_register_type_api():
    resp = client.post("/api/v1/finetune/register", json={
        "document_type": "test_shipping_manifest",
        "field_definitions": {
            "tracking_number": r"Track(?:ing)?\s*#?\s*[:\-]?\s*([A-Z0-9]{10,})",
            "weight": r"Weight\s*[:\-]?\s*([\d\.]+\s*kg)",
        },
        "sample_texts": ["Tracking #: UPS1234567890\nWeight: 2.5 kg"]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "registered"
    assert "tracking_number" in data["fields_registered"]


def test_list_document_types():
    resp = client.get("/api/v1/finetune/types")
    assert resp.status_code == 200
    data = resp.json()
    assert "invoice" in data["builtin_types"]
    assert "receipt" in data["builtin_types"]


def test_cannot_overwrite_builtin():
    resp = client.post("/api/v1/finetune/register", json={
        "document_type": "invoice",
        "field_definitions": {"total": r"\$(\d+)"},
        "sample_texts": ["Total: $100"]
    })
    assert resp.status_code == 409


# ── Upload endpoint tests (mocked OCR) ────────────────────────────────────────

@patch("app.routers.extract.extract_blocks_from_file")
@patch("app.routers.extract.extract_fields")
@patch("app.routers.extract.extract_tables")
def test_extract_endpoint_invoice(mock_tables, mock_fields, mock_ocr):
    mock_ocr.return_value = (INVOICE_TEXT_BLOCKS, 1)
    mock_fields.return_value = (
        {"invoice_number": "INV-001", "total": "1380.00"},
        "invoice",
        0.92,
    )
    mock_tables.return_value = []

    dummy_pdf = io.BytesIO(b"%PDF-1.4 fake content")
    dummy_pdf.name = "invoice.pdf"

    resp = client.post(
        "/api/v1/extract",
        files={"file": ("invoice.pdf", dummy_pdf, "application/pdf")},
        data={"document_type": "invoice", "ocr_engine": "paddle"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["detected_type"] == "invoice"
    assert result["fields"]["invoice_number"] == "INV-001"


def test_extract_unsupported_file_type():
    resp = client.post(
        "/api/v1/extract",
        files={"file": ("report.docx", io.BytesIO(b"fake"), "application/octet-stream")},
        data={"document_type": "auto"},
    )
    assert resp.status_code == 415
