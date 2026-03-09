# Persona

Persona is a fully local, offline-first Python CLI for anonymizing sensitive data in documents before sharing them with LLMs, agents, or other tooling.

It analyzes a file locally, proposes deterministic censures, requires an interactive review by default, writes a censored copy of the original document, stores an encrypted local map, and can later restore the original values in strict mode.

## Principles

- Local only
- Offline by design during anonymize and restore
- No external APIs
- No cloud services
- No generative model dependency in v1
- Simple architecture with explicit behavior

## Supported formats in v1

- `.docx`
- `.xlsx`
- text-based `.pdf`

## Explicit v1 limits

- `.doc` is not supported
- `.xls` is not supported
- scanned or image-based PDFs are not supported
- no OCR
- no GUI
- no web app
- no image/textbox/header/footer editing
- no advanced Excel formula rewriting
- PDF output is best-effort and complex layouts may drift

## Detection model

Detection is strictly local and hybrid:

- deterministic recognizers and regex recognizers
- Presidio recognizer primitives and registry orchestration
- spaCy local NER for base `PERSON` and optional `ORGANIZATION`

### Entities in v1

- `PERSON`
- `EMAIL_ADDRESS`
- `PHONE_NUMBER`
- `IBAN`
- `IT_FISCAL_CODE`
- `ORGANIZATION`

## Security model

- a local persistent root key is created on first use
- the root key is encrypted at rest with a password-derived key
- Argon2id is used for key derivation
- AES-256-GCM is used for encrypted map files
- stable token ids are derived with keyed HMAC-SHA256 over canonicalized values
- placeholder restore is strict: altered placeholders are left untouched and reported

More detail is in [docs/architecture.md](docs/architecture.md) and [docs/security.md](docs/security.md).

## Placeholder strategy

Persona separates:

1. stable identifier
2. visual masked payload

The placeholder format used in v1 is:

```text
[[P1|TOKEN_ID|masked payload]]
```

The token id is deterministic and keyed. The masked payload is also deterministic and preserves visual shape as much as possible:

- length
- spaces
- punctuation
- alphabetic/numeric pattern

## Project structure

```text
persona/
  cli.py
  adapters/
  core/
  models/
  review/
  security/
tests/
docs/
```

## Installation

Python 3.11+ is required.

```bash
uv venv
uv pip install --python .venv\Scripts\python.exe -e .[dev]
python -m spacy download en_core_web_sm
```

`en_core_web_sm` is required for robust `PERSON` detection in the default configuration.

## CLI

### Anonymize

```bash
persona anonymize .\sample.docx --password-prompt
persona anonymize .\sample.xlsx --password-env PERSONA_PASSWORD --entities PERSON,EMAIL_ADDRESS,PHONE_NUMBER
persona anonymize .\sample.pdf --no-review --out-dir .\output --report-json .\output\anonymize-report.json --password-prompt
```

### Restore

```bash
persona restore .\sample.censored.docx --map .\sample.persona-map.json --password-prompt
persona restore .\sample.censored.pdf --map .\sample.persona-map.json --out-dir .\restored --report-json .\restored\restore-report.json --password-env PERSONA_PASSWORD
```

### Main options

- `--out-dir`
- `--review / --no-review`
- `--password-prompt`
- `--password-env`
- `--entities`
- `--verbose`
- `--report-json`

## Review flow

Review is enabled by default.

For each detected match Persona shows:

- internal id
- entity type
- detected value
- local context
- logical position
- proposed replacement

Per match you can:

- approve
- reject
- edit the masked payload manually

## Restore behavior

Restore requires:

- censored file
- encrypted map
- correct password

Default restore policy is strict:

- valid placeholders are restored
- altered or inconsistent placeholders are not restored
- altered placeholders remain in place
- warnings are reported

## Format behavior

### DOCX

- paragraphs in the document body
- table cells
- run-aware replacement strategy to handle cross-run matches

### XLSX

- string cells only
- multiple sheets
- formulas are left untouched by default

### PDF

- text extraction with `pdfplumber`
- no OCR
- output PDF is regenerated in best-effort text mode

## Tests

The repository includes:

- unit tests for canonicalization, stable tokens, deterministic masking, placeholder validation, keystore and encrypted map handling
- integration tests for DOCX paragraphs, DOCX tables, DOCX split runs, XLSX multi-sheet handling, PDF text extraction, non-text PDF failure, review flow, and end-to-end restore

Run the full suite with:

```bash
.venv\Scripts\python.exe -m pytest
```

## Known limits

- PDF round-tripping is intentionally conservative and not layout-faithful for complex documents
- spaCy model installation is a local prerequisite for default `PERSON` detection
- placeholders currently reserve `|` and `]]` inside manual masked payload edits

## Sensible next steps

- configurable policies per entity type
- richer review TUI
- stronger PDF segmentation and layout preservation
- optional local-model-assisted suggestions behind an explicit non-default path

