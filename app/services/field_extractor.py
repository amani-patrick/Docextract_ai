"""
Field extraction engine.

Built-in document type templates:
  - invoice
  - receipt
  - form (generic key:value pairs)
  - contract (parties, dates, amounts)
  - id_card
  - bank_statement
  - purchase_order

Each template is a dict of:
  field_name → list of regex patterns (first match wins)

Custom document types can be registered at runtime via the fine-tune API
and are persisted to a JSON registry file.
"""

import re
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("docuextract.fields")

REGISTRY_PATH = Path("/tmp/docuextract_custom_types.json")

# ── Built-in templates ─────────────────────────────────────────────────────────
BUILTIN_TEMPLATES: dict[str, dict[str, list[str]]] = {

    "invoice": {
        "invoice_number": [
            r"invoice\s*(?:no|number|#|num)\.?\s*[:\-]?\s*([A-Z0-9\-\/]+)",
            r"inv\.?\s*#?\s*[:\-]?\s*([A-Z0-9\-\/]+)",
        ],
        "date": [
            r"(?:invoice\s+)?date\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            r"dated?\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            r"(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{2,4})",
        ],
        "due_date": [
            r"due\s+(?:date|by|on)\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            r"payment\s+due\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        ],
        "vendor_name": [
            r"(?:from|vendor|seller|billed?\s+by)\s*[:\-]?\s*([A-Za-z0-9\s&\.,]+?)(?:\n|ltd|llc|inc|corp|co\.)",
            r"^([A-Z][A-Za-z0-9\s&\.,]{2,50})\s*\n.*invoice",
        ],
        "client_name": [
            r"(?:to|bill\s*to|sold\s*to|customer)\s*[:\-]?\s*([A-Za-z0-9\s&\.,]+?)(?:\n|$)",
        ],
        "subtotal": [
            r"sub\s*total\s*[:\-]?\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
        ],
        "tax": [
            r"(?:vat|tax|gst|hst)\s*(?:\d+%?)?\s*[:\-]?\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
        ],
        "total": [
            r"(?:grand\s+)?total\s+(?:due|amount)?\s*[:\-]?\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
            r"amount\s+(?:due|payable)\s*[:\-]?\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
            r"total\s*[:\-]\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
        ],
        "currency": [
            r"(USD|EUR|GBP|RWF|KES|NGN|ZAR|AUD|CAD)",
            r"(\$|€|£|₦|KSh)",
        ],
        "payment_terms": [
            r"(?:payment\s+)?terms?\s*[:\-]?\s*([^\n]{3,50})",
            r"(net\s*\d+|due\s+on\s+receipt|immediate)",
        ],
        "po_number": [
            r"p\.?o\.?\s*(?:number|#|no)\.?\s*[:\-]?\s*([A-Z0-9\-]+)",
            r"purchase\s+order\s*[:\-]?\s*([A-Z0-9\-]+)",
        ],
    },

    "receipt": {
        "store_name": [
            r"^([A-Z][A-Za-z0-9\s&\.,]{2,40})\s*\n",
        ],
        "date": [
            r"(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            r"(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{2,4})",
        ],
        "time": [
            r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?)",
        ],
        "total": [
            r"(?:total|amount\s+paid|grand\s+total)\s*[:\-]?\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
        ],
        "tax": [
            r"(?:tax|vat|gst)\s*[:\-]?\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
        ],
        "payment_method": [
            r"(cash|credit\s*card|debit\s*card|visa|mastercard|amex|mobile\s*money|mpesa|mtn|airtel)",
        ],
        "transaction_id": [
            r"(?:transaction|txn|ref|receipt)\s*(?:id|#|no)\.?\s*[:\-]?\s*([A-Z0-9\-]{6,})",
        ],
    },

    "form": {
        # Generic: extract any key: value pair
        "_generic_kv": [
            r"([A-Za-z\s]{2,30})\s*[:\-]\s*(.{1,100})",
        ],
    },

    "contract": {
        "party_1": [
            r"(?:between|party\s+a|first\s+party)\s*[:\-]?\s*([A-Za-z0-9\s&\.,]{3,60}?)(?:\n|and\b|,)",
        ],
        "party_2": [
            r"(?:and|party\s+b|second\s+party)\s*[:\-]?\s*([A-Za-z0-9\s&\.,]{3,60}?)(?:\n|,)",
        ],
        "effective_date": [
            r"effective\s+(?:date|as\s+of)\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            r"effective\s+(\w+\s+\d{1,2},?\s+\d{4})",
        ],
        "expiry_date": [
            r"(?:expir(?:y|es?|ation)|terminat(?:es?|ion))\s+(?:date\s*)?[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        ],
        "contract_value": [
            r"(?:consideration|contract\s+value|total\s+fee|compensation)\s*[:\-]?\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
        ],
        "governing_law": [
            r"govern(?:ed|ing)\s+(?:by\s+the\s+laws?\s+of|law)\s*[:\-]?\s*([A-Za-z\s]{3,50}?)(?:\.|,|\n)",
        ],
    },

    "id_card": {
        "full_name": [
            r"(?:name|full\s+name)\s*[:\-]?\s*([A-Z][a-zA-Z\s]{2,40})",
            r"^([A-Z]{2,}\s+[A-Z]{2,}(?:\s+[A-Z]{2,})?)\s*$",
        ],
        "id_number": [
            r"(?:id\s*(?:no|number|#)|national\s+id)\s*[:\-]?\s*([A-Z0-9\s\-]{5,20})",
        ],
        "date_of_birth": [
            r"(?:dob|date\s+of\s+birth|born)\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        ],
        "expiry_date": [
            r"(?:expir(?:y|es?|ation)|valid\s+(?:until|through))\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        ],
        "nationality": [
            r"(?:nationality|citizenship)\s*[:\-]?\s*([A-Za-z]{3,20})",
        ],
        "sex": [
            r"(?:sex|gender)\s*[:\-]?\s*(male|female|m|f)\b",
        ],
    },

    "bank_statement": {
        "account_number": [
            r"(?:account\s*(?:no|number|#))\s*[:\-]?\s*([X\*\d\s\-]{6,20})",
        ],
        "account_holder": [
            r"(?:account\s+holder|name)\s*[:\-]?\s*([A-Za-z\s]{3,40}?)(?:\n|$)",
        ],
        "bank_name": [
            r"^([A-Z][A-Za-z\s&]{3,40}(?:bank|financial|credit\s+union))",
        ],
        "statement_period": [
            r"(?:statement\s+)?period\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}\s*(?:to|–|-)\s*\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        ],
        "opening_balance": [
            r"(?:opening|beginning)\s+balance\s*[:\-]?\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
        ],
        "closing_balance": [
            r"(?:closing|ending)\s+balance\s*[:\-]?\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
        ],
        "currency": [
            r"(USD|EUR|GBP|RWF|KES|NGN|ZAR|AUD|CAD)",
        ],
    },

    "purchase_order": {
        "po_number": [
            r"p\.?o\.?\s*(?:number|#|no)\.?\s*[:\-]?\s*([A-Z0-9\-\/]+)",
            r"purchase\s+order\s*(?:number|#)?\s*[:\-]?\s*([A-Z0-9\-\/]+)",
        ],
        "date": [
            r"(?:po\s+)?date\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        ],
        "vendor": [
            r"(?:vendor|supplier|from)\s*[:\-]?\s*([A-Za-z0-9\s&\.,]{3,50}?)(?:\n|$)",
        ],
        "ship_to": [
            r"(?:ship\s+to|deliver\s+to)\s*[:\-]?\s*([A-Za-z0-9\s\.,\-]{3,80}?)(?:\n|$)",
        ],
        "total": [
            r"(?:total|order\s+total|amount)\s*[:\-]?\s*[$€£]?\s*([\d,]+\.?\d{0,2})",
        ],
        "requested_by": [
            r"(?:requested|ordered)\s+by\s*[:\-]?\s*([A-Za-z\s]{3,40}?)(?:\n|$)",
        ],
    },
}

# ── Auto-detection keywords ────────────────────────────────────────────────────
DOC_TYPE_KEYWORDS: dict[str, list[str]] = {
    "invoice": ["invoice", "bill to", "amount due", "remit payment", "inv #"],
    "receipt": ["receipt", "thank you for your purchase", "amount paid", "change"],
    "contract": ["agreement", "whereas", "hereinafter", "governing law", "terms and conditions", "signed by"],
    "id_card": ["date of birth", "nationality", "national id", "passport", "expires"],
    "bank_statement": ["account statement", "opening balance", "closing balance", "transaction history"],
    "purchase_order": ["purchase order", "p.o. number", "ship to", "vendor"],
}


def detect_document_type(text: str) -> tuple[str, float]:
    """
    Score each document type by keyword hits.
    Returns (best_type, confidence_0_to_1).
    """
    text_lower = text.lower()
    scores: dict[str, int] = {}

    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[doc_type] = score

    if not scores:
        return "form", 0.3  # fallback generic

    best = max(scores, key=lambda k: scores[k])
    total_keywords = len(DOC_TYPE_KEYWORDS[best])
    confidence = min(scores[best] / total_keywords, 1.0)
    return best, round(confidence, 3)


def _load_custom_registry() -> dict[str, dict[str, list[str]]]:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_custom_registry(registry: dict):
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))


def register_custom_type(
    doc_type: str,
    field_definitions: dict[str, str],
    sample_texts: list[str],
) -> dict[str, list[str]]:
    """
    Register a new custom document type with field patterns.
    field_definitions: {field_name: regex_or_hint_string}
    Returns the compiled pattern map.
    """
    registry = _load_custom_registry()

    pattern_map: dict[str, list[str]] = {}
    for field, pattern_or_hint in field_definitions.items():
        # If it looks like a regex, use it; otherwise auto-wrap it
        try:
            re.compile(pattern_or_hint)
            pattern_map[field] = [pattern_or_hint]
        except re.error:
            # Treat as a literal keyword hint — build a capture pattern
            escaped = re.escape(pattern_or_hint.strip())
            pattern_map[field] = [
                rf"(?:{escaped})\s*[:\-]?\s*(.{{1,100}})"
            ]

    registry[doc_type] = pattern_map
    _save_custom_registry(registry)
    logger.info(f"Registered custom document type '{doc_type}' with {len(pattern_map)} fields")
    return pattern_map


def extract_fields(
    blocks: list,
    doc_type: str,
    auto_detect: bool = True,
) -> tuple[dict[str, Any], str, float]:
    """
    Extract structured fields from OCR text blocks.

    Returns:
        (fields_dict, detected_type, confidence)
    """
    full_text = "\n".join(b.text for b in blocks)

    # Auto-detect or use provided
    detected_type = doc_type
    confidence = 1.0
    if doc_type == "auto" or auto_detect:
        detected_type, confidence = detect_document_type(full_text)
        if doc_type != "auto" and doc_type != detected_type:
            # User specified — use it but report low confidence
            detected_type = doc_type
            confidence = 0.5

    # Get template
    custom_registry = _load_custom_registry()
    if detected_type in custom_registry:
        template = custom_registry[detected_type]
    elif detected_type in BUILTIN_TEMPLATES:
        template = BUILTIN_TEMPLATES[detected_type]
    else:
        template = BUILTIN_TEMPLATES["form"]

    fields: dict[str, Any] = {}

    # Generic form: key-value pair extraction
    if "_generic_kv" in template:
        kv_pattern = template["_generic_kv"][0]
        matches = re.findall(kv_pattern, full_text, re.IGNORECASE | re.MULTILINE)
        for key, value in matches:
            clean_key = key.strip().lower().replace(" ", "_")
            if clean_key and len(clean_key) > 1:
                fields[clean_key] = value.strip()
        return fields, detected_type, confidence

    # Structured extraction
    for field, patterns in template.items():
        value = None
        for pattern in patterns:
            try:
                match = re.search(pattern, full_text, re.IGNORECASE | re.MULTILINE)
                if match:
                    value = match.group(1).strip()
                    # Clean up common OCR artifacts
                    value = re.sub(r'\s+', ' ', value).strip()
                    break
            except (re.error, IndexError):
                continue
        fields[field] = value

    logger.info(f"Extracted {sum(1 for v in fields.values() if v)} / {len(fields)} fields for '{detected_type}'")
    return fields, detected_type, confidence
