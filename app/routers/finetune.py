"""
/api/v1/finetune — Register and manage custom document types.
"""

import logging
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException
from app.models.responses import FineTuneRequest, FineTuneResponse
from app.services.field_extractor import (
    register_custom_type,
    _load_custom_registry,
    BUILTIN_TEMPLATES,
)

logger = logging.getLogger("docuextract.finetune")
router = APIRouter()


@router.post(
    "/finetune/register",
    response_model=FineTuneResponse,
    summary="Register a custom document type",
    description="""
Register a new document type with custom field extraction patterns.

**Example use cases:**
- Medical prescriptions
- Shipping manifests
- Insurance claims
- Utility bills
- HR onboarding forms

**field_definitions** can be:
- A full regex with one capture group: `"invoice_no": "INV[\\-\\s]?(\\d{4,})"`
- A plain hint string: `"patient_name": "Patient Name"` (auto-wrapped into a capture pattern)
""",
)
async def register_document_type(request: FineTuneRequest):
    # Prevent overwriting built-ins
    if request.document_type in BUILTIN_TEMPLATES:
        raise HTTPException(
            status_code=409,
            detail=f"'{request.document_type}' is a built-in document type and cannot be overwritten. Use a different name."
        )

    if len(request.field_definitions) == 0:
        raise HTTPException(status_code=400, detail="At least one field definition is required.")

    pattern_map = register_custom_type(
        doc_type=request.document_type,
        field_definitions=request.field_definitions,
        sample_texts=request.sample_texts,
    )

    return FineTuneResponse(
        document_type=request.document_type,
        fields_registered=list(pattern_map.keys()),
        pattern_count=sum(len(v) for v in pattern_map.values()),
        status="registered",
        message=f"Custom document type '{request.document_type}' registered with {len(pattern_map)} fields. Use it by passing document_type='{request.document_type}' to /api/v1/extract.",
    )


@router.get(
    "/finetune/types",
    summary="List all available document types",
)
async def list_document_types():
    custom = _load_custom_registry()
    return {
        "builtin_types": list(BUILTIN_TEMPLATES.keys()),
        "custom_types": list(custom.keys()),
        "total": len(BUILTIN_TEMPLATES) + len(custom),
    }


@router.delete(
    "/finetune/types/{document_type}",
    summary="Delete a custom document type",
)
async def delete_document_type(document_type: str):
    if document_type in BUILTIN_TEMPLATES:
        raise HTTPException(status_code=403, detail="Cannot delete built-in document types.")

    from pathlib import Path
    import json
    from app.services.field_extractor import REGISTRY_PATH

    registry = _load_custom_registry()
    if document_type not in registry:
        raise HTTPException(status_code=404, detail=f"Custom type '{document_type}' not found.")

    del registry[document_type]
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))

    return {"status": "deleted", "document_type": document_type}
