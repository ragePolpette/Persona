# Architecture

Persona is now organized around two main layers:

- `engine`: reusable anonymization engine
- `web`: minimal local app using the same engine

The CLI remains supported, but it is no longer the conceptual center of the project.

## High-level structure

```text
persona/
  adapters/   # format-specific extraction/write-back/restore
  core/       # deterministic masking, placeholders, binding, restore primitives
  engine/     # block-oriented LLM detection, orchestration, storage
  review/     # CLI review fallback
  security/   # keystore + encrypted map
  web/        # local FastAPI application
  cli.py      # CLI using the shared engine
```

## What was reused

The repositioning deliberately keeps the strongest existing pieces:

- DOCX/XLSX/PDF adapters
- deterministic masking
- placeholder model
- encrypted map
- binding checks
- strict restore
- test infrastructure

## What changed direction

The previous fixed-entity detection path based on Presidio/spaCy is no longer the primary product model. It remains in the repository as legacy code and tests, but the main engine path is now:

1. extract logical text segments through adapters
2. chunk segment text when needed
3. send chunk text to a local LLM backend
4. validate JSON span output
5. resolve overlaps into logical sensitive blocks
6. prepare deterministic masked blocks and placeholders
7. review those blocks
8. write censored file + encrypted map + binding metadata
9. restore through strict placeholder validation and pragmatic/strict binding checks

## Engine layer

Main modules in `persona.engine`:

- `llm.py`
  - local backend contract
  - Qwen backends
  - JSON prompt contract
  - response parsing/validation
- `chunking.py`
  - chunk large text segments into bounded chunks with overlap
- `analysis.py`
  - convert backend findings into document-level block matches
  - overlap resolution
- `service.py`
  - reusable orchestration for analyze/anonymize/restore
- `storage.py`
  - simple local JSON-backed document storage for the app

The engine intentionally reuses `persona.core` and `persona.adapters` instead of replacing them.

## Local LLM backend model

The engine depends on a small contract:

- `analyze_chunk(text) -> list[findings]`

A finding contains at minimum:

- `start`
- `end`
- `text`

Optional fields:

- `confidence`
- `label`
- `reason`

Implemented backends:

- `qwen-ollama`
- `qwen-llama-cpp`
- `mock`

This keeps Persona model-agnostic while still making Qwen3-4B the first-class concrete backend.

## Block model

Persona now works on logical sensitive blocks, not fixed PII entity types.

Important distinction:

- detection identifies blocks semantically
- masking preserves structure inside each block deterministically

The map stores each block as one logical restore unit.

`entity_type` is still present in some existing data structures for compatibility, but in the new path it behaves as an optional block label rather than the project’s organizing principle.

## Review model

Review is aligned to block findings.

Per block, Persona keeps:

- original text
- local context
- logical position
- confidence
- label
- reason
- proposed masked block
- approval state

The CLI still offers a text review fallback. The local web app is now the primary review surface.

## Local app

The web app is intentionally small and server-rendered.

Routes:

- `/`
  - document list
  - upload form
- `/documents/{id}`
  - original preview
  - anonymized preview
  - block review table
  - anonymize action
  - restore action
- `POST /documents/upload`
- `POST /documents/{id}/review`
- `POST /documents/{id}/anonymize`
- `POST /documents/{id}/restore`

The preview is a logical-text preview derived from adapter extraction. It is not a visual fidelity renderer.

## Local storage

The app uses a simple workspace on disk:

```text
~/.persona/workspace/
  originals/
  censored/
  maps/
  restored/
  metadata/
```

Metadata is stored as one JSON file per document. No database is used.

## Restore and binding

Restore still uses the existing strict placeholder logic and the newer binding checks.

Binding remains map-driven and checks:

- file format
- exact file hash
- logical-content fingerprint
- structure fingerprint
- segment count

Modes:

- `pragmatic`
- `strict`

The web app and CLI both call the same restore service.

## Design tradeoffs

Intentional decisions in this repositioning:

- keep the deterministic anonymization/restore core rather than rewriting it
- move detection to an LLM interface rather than hard-coded field recognizers
- keep the web app server-rendered and simple instead of adding a JS-heavy frontend
- avoid database and cloud dependencies
- keep CLI and GUI as alternate surfaces over the same engine

## Current legacy boundary

Still present but de-centered:

- `persona.core.detection`
- fixed-entity Presidio/spaCy detection tests

Current centerline:

- `persona.engine`
- `persona.web`
- deterministic core primitives under `persona.core`
