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
- document-binding evaluation
- text replacement logic
- detection orchestration
- anonymize and restore pipeline functions

## Security responsibilities

`persona.security` contains:

- Argon2id key derivation
- persistent local keystore handling
- AES-256-GCM map encryption and decryption
- map format versioning
- encrypted storage of document-binding metadata
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
10. Re-open the censored output and derive binding fingerprints from its extracted logical segments.
11. Encrypt the local map file, including both original and censored-file binding metadata.

### Restore

1. Decrypt the map with the user password.
2. Load the existing local root key with the same password.
3. Re-open the provided censored file with the proper adapter.
4. Derive current file fingerprints from the extracted logical segments.
5. Evaluate document binding between the current file and the encrypted map.
6. In `strict` binding mode, refuse restore early if the binding checks are not strong enough.
7. Validate placeholders strictly.
8. Restore only expected intact placeholders.
9. Leave altered, malformed, duplicate, unexpected, or binding-incompatible situations reported as structured issues.

## Document binding model

Persona now stores additional encrypted binding metadata for:

- original input file fingerprint
- censored output file fingerprint
- logical-content fingerprint
- structural fingerprint
- segment count

During restore the current file is re-extracted through the adapter and compared against the encrypted binding metadata.

Two restore policies exist:

- `pragmatic`: continue restore when compatibility is weak but not strong enough for full trust, and report binding issues
- `strict`: require a strong match on the main binding checks and refuse restore before writing output when the file/map pair is not sufficiently compatible

The current implementation does not inject a Persona marker into the generated files themselves. Binding is map-driven and based on deterministic metadata derived from the file bytes and extracted logical structure.

## Design choices

- Prefer deterministic behavior over heuristic magic.
- Prefer explicit errors over silent fallback.
- Prefer small, testable helpers over deep abstraction layers.
- Keep format-specific logic in adapters rather than leaking it into the core.
- Keep restore strict and report partial failures explicitly instead of auto-healing them.
- Keep document binding explicit and testable rather than hiding it behind opaque restore heuristics.
