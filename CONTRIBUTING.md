# Contributing

## Workflow

1. Fork the repository and create a branch from `main`, for example `fix/docx-footnotes`.
2. Make a focused change and add or update tests.
3. Run the test suite (see below).
4. Open a pull request against `main` describing the change and why it is needed.

## Development setup

Requires Python 3.11 or later.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Tests and lint

```bash
pytest
pytest tests/test_corpus.py -s    # per-kind detection report on the synthetic corpus
```

CI runs `pytest` on Python 3.11, 3.12 and 3.13. No linter is configured at the moment. Keep the style of the surrounding code and do not add code comments.

## Security rules

- Never commit real personal data, real vaults, passwords or `.env` files. Test documents must be synthetic.
- Corpus files in `tests/corpus` must contain only invented values.
- Do not weaken the safety check or log sensitive values.
- Report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md), not in public issues.
