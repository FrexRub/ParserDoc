# ParserDoc Project Context

## Purpose

ParserDoc is an asynchronous HTTP service for n8n workflows. It receives documents in binary form, extracts text, normalizes the output, and returns a structured response for an AI agent or another workflow step.

The project is a compact document parsing backend, not a full document management system.

## Core Flow

1. n8n sends a file to the service through an `HTTP Request` node.
2. The file is transferred as binary data.
3. The service detects the document type.
4. The service extracts text from the file.
5. The service normalizes the text.
6. The service returns JSON with the extracted content and metadata.
7. n8n passes the result to an AI agent or another processing step.

## Supported Formats

The current implementation recognizes:

- `PDF`
- `DOCX`
- `DOC`
- `RTF`
- `XLS`
- `TXT`
- `CSV`
- `HTML`
- `JSON`
- `XML`

Some formats rely on optional Python libraries or external host tools. Missing dependencies should result in clear parser errors.

## HTTP API

### `GET /health`

Simple health check.

### `POST /parse`

- Accepts `multipart/form-data`
- Expects a file field named `file`
- Best choice for the usual n8n file upload flow

### `POST /parse/raw`

- Accepts a raw binary request body
- Supports query parameters:
  - `filename`
  - `mime_type`
- Useful when n8n sends the binary directly instead of multipart form data

## Local Test Launcher

For this workspace, the project can also be run without FastAPI using the standalone standard-library server:

```bash
python serve.py
```

That launcher serves the test page at `/` and exposes the same `/health`, `/parse`, and `/parse/raw` routes for local testing.

## Response Shape

Successful parsing returns:

- `status`
- `filename`
- `mime_type`
- `source_type`
- `characters`
- `text`
- `warnings`

Errors return:

- `status`
- `error`
- `detail`

## Project Structure

- `app/main.py`
  - FastAPI app and routes

- `app/models.py`
  - Pydantic response models

- `app/settings.py`
  - Runtime limits and defaults

- `app/services/extractor.py`
  - Parser selection and async orchestration

- `app/services/normalizer.py`
  - Text normalization

- `app/parsers/`
  - Format-specific parsers

## Parser Strategy

Each format is handled by a separate parser module. The extractor chooses a parser by file name and MIME type, then runs the parser in a worker thread via `asyncio.to_thread()` so the event loop stays responsive.

Current parser modules:

- `pdf.py`
- `docx.py`
- `doc.py`
- `rtf.py`
- `spreadsheet.py`
- `text.py`

## Dependency Strategy

Base runtime dependencies in `pyproject.toml`:

- `fastapi`
- `uvicorn[standard]`
- `python-multipart`
- `pydantic`

Optional or external dependencies used by parsers:

- `PyMuPDF` for PDF extraction
- `xlrd` for legacy XLS extraction
- `striprtf` for RTF extraction
- `antiword`, `catdoc`, or LibreOffice for DOC extraction

## Important Implementation Notes

- The HTTP layer is async, but many document parsers are blocking. Those parsers are executed in worker threads.
- File size is limited by `settings.max_upload_bytes`.
- The service prefers explicit errors for unsupported formats or missing dependencies.
- Text normalization removes excess blank lines and normalizes line endings.

## Current Design Intent

This service is meant for practical workflow automation. The main goals are:

- stable API shape
- predictable text extraction
- easy integration with n8n
- graceful failure modes
- low maintenance cost

## Future Work

Likely next steps:

- add `Dockerfile`
- add automated tests for every parser
- improve `DOC` and `XLS` coverage with better server-side dependencies
- add OCR support for scanned documents
- add streaming or chunked handling for large files
- add logging and request tracing
- add more explicit content-type detection

## Working Rules for Future Changes

When extending the project, prefer:

- one parser per format family
- small changes to `app/main.py`
- async request handling
- optional dependencies for heavy file formats
- structured JSON responses for n8n compatibility

Avoid turning the service into a single monolithic parser. Keep format-specific logic isolated and easy to replace.
