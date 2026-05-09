"""
DocuExtract AI — Production OCR Document Extraction API
Handles invoices, receipts, forms, contracts, and custom document types.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
import time
import logging

from app.routers import extract, health, finetune
from app.models.responses import ErrorResponse

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("docuextract")

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="DocuExtract AI",
    description="Production-grade OCR document extraction API supporting invoices, receipts, forms, and custom document types.",
    version="1.0.0",
    # docs_url="/docs",
    # redoc_url="/redoc",
)

# ── Middleware ─────────────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock down in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = round((time.perf_counter() - start) * 1000, 1)
    response.headers["X-Process-Time-Ms"] = str(duration)
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration}ms)")
    return response

# ── Global exception handler ───────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_error",
            message="An unexpected error occurred. Please try again.",
            details=str(exc),
        ).dict(),
    )

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(health.router, tags=["Health"])
app.include_router(extract.router, prefix="/api/v1", tags=["Extraction"])
app.include_router(finetune.router, prefix="/api/v1", tags=["Fine-tuning"])

@app.get("/", include_in_schema=False)
async def root():
    import os
    # pyrefly: ignore [missing-import]
    from fastapi.responses import FileResponse
    for filename in ["index.html", "dashboard/index.html"]:
        if os.path.exists(filename):
            return FileResponse(filename)
    return {"service": "DocuExtract AI", "version": "1.0.0", "status": "running"}
