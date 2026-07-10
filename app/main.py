from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.models import ErrorResponse, ParseResponse
from app.parsers.base import ParserError
from app.services.extractor import DocumentExtractor, DocumentPayload
from app.settings import settings

app = FastAPI(title="ParserDoc", version="0.1.0")
extractor = DocumentExtractor()
base_dir = Path(__file__).resolve().parent
index_html = base_dir / "static" / "index.html"


async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File too large")
    return content


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def home() -> FileResponse:
    return FileResponse(index_html)


@app.post("/parse", response_model=ParseResponse)
async def parse_multipart(file: UploadFile = File(...)) -> ParseResponse:
    try:
        content = await _read_upload(file)
        payload = DocumentPayload(filename=file.filename or "document", mime_type=file.content_type, content=content)
        return await extractor.extract(payload)
    except ParserError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/parse/raw", response_model=ParseResponse)
async def parse_raw(request: Request, filename: str = "document", mime_type: str | None = None) -> ParseResponse:
    try:
        content = await request.body()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="File too large")
        payload = DocumentPayload(filename=filename, mime_type=mime_type, content=content)
        return await extractor.extract(payload)
    except ParserError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error="request_error", detail=str(exc.detail)).model_dump(),
    )
