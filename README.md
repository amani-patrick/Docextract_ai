# DocuExtract AI

**Production-grade OCR document extraction API. Invoices, receipts, forms, contracts — structured JSON in seconds.**

![Python](https://img.shields.io/badge/python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green) ![PaddleOCR](https://img.shields.io/badge/PaddleOCR-2.7-orange) ![Docker](https://img.shields.io/badge/docker-ready-blue) ![Tests](https://img.shields.io/badge/tests-passing-brightgreen)

---

## What it does

DocuExtract AI takes any PDF or image — invoice, receipt, form, contract, ID card, bank statement, purchase order — and returns clean, structured JSON with:

- **Extracted fields** (invoice number, totals, dates, parties, etc.)
- **Structured tables** (line items, transactions, data grids)
- **Raw OCR blocks** with bounding boxes and confidence scores
- **Auto document type detection**

Plus a fine-tuning API to teach it any custom document format in minutes.

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/yourname/docuextract-ai
cd docuextract-ai

# Install system dependencies (Ubuntu/Debian)
sudo apt-get install tesseract-ocr poppler-utils

# Python deps
pip install -r requirements.txt
```

### 2. Run the API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API docs: http://localhost:8000/docs

### 3. Open the dashboard

```bash
open dashboard/index.html
# or: python -m http.server 3000 --directory dashboard
```

### 4. Run with Docker (recommended for production)

```bash
# Standard build & start
docker compose up --build

# Clean rebuild (no cache, full reset)
docker compose down -v
docker compose build --no-cache
docker compose up

# Production profile with Nginx
docker compose --profile production up --build -d
```

---

## API Usage

### Extract a document

```bash
curl -X POST http://localhost:8000/api/v1/extract \
  -F "file=@invoice.pdf" \
  -F "document_type=auto" \
  -F "ocr_engine=paddle" \
  -F "extract_tables_flag=true"
```

**Response:**
```json
{
  "document_type": "auto",
  "detected_type": "invoice",
  "confidence_score": 0.833,
  "page_count": 2,
  "processing_time_ms": 1240.5,
  "fields": {
    "invoice_number": "INV-2024-0042",
    "date": "15/03/2024",
    "due_date": "30/03/2024",
    "vendor_name": "ACME Corp",
    "client_name": "Wayne Enterprises",
    "subtotal": "1,200.00",
    "tax": "180.00",
    "total": "1,380.00",
    "currency": "USD",
    "payment_terms": "Net 30",
    "po_number": null
  },
  "tables": [
    {
      "table_index": 0,
      "page": 1,
      "headers": ["Description", "Qty", "Unit Price", "Total"],
      "rows": [
        ["Web Design", "1", "$800.00", "$800.00"],
        ["Hosting Setup", "1", "$400.00", "$400.00"]
      ],
      "confidence": 0.91
    }
  ],
  "raw_blocks": [...],
  "filename": "invoice.pdf",
  "file_size_bytes": 245120
}
```

### Batch extraction (up to 10 files)

```bash
curl -X POST http://localhost:8000/api/v1/extract/batch \
  -F "files=@invoice1.pdf" \
  -F "files=@receipt.jpg" \
  -F "document_type=auto"
```

### Register a custom document type

```bash
curl -X POST http://localhost:8000/api/v1/finetune/register \
  -H "Content-Type: application/json" \
  -d '{
    "document_type": "medical_prescription",
    "field_definitions": {
      "patient_name": "Patient\\s*[:\\-]?\\s*([A-Za-z\\s]+)",
      "medication":   "Rx\\s*[:\\-]?\\s*(.+)",
      "dosage":       "Dosage",
      "prescriber":   "Dr\\.?\\s*([A-Za-z\\s]+)"
    },
    "sample_texts": [
      "Patient: John Doe\\nRx: Amoxicillin 500mg\\nDosage: 3x daily\\nDr. Sarah Smith"
    ]
  }'
```

Then use it:
```bash
curl -X POST http://localhost:8000/api/v1/extract \
  -F "file=@prescription.jpg" \
  -F "document_type=medical_prescription"
