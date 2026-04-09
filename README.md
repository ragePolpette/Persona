# Persona

> [!IMPORTANT]
> Work in progress.
> Persona is an active prototype and portfolio project. The current repository shows the intended architecture and local workflow, but the product should not be read as a finished or production-ready document anonymization system.

Persona is a local/offline application for reversible document anonymization, guided by a local LLM that identifies logically sensitive text blocks. A deterministic engine applies structural masking, stores an encrypted local map, and supports verifiable restore with document binding checks. Persona now includes both:

- a reusable Python engine
- a minimal local web app for document upload, review, anonymization, and restore
- a CLI that uses the same engine

## Product direction

Persona is no longer positioned primarily as a fixed-field PII detector.

The main flow is:

1. extract logical text from a local document
2. ask a local LLM to identify sensitive text blocks
3. review those blocks
4. apply deterministic masking
5. write a censored copy plus encrypted local map
6. restore later with strict placeholder checks and document binding checks

## Current architecture

Main areas:

```text
persona/
  adapters/      # DOCX/XLSX/PDF extraction and write-back
  core/          # masking, placeholders, binding, restore primitives
  engine/        # LLM-guided block detection, orchestration, local storage
  review/        # CLI review fallback
  security/      # keystore + encrypted map
  web/           # local FastAPI web app
  cli.py         # CLI entrypoints using the shared engine
tests/
docs/
```

## Supported formats

- `.docx`
- `.xlsx`
- text-based `.pdf`

Explicitly not supported:

- `.doc`
- `.xls`
- OCR
- image-based/scanned PDFs
- cloud inference
- external APIs
- Electron

## Detection model

Detection is now block-oriented and LLM-guided.

The local LLM is asked to return JSON findings shaped around spans such as:

```json
{
  "findings": [
    {
      "start": 10,
      "end": 32,
      "text": "Alice Example",
      "confidence": 0.93,
      "label": "person",
      "reason": "full identifying name"
    }
  ]
}
```

Important constraints:

- the model only identifies sensitive blocks
- it does not rewrite text
- it does not invent placeholders
- it does not perform masking

Masking, encrypted map generation, restore, and binding are deterministic engine concerns.

## Local LLM backend

Persona is model-agnostic through a small backend contract:

- `analyze_chunk(text) -> findings`

Concrete backends currently implemented:

- `qwen-ollama`
- `qwen-llama-cpp`
- `mock` for tests and contract validation

Default intended runtime is Qwen3-4B via a local runtime such as Ollama or llama.cpp.

Relevant environment variables:

- `PERSONA_LLM_BACKEND`
- `PERSONA_LLM_MODEL`
- `PERSONA_LLM_BASE_URL`
- `PERSONA_LLM_CLI`
- `PERSONA_LLM_MODEL_PATH`
- `PERSONA_LLM_EXTRA_ARGS`

Examples:

```powershell
$env:PERSONA_LLM_BACKEND="qwen-ollama"
$env:PERSONA_LLM_MODEL="qwen3:4b"
```

or:

```powershell
$env:PERSONA_LLM_BACKEND="qwen-llama-cpp"
$env:PERSONA_LLM_MODEL_PATH="C:\models\Qwen3-4B.gguf"
$env:PERSONA_LLM_CLI="C:\llama.cpp\llama-cli.exe"
```

## Local app

Persona now includes a minimal local web app served on localhost.

Workflow:

- home page: list local documents and upload a new one
- detail page: show original preview, anonymized preview, detected blocks, and review state
- review actions: approve, reject, edit masked block
- confirm anonymization
- restore when censored file + map exist

The web app uses local storage only. Default workspace:

```text
~/.persona/workspace/
  originals/
  censored/
  maps/
  restored/
  metadata/
```

Metadata is stored as simple JSON files. No database is used.

## CLI

The CLI remains fully functional and uses the same engine as the web app.

### Anonymize

```powershell
.\.venv\Scripts\python.exe -m persona.cli anonymize .\sample.docx --password-prompt --backend qwen-ollama --model-ref qwen3:4b
```

For contract/testing with the mock backend:

```powershell
$env:PERSONA_LLM_BACKEND="mock"
.\.venv\Scripts\python.exe -m persona.cli anonymize .\sample.docx --password-prompt
```

### Restore

```powershell
.\.venv\Scripts\python.exe -m persona.cli restore .\sample.censored.docx --map .\sample.persona-map.json --password-prompt
.\.venv\Scripts\python.exe -m persona.cli restore .\sample.censored.docx --map .\sample.persona-map.json --binding-mode strict --password-prompt
```

### Run local app

```powershell
.\.venv\Scripts\python.exe -m persona.cli app --backend qwen-ollama --model-ref qwen3:4b
```

Then open:

```text
http://127.0.0.1:8765
```

## Deterministic masking and restore

Persona still reuses the existing deterministic core:

- stable token ids via keyed HMAC
- structural masking preserving spaces, punctuation, and broad alphanumeric shape
- encrypted local map with AES-256-GCM
- Argon2id for password-based key derivation
- strict placeholder validation during restore
- document binding metadata for pragmatic/strict restore modes

Placeholder format for current output:

```text
[[P2|TOKEN_ID|TAG|MASKED_BLOCK]]
```

Legacy `P1` placeholders and legacy maps remain supported where possible.

## Legacy components

The old Presidio/spaCy fixed-entity detector still exists in the repository as legacy support and test coverage, but it is no longer the product centerline. The primary path is now:

- local LLM block detection
- deterministic engine
- local web app + CLI on top

## Tests

Run the full suite with:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Current coverage includes:

- encrypted map / keystore / restore integrity paths
- block-oriented LLM response parsing and validation
- overlap resolution for multi-word blocks
- engine anonymize + restore with mock backend
- local web app upload/review/anonymize flow
- DOCX/XLSX/PDF adapters
- binding pragmatic vs strict

## Known limitations

- PDF remains best-effort and is the weakest format both for layout fidelity and binding strength
- the web app preview is logical-text preview, not faithful visual rendering of DOCX/XLSX/PDF layouts
- Qwen runtime integration is implemented architecturally, but real execution depends on the user’s local runtime setup
- no OCR
- no image/textbox/header/footer handling
- no formulas rewrite in Excel
- no embedded in-file Persona marker yet

## More detail

- [docs/architecture.md](docs/architecture.md)
- [docs/security.md](docs/security.md)

## Development Process

Built with AI-assisted workflows, while architecture, tradeoffs, integration, review, and validation were directed by the author.
