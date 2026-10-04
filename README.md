# Persona

Share documents with an AI without exposing the sensitive data of your clients, suppliers or anyone else, then bring the AI's output back to a usable document.

```
document ──anonymize──▶ [PERSONA_1] signed with [AZIENDA_2] ──▶ AI ──▶ edited file ──restore──▶ usable document
              │                                                                          ▲
              └──────────── encrypted per-project vault (stays on your machine) ─────────┘
```

> **Status: early rewrite.** The engine and CLI work for `.docx`, `.xlsx`, `.txt`, `.md` and text-based `.pdf` (read as extracted text). A review UI and an optional local-LLM detector are next.

## Quick start

```bash
pip install -e ".[dev]"        # add the pdf extra ("persona[pdf]") if you only need PDF input

persona init -p acme                                   # create the encrypted vault
persona glossary add "Tessitura Valdarno S.r.l." -k AZIENDA -a Tessitura -p acme
persona anonymize contract.md -p acme --dry-run        # see what would be masked
persona anonymize contract.md -p acme                  # -> contract.anon.md (after a safety check)

persona anonymize offer.docx -p acme                   # -> offer.anon.docx, formatting kept
persona anonymize clients.xlsx -p acme                 # -> clients.anon.xlsx, sheets/formulas kept consistent
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
- **XLSX goes deep too**: shared and inline strings (rich text included), formulas, cached results, **sheet names** and defined names (renamed consistently, bracket-less `AZIENDA_1` because Excel forbids `[ ]` in sheet names; formulas pointing at them are updated the same way), hyperlinks, headers/footers, validation texts, legacy and threaded comments, table column names, document properties. Numbers stay numbers; layout, charts and styles are untouched because only text nodes are edited. Phonetic guides of masked strings are dropped (they would reveal the original).
- **Restore works on any text**, not on a specific file: the AI never returns the file you sent. Placeholders are matched tolerantly (case, brackets, markdown escapes like `\[PERSONA\_1\]`) and the report lists placeholders the AI **invented**, **dropped** or **altered**.

Details and trade-offs: [docs/design.md](docs/design.md).

## What it catches today

Measured on the synthetic corpus in `tests/corpus` (15 documents, 146 sensitive values; run `pytest tests/test_corpus.py -s`). Eight documents are Italian business texts (contracts, e-mail, minutes, invoice, CV…); six are a "hard set" with e-mail threads, foreign invoices and addresses (DE/ES/UK), EU VAT numbers, a declaration with birth date / plate / ID number, minutes with surnames only, an English contract.

| | Without glossary | With glossary |
|---|---|---|
| E-mail, phone (IT and international), IBAN, codice fiscale, VAT/P.IVA, addresses (IT/DE/ES/FR/UK), URLs, birth date / plate / ID number | 82/82 | 82/82 |
| Companies and institutions | 24/26 | 26/26 |
| People | 34/38 | 38/38 |
| **Total** | **140/146** | **146/146** |

What still needs the glossary: companies and schools without a legal suffix or known keyword (`Officine Digitali Veronesi`), and a bare first name with no surname beside it (`Ciao Francesca`) unless the full name appears elsewhere in the same project. Cities are deliberately **not** masked unless they are part of an address with a postcode.

How much to trust these numbers: the hard set scored **43/58 before** its rules existed and **57/58 after**, but the rules were written after looking at those misses, so that set is now *seen* data. The corpus is author-written; treat the numbers as a regression ratchet, not a guarantee. The only independent test so far is one real PDF CV (not committed): address, phone, e-mail, name, LinkedIn/GitHub URLs and a school were caught with no setup; four employers/schools without a suffix needed glossary entries. **Always review before sending real data.**

Known over-masking (by design, never the other way round): a capitalised first name followed by a capitalised word is treated as a person (`Aurora Borealis`, `Victoria Station`), `Dr. House` is a person, a real street name in running text is an address.

## Limits worth knowing

- **Text inside images, charts, SmartArt, pivot tables, drawings/shapes, external links, data connections and macros is not anonymized.** Persona warns when a DOCX/XLSX contains them; check them by hand.
- **Identifiers stored as numbers** in a spreadsheet (a phone or P.IVA typed as `3384567890`) cannot be detected as text. Persona warns with the cells; mask them by hand.
- Removing names does not remove identifiability from context ("the only supplier of X in Y").
- If the AI derives new forms (`M. Rossi`, an e-mail built from a name) they are not in the vault and are not restored.
- If the original text already contains something that looks like `[PERSONA_1]`, restore will treat it as a placeholder.
- The same entity written in different ways (`ACME S.R.L.` / `Acme S.r.l.`) gets different placeholders, so restore gives back exactly what was written.
- DOCX/XLSX output was checked with python-docx / openpyxl, XML well-formedness and zip integrity, not with Word or Excel themselves: open the result once before relying on it.

## Roadmap

1. Review UI to approve/reject detections and add glossary entries on the spot.
2. Optional local-LLM / NER detector for names (asked for text, never offsets), measured against the corpus.
3. OCR for scanned PDFs and images (PDF *output* stays out of scope: the AI never needs a PDF back).

## Development

```bash
pytest                        # 253 tests, ~3 s
pytest tests/test_corpus.py -s
```

Built with AI-assisted workflows; design decisions and review by the author.
