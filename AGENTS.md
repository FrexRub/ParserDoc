# Repository Guidelines

## Project Structure & Module Organization

ParserDoc is a Python 3.11+ document-extraction service. The FastAPI application and routes live in `app/main.py`; shared response models and runtime limits are in `app/models.py` and `app/settings.py`. Keep format-specific extraction in `app/parsers/` (one module per format family) and orchestration or normalization in `app/services/`. The browser test panel is `app/static/index.html`. `serve.py` provides a standard-library fallback server for local testing. Tests belong in `tests/`, while design and API context live in `docs/PROJECT_CONTEXT.md`.

## Build, Test, and Development Commands

Create and activate a virtual environment, then install the package:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

- `python -m unittest discover -s tests -v` runs the complete test suite.
- `uvicorn app.main:app --reload` starts the FastAPI development server with reload.
- `python serve.py` starts the dependency-light local server and test page.
- `curl http://127.0.0.1:8000/health` verifies the running service.

Some parsers need optional packages or host tools (for example PyMuPDF, `xlrd`, `striprtf`, or LibreOffice). Keep these optional and return clear parser errors when unavailable.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations, and `from __future__ import annotations`. Follow PEP 8: `snake_case` for functions and modules, `PascalCase` for classes, and uppercase names for module constants. Prefer small async HTTP handlers; move blocking extraction into worker threads through the service layer. Keep response shapes stable for n8n clients. No formatter or linter is currently configured, so match nearby code and avoid unrelated formatting changes.

## Testing Guidelines

Tests use Python's built-in `unittest`. Name files `test_*.py`, classes `*Tests`, and methods `test_<behavior>`. Add focused unit tests for parsers and normalization, plus endpoint tests when routes or response contracts change. Use in-memory fixtures where practical; do not commit generated documents or server logs.

## Commit & Pull Request Guidelines

Recent history uses short, imperative summaries such as `Build async document parser service`. Keep each commit focused and use the body to explain non-obvious tradeoffs. Pull requests should summarize behavior changes, list verification commands, note optional dependency impacts, and link relevant issues. Include screenshots only for changes to the static test panel, and include sample request/response JSON for API contract changes.

# ExecPlans

When writing complex features or significant refactors, use an ExecPlan (as described in .agents/PLANS.md) from design to implementation.
