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
- placeholder creation and validation
- text replacement logic
- detection orchestration
- anonymize and restore pipeline functions

## Security responsibilities

`persona.security` contains:

- Argon2id key derivation
- persistent local keystore handling
- AES-256-GCM map encryption and decryption
- map format versioning

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
8. Write censored copy through the adapter.
9. Encrypt the local map file.

### Restore

1. Decrypt the map with the user password.
2. Re-open the censored file with the proper adapter.
3. Validate placeholders strictly.
4. Restore only exact, intact placeholders.
5. Leave altered placeholders untouched and report warnings.

## Design choices

- Prefer deterministic behavior over heuristic magic.
- Prefer explicit errors over silent fallback.
- Prefer small, testable helpers over deep abstraction layers.
- Keep format-specific logic in adapters rather than leaking it into the core.
