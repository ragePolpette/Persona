# Persona

Persona is a fully local, offline-first Python CLI for anonymizing sensitive data in documents before sharing them with LLMs, agents, or other tooling.

## Goals

- Analyze a local file without sending data to external services
- Detect sensitive entities locally
- Propose deterministic censorship placeholders
- Require an interactive review step before writing outputs
- Produce a censored copy of the original file
- Produce an encrypted local map for later restoration
- Restore original values only when placeholder integrity checks pass

## Supported formats in v1

- `.docx`
- `.xlsx`
- text-based `.pdf`

## Explicit v1 limits

- No `.doc`
- No `.xls`
- No OCR
- No GUI or web app
- No cloud services
- No image/textbox/header/footer editing
- No advanced Excel formula rewriting
- PDF output is best-effort and may not preserve complex layouts

## Local-only model

Persona does not call external APIs during anonymization or restore. Detection is built around:

- deterministic recognizers and regex-based recognizers
- Presidio for recognizer orchestration
- spaCy local NLP for baseline NER

## Security model

- local persistent root key protected by a password-derived key
- Argon2id for key derivation
- AES-256-GCM for encrypted map files
- deterministic keyed HMAC tokens for stable placeholders across sessions
- strict restore behavior when placeholders are altered

More detail lives in [docs/architecture.md](docs/architecture.md) and [docs/security.md](docs/security.md).

## Installation

```bash
uv venv
uv pip install -e .[dev]
python -m spacy download en_core_web_sm
```

`en_core_web_sm` is required for PERSON detection through the local spaCy pipeline.

## CLI

```bash
persona anonymize sample.docx --password-prompt
persona restore sample.censored.docx --map sample.persona-map.json --password-prompt
```

## Review flow

By default `persona anonymize` opens an interactive review. For every match it shows:

- internal id
- entity type
- detected value
- local context
- logical position
- proposed replacement

The user can approve, reject, or replace the masked payload manually for that specific match.

## Repository status

This repository is being bootstrapped as a clean baseline with tests, format adapters, restore flow, and GitHub-ready packaging.

