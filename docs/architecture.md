# Architecture

Persona is split into four main layers:

- `persona.core`: format-agnostic detection spans, canonicalization, deterministic tokens, masked payload generation, placeholder validation, and restore logic
- `persona.security`: local key handling, Argon2id derivation, encrypted map serialization, and integrity-sensitive operations
- `persona.adapters`: file-format extraction and write-back for DOCX, XLSX, and PDF
- `persona.review`: interactive CLI review loop that approves, rejects, or edits proposed masks

## Pipeline

1. The selected adapter extracts logical text segments from the input file.
2. The detector runs locally on each segment and returns candidate spans.
3. Core logic canonicalizes values, derives stable token ids, and builds placeholders.
4. The review layer optionally approves or edits each proposed replacement.
5. The adapter writes a censored copy of the file.
6. The security layer writes an encrypted map file for later restore.
7. Restore validates placeholders and only restores intact matches in strict mode.

## Format responsibilities

- DOCX: paragraphs and table cells, with logical offset to run-position mapping
- XLSX: string cells across sheets, formulas left untouched by default
- PDF: text extraction via `pdfplumber`; output uses a best-effort text PDF regeneration path

