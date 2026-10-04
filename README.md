# Persona

Share documents with an AI without exposing the sensitive data of your clients, suppliers or anyone else, then bring the AI's output back to a usable document.

```
document ──anonymize──▶ [PERSONA_1] signed with [AZIENDA_2] ──▶ AI ──▶ edited file ──restore──▶ usable document
              │                                                                          ▲
              └──────────── encrypted per-project vault (stays on your machine) ─────────┘
```

> **Status: early rewrite.** The engine and CLI work for `.docx`, `.txt`, `.md` and text-based `.pdf` (read as extracted text). XLSX, a review UI and an optional local-LLM detector are next.

## Quick start

```bash
pip install -e ".[dev]"        # add the pdf extra ("persona[pdf]") if you only need PDF input

persona init -p acme                                   # create the encrypted vault
persona glossary add "Tessitura Valdarno S.r.l." -k AZIENDA -a Tessitura -p acme
persona anonymize contract.md -p acme --dry-run        # see what would be masked
persona anonymize contract.md -p acme                  # -> contract.anon.md (after a safety check)

persona anonymize offer.docx -p acme                   # -> offer.anon.docx, formatting kept
persona anonymize cv.pdf -p acme                       # PDFs are read as text -> cv.anon.txt

# ...work on contract.anon.md with an AI, save its answer as answer.md...

persona restore answer.md --sent contract.anon.md -p acme   # -> answer.restored.md
```

The password is asked interactively, or read from `PERSONA_PASSWORD`. Vaults live in `~/.persona/projects/` (override with `PERSONA_HOME`).

## How it works

- **Short, readable placeholders** (`[PERSONA_1]`, `[AZIENDA_2]`, `[IBAN_1]`): the kind tells the AI what the thing is, so it can write around it naturally.
- **One vault per project**: the same value is always the same placeholder, across all documents of a client. The vault is a single AES-256-GCM file (Argon2id key) holding the mapping and your glossary.
- **Detection in layers**: your glossary (highest recall: you know your clients), checksum-validated identifiers (IBAN, codice fiscale, P.IVA, e-mail), phone numbers, profile/web URLs, and heuristics for names (titles, a list of common Italian first names, labels like `Cognome:`, names hidden in e-mail addresses and profile URLs), company suffixes, institutions (`Liceo …`, `Cooperativa …`) and street addresses. A value found once is masked everywhere, including in later documents of the project.
- **Safety check before sharing**: the file that was actually written is re-opened and re-scanned for every known value and for anything the detectors still find. If something is left, nothing is written (`--force` overrides).
- **DOCX goes deep**: body, tables, headers, footers, footnotes/endnotes, comments, text boxes, tracked deletions, field codes (`HYPERLINK "mailto:…"`), hyperlink targets, image alt text, custom XML and document properties are all analysed. Formatting is kept: a placeholder inherits the run it starts in, even when the name was split across differently formatted runs. Who-made-the-file traces are scrubbed: author / last-modified-by / company, comment and revision authors, the page thumbnail and the people list. Scrubbed fields are not restored.
- **Restore works on any text**, not on a specific file: the AI never returns the file you sent. Placeholders are matched tolerantly (case, brackets, markdown escapes like `\[PERSONA\_1\]`) and the report lists placeholders the AI **invented**, **dropped** or **altered**.

Details and trade-offs: [docs/design.md](docs/design.md).

## What it catches today

Measured on the synthetic Italian corpus in `tests/corpus` (9 documents including a CV, 88 sensitive values; run `pytest tests/test_corpus.py -s`):

| | Without glossary | With glossary |
|---|---|---|
| E-mail, phone, IBAN, codice fiscale, P.IVA, addresses, URLs | 46/46 | 46/46 |
| Companies and institutions | 17/19 | 19/19 |
| People | 20/23 | 23/23 |
| **Total** | **83/88** | **88/88** |

What still needs the glossary: companies and schools without a legal suffix or a known keyword (`Officine Digitali Veronesi`), and a bare first name with no surname next to it (`Ciao Giulia`) unless the full name appears elsewhere in the same project. Cities are deliberately **not** masked.

Reality check on one real two-page PDF CV (not committed): address, phone, e-mail, name, LinkedIn and GitHub URLs and a school were caught with no setup; four employers/schools (no suffix) were not, and four glossary entries fixed that. The corpus is written by the author, so treat its numbers as a regression ratchet, not a guarantee. **Always review before sending real data.**

## Limits worth knowing

- **Text inside images, charts, SmartArt and embedded objects is not anonymized.** Persona warns when a DOCX contains them; check them by hand.
- Removing names does not remove identifiability from context ("the only supplier of X in Y").
- If the AI derives new forms (`M. Rossi`, an e-mail built from a name) they are not in the vault and are not restored.
- If the original text already contains something that looks like `[PERSONA_1]`, restore will treat it as a placeholder.
- The same entity written in different ways (`ACME S.R.L.` / `Acme S.r.l.`) gets different placeholders, so restore gives back exactly what was written.
- DOCX output was checked with python-docx, XML well-formedness and zip integrity, not with Word itself: open the result in Word once before relying on it.

## Roadmap

1. XLSX adapter (cells, sheet names, comments, properties), same safety checks as DOCX.
2. Review UI to approve/reject detections and add glossary entries on the spot.
3. Optional local-LLM / NER detector for names (asked for text, never offsets), measured against the corpus.
4. OCR for scanned PDFs and images (PDF *output* stays out of scope: the AI never needs a PDF back).

## Development

```bash
pytest                        # 170 tests, ~2 s
pytest tests/test_corpus.py -s
```

Built with AI-assisted workflows; design decisions and review by the author.
