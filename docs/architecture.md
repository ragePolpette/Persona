# Architecture

Persona keeps the architecture intentionally small:

- `persona.core`
- `persona.security`
- `persona.adapters`
- `persona.review`
- `persona.models`

There is no database, no background worker, no remote service, and no distributed component.

## Core responsibilities

`persona.core` is format-agnostic and contains:

- canonicalization rules
- deterministic keyed token generation
- deterministic masked payload generation
- placeholder creation, integrity tagging, and validation
- text replacement logic
- detection orchestration
- anonymize and restore pipeline functions

## Security responsibilities

`persona.security` contains:

- Argon2id key derivation
- persistent local keystore handling
- AES-256-GCM map encryption and decryption
- map format versioning
- exception normalization for malformed keystore/map inputs

## Adapter responsibilities

Each adapter owns:

- extraction of logical text segments
- stable location ids
- writing replacements back to the file format
- strict restore application

### DOCX

- iterates body paragraphs and tables
- keeps logical paragraph ids stable
- applies replacements with a run-aware offset mapping

### XLSX

- walks all worksheets
- handles string cells only
- skips formulas by default

### PDF

- extracts text with `pdfplumber`
- rejects PDFs without extractable text
- writes anonymized and restored outputs as best-effort text PDFs

## Pipeline

### Anonymize

1. Select adapter from file suffix.
2. Extract logical text segments.
3. Run local detection on each segment.
4. Canonicalize matches and derive deterministic token ids.
5. Generate deterministic masked payloads.
6. Build placeholders.
7. Run interactive review unless `--no-review` is used.
8. Build a replacement plan and encrypted map entries.
9. Write censored copy through the adapter.
10. Encrypt the local map file.

### Restore

1. Decrypt the map with the user password.
2. Load the existing local root key with the same password.
3. Re-open the censored file with the proper adapter.
4. Validate placeholders strictly.
5. Restore only expected intact placeholders.
6. Leave altered, malformed, duplicate, or unexpected placeholders untouched and report structured issues.

## Design choices

- Prefer deterministic behavior over heuristic magic.
- Prefer explicit errors over silent fallback.
- Prefer small, testable helpers over deep abstraction layers.
- Keep format-specific logic in adapters rather than leaking it into the core.
- Keep restore strict and report partial failures explicitly instead of auto-healing them.