```

---

## Supported Document Types

| Type | Fields Extracted |
|------|-----------------|
| `invoice` | Invoice #, date, due date, vendor, client, subtotal, tax, total, currency, PO #, payment terms |
| `receipt` | Store, date, time, total, tax, payment method, transaction ID |
| `form` | Auto key-value extraction (generic) |
| `contract` | Party 1 & 2, effective date, expiry, contract value, governing law |
| `id_card` | Name, ID number, DOB, expiry, nationality, sex |
| `bank_statement` | Account holder, account #, bank, period, opening/closing balance, currency |
| `purchase_order` | PO #, date, vendor, ship-to, total, requested by |
| `auto` | Auto-detects from the above list |
| `custom` | Any type you register via `/api/v1/finetune/register` |

---

## Architecture

```
client
  │
  ▼
┌─────────────────────────────────────────┐
│  Nginx (rate limiting, SSL, 50MB limit) │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  FastAPI (uvicorn, 2 workers)           │
│                                         │
│  POST /api/v1/extract                   │
│    → ocr_service.py (PaddleOCR)         │
│    → table_extractor.py (spatial geo)   │
│    → field_extractor.py (regex engine)  │
│                                         │
│  POST /api/v1/finetune/register         │
│    → custom type registry (JSON file)   │
└─────────────────────────────────────────┘
```

**OCR Pipeline:**
1. PDF → per-page images at 200dpi (pdf2image or PyMuPDF)
2. Preprocess: upscale if small, convert to RGB
3. PaddleOCR: detect text regions → recognize text
4. Spatial clustering: group blocks into rows → columns (table detection)
5. Pattern matching: regex against full text per field template

---

## Deployment

### Render.com (easiest)
1. Push to GitHub
2. New Web Service → connect repo → Render auto-detects `render.yaml`
3. Select **Standard** plan (2 CPU, 4GB RAM for PaddleOCR)
4. Deploy — done. ~$25/month.

### Railway.app
```bash
railway login
railway up
```

### VPS (DigitalOcean/Linode/Hetzner)
```bash
# On server
git clone https://github.com/yourname/docuextract-ai
cd docuextract-ai
docker compose --profile production up -d
```

---

## Testing

```bash
# Run full test suite
pytest tests/ -v --cov=app --cov-report=term-missing

# Run just field extraction tests
pytest tests/test_extraction.py::test_extract_invoice_fields -v
```

---

## Client Pricing Guide

| Package | What's included | Price |
|---------|----------------|-------|
| **Starter** | Single doc type, 500 docs/mo, hosted | $250/mo |
| **Professional** | All doc types, 5,000 docs/mo, 2 custom types | $600/mo |
| **Enterprise** | Unlimited docs, unlimited custom types, SLA, white-label dashboard | $1,200+/mo |
| **One-time setup** | Custom doc type training + integration | $400–800 |

**Ideal clients:** accounting firms, AP/AR automation startups, fintech, logistics, legal, healthcare.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API framework | FastAPI + uvicorn |
| Primary OCR | PaddleOCR 2.7 |
| Fallback OCR | pytesseract |
| PDF rendering | pdf2image (poppler) / PyMuPDF |
| Field extraction | Regex engine (custom templates) |
| Table detection | Spatial bounding-box clustering |
| Containerization | Docker + docker-compose |
| Reverse proxy | Nginx |
| Testing | pytest + pytest-asyncio |

---

## Roadmap / Upsells

- [ ] **Webhook callbacks** — POST result to your endpoint when done
- [ ] **TableTransformer** — ML-based table detection for complex layouts
- [ ] **Multilingual OCR** — PaddleOCR supports 80+ languages
- [ ] **Fine-tune with examples** — upload 10 sample docs, auto-generate patterns
- [ ] **S3/GCS integration** — process files directly from cloud storage
- [ ] **CSV/Excel export** endpoint
- [ ] **Auth / API keys** — multi-tenant with usage metering
