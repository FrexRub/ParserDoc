# Prepare ParserDoc for Dokploy Deployment

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document follows `.agents/PLANS.md` in this repository.

## Purpose / Big Picture

After this change, ParserDoc can be deployed from GitHub to a Dokploy server as a containerized web service. A server operator can point Dokploy at the repository, use the included Docker Compose file or Dockerfile, expose port 8000, and verify the deployment by requesting `/health`. The deployed service will keep the existing FastAPI endpoints `/`, `/health`, `/parse`, and `/parse/raw` while including common document extraction dependencies inside the image.

## Progress

- [x] (2026-07-13 13:10Z) Read project structure, parser dependencies, and current Git state.
- [x] (2026-07-13 13:12Z) Decided to provide both Dockerfile and Docker Compose artifacts so Dokploy can deploy either mode.
- [x] (2026-07-13 13:22Z) Added Dockerfile, Docker Compose, `.dockerignore`, and `.env.example`.
- [x] (2026-07-13 13:25Z) Updated runtime settings, parser dependencies, README deployment instructions, and Git line-ending attributes.
- [x] (2026-07-13 13:31Z) Validated Python tests, Python syntax, `pyproject.toml`, and basic Compose structure. Docker CLI is not installed in this local environment, so full image build remains a server-side validation step.

## Surprises & Discoveries

- Observation: The project already uses `asyncio.to_thread()` in `app/services/extractor.py`, so deployment work does not need to change the async request model.
  Evidence: `DocumentExtractor.extract()` awaits `asyncio.to_thread(parser.extract, ...)`.
- Observation: PDF and XLS parsers rely on optional Python packages, and legacy DOC parsing benefits from host tools.
  Evidence: `app/parsers/pdf.py` imports `fitz`; `app/parsers/spreadsheet.py` imports `xlrd`; `app/parsers/doc.py` checks `antiword`, `catdoc`, and LibreOffice.
- Observation: `README.md` was UTF-16LE before deployment documentation was added.
  Evidence: the first bytes were `FF FE`, so the file was rewritten as UTF-8 to match `.gitattributes`.
- Observation: Docker CLI is not available in the current Windows workspace.
  Evidence: `docker compose config` failed with `docker : Имя "docker" не распознано...`.

## Decision Log

- Decision: Use a Dockerfile with system packages `antiword`, `catdoc`, and `libreoffice-writer`, plus Python parser libraries.
  Rationale: Dokploy deployments should behave consistently without manually installing parser tools on the host server.
  Date/Author: 2026-07-13 / Codex.
- Decision: Keep the application listening on container port 8000 and make the host port configurable in Compose through `${PORT:-8000}`.
  Rationale: Dokploy can route to a known internal port while users can still run the Compose file locally without extra configuration.
  Date/Author: 2026-07-13 / Codex.
- Decision: Exclude sample documents from the Docker build context but keep `docs/PROJECT_CONTEXT.md`.
  Rationale: sample PDFs, Word files, and spreadsheets are useful for development but unnecessarily increase image build context. `docs/PROJECT_CONTEXT.md` must remain available because `pyproject.toml` uses it as package readme metadata.
  Date/Author: 2026-07-13 / Codex.

## Outcomes & Retrospective

Completed for repository preparation. The repository now contains Docker and Dokploy-ready deployment artifacts, configurable runtime settings, and documentation. Python validation passes locally. Full Docker build validation should be run on a machine with Docker installed, such as the Dokploy server.

## Context and Orientation

ParserDoc is a Python FastAPI service. `app/main.py` defines HTTP routes. `app/services/extractor.py` chooses a parser and runs blocking parser code in a worker thread so the async FastAPI event loop remains responsive. Format-specific parsers live in `app/parsers/`. The deployment target, Dokploy, can build Docker images from a repository or run Docker Compose. A Dockerfile is a recipe for building a container image. Docker Compose is a YAML file that describes one or more containers and their ports, health checks, restart policy, and environment variables.

The service must run with `uvicorn app.main:app --host 0.0.0.0 --port 8000` inside the container. Binding to `0.0.0.0` means the server accepts traffic from outside the container, which is required for Docker networking.

## Plan of Work

Create a `Dockerfile` at the repository root. It will install system tools needed by document parsers, install the Python project, expose port 8000, and start Uvicorn. Create `.dockerignore` to keep `.git`, virtual environments, caches, and sample documents out of the build context unless needed. Create `docker-compose.yml` with a single `parserdoc` service, a health check for `/health`, and a configurable host port.

Update `pyproject.toml` so deployment installs common optional parser libraries: `PyMuPDF` for PDF, `xlrd` for old Excel files, and `striprtf` for RTF. Update `app/settings.py` to read upload limits from environment variables so server limits can be adjusted without rebuilding. Add `.env.example` and expand `README.md` with Dokploy steps.

## Concrete Steps

Work from `C:\Work\ParserDoc`.

Run tests with:

    python -m unittest discover -s tests -v

If Docker is installed locally, validate the image with:

    docker compose config
    docker compose build
    docker compose up -d

Then open:

    http://127.0.0.1:8000/health

The response should be JSON:

    {"status":"ok"}

## Validation and Acceptance

The change is accepted when `python -m unittest discover -s tests -v` passes, `docker compose config` accepts the Compose file if Docker is available, and the repository contains enough deployment documentation for a Dokploy user to deploy from GitHub without guessing the startup command or internal port. The Dokploy application should route to internal port 8000 and use `/health` as a health endpoint.

Current validation result:

    python -m unittest discover -s tests -v
    Ran 11 tests in 1.494s
    OK

    python -m py_compile app\settings.py app\main.py
    passed

    python -c "import tomllib; tomllib.load(open('pyproject.toml','rb')); print('pyproject ok')"
    pyproject ok

    python -c "from pathlib import Path; p=Path('docker-compose.yml'); text=p.read_text(encoding='utf-8'); assert '\t' not in text; assert 'services:' in text and 'parserdoc:' in text and 'healthcheck:' in text; print('compose structural check ok')"
    compose structural check ok

## Idempotence and Recovery

All changes are additive or configuration-only. Re-running `docker compose build` is safe. If a container fails because LibreOffice packages are unavailable on a future base image, remove or adjust the apt package line and rely on the existing DOC best-effort fallback, but keep the explicit parser warning behavior.

## Artifacts and Notes

Pending. Validation outputs will be recorded after commands run.

## Interfaces and Dependencies

The deployment interface is HTTP on port 8000. The container command is:

    uvicorn app.main:app --host 0.0.0.0 --port 8000

The health endpoint is:

    GET /health

The upload endpoints are:

    POST /parse
    POST /parse/raw
