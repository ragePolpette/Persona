# Design

Goal: the loop **anonymize → share with an AI → get a file back → restore**.
Everything is shaped by one fact: *the file that comes back is not the file you sent.*
It may be regenerated, rewritten, converted to markdown, or have its placeholders mangled.

## Consequences

| Decision | Why |
|---|---|
| Restore operates on text, not on a file bound to a map | The AI's output has a different hash, structure and format. The previous prototype's file "binding" failed exactly when a restore was needed. |
| Placeholders are `[KIND_N]` | Short enough to survive, semantic enough for the AI to use. No integrity tag: placeholders are not secret, the vault is. |
| Placeholder matching is tolerant, reporting is strict | Models change case, brackets and escape underscores. Whatever was invented, dropped or altered is listed so nothing is silently wrong. |
| One vault per project | Same client, same placeholder, across documents. Values already in the vault are masked in new documents. |
| Verification is a separate step on the *output* | The cardinal failure is a leak to an external service. `verify` re-scans the final text; it does not trust the detectors that produced it. |
| The glossary is a first-class detector | Users know their recurring clients and suppliers; a list beats any model on recall for those. |

## Pipeline

```
segments ─▶ detectors ─▶ propagate ─▶ resolve overlaps ─▶ (review) ─▶ apply ─▶ verify ─▶ share
```

- **Segments** are named strings (a paragraph, a cell, a whole .md file), so file adapters can plug in without touching the engine.
- **Detectors** (`persona/detect`): glossary; validated identifiers (IBAN mod-97, codice fiscale and P.IVA checksums, e-mail); phones; profile/web URLs; heuristics (titled names, known first name + capitalised surname, `Nome:`/`Cognome:` labels, company suffixes, institutions such as `Liceo …`, street addresses). Labeled values (`C.F. …`, `P.IVA …`) are masked even with a wrong checksum, because a typo must not become a leak.
- **Propagation**: every detected value, plus every value in the vault, is searched across all segments (case/accent-insensitive, whole word). Bare surnames/first names of detected people ("Rossi" after "Mario Rossi") are masked case-sensitively, so "verdi" (green) survives "Anna Verdi".
- **Names hidden in handles**: `zeno.cosini@…` or `linkedin.com/in/zeno-cosini` reveal that `Zeno` and `Cosini` are names, so they are masked wherever they appear capitalised; adjacent name parts are merged into one `PERSONA` block. Generic mailbox words (`ufficio`, `info`, `amministrazione`…) are excluded.
- **Overlaps**: highest priority wins (validated > glossary > known value > pattern > heuristic > alias), then longest. A loser is not discarded: the part the winner does not cover is kept (trimmed of connectors), so a greedy heuristic match can never hide a value behind a neighbour. This fixed a real leak found with the corpus (`Giulia Marchetti di Tessitura Valdarno S.r.l.`).
- **Apply** registers values in the vault and replaces approved spans; the caller saves the vault.
- **Review** is `Span.approved`: the engine already supports rejecting detections; the UI is to come.

## Documents

`persona/documents.py`: `open_document(path)` returns segments (what the engine reads) and `write(out, edits)` (what it changes). Text and PDF are one segment. DOCX is edited at the XML level inside the zip, so nothing outside the touched text nodes is rewritten.

- Segments: every paragraph of the body, headers, footers, footnotes, endnotes, comments, glossary; text-box paragraphs are separate segments (not double-counted in the outer paragraph); tracked-deletion text and field-code text are separate streams per paragraph; external hyperlink targets; image alt text; custom XML leaf text; title/subject/keywords and `vt:` strings in document properties (heading lists in `app.xml` repeat document text).
- Edits are `(start, end, text)` on a segment's text. Characters map back to `w:t` nodes; the replacement goes in the first covered node, the rest of the covered characters are blanked, tabs and line breaks stay. So formatting follows the run where the match starts, and a placeholder the AI split over runs is still found on restore.
- Scrubbed on write, never restored: creator, last-modified-by, company, manager, hyperlink base; `w:author` / `w:initials` on revisions and comments; `people.xml`; `docProps/thumbnail.*` (a picture of page 1) and its relationship.
- `anonymize` writes to a staging file, **re-opens it**, verifies the text actually on disk, and only then moves it into place.

## Vault

Single JSON envelope: Argon2id (t=3, m=64 MiB, p=4) → AES-256-GCM, AAD `persona-vault-v1`, atomic write, mode 0600. Contents: entries (`kind`, `number`, `value`, `case_sensitive`) and the glossary. A wrong password and a tampered file are indistinguishable (GCM), and reported as such.

Identity of an entry is the **exact surface string**. `ACME S.R.L.` and `Acme S.r.l.` are two placeholders. The cost is that the AI sees two entities; the gain is that restore is byte-exact.

## Known gaps (tracked by tests or the roadmap)

- Names outside the first-name list, or a lone first name, are not detected by rules (`test_names_not_in_the_first_name_list_or_alone_are_a_known_gap`).
- Companies/institutions without a legal suffix or known keyword (`Officine Digitali Veronesi`, `Studioboost`) need the glossary.
- The first-name list is a hand-written gazetteer of ~350 common Italian names: it will miss rarer or foreign names.
- Cities are not masked, even though a city plus an employer can identify someone.
- PDFs are read as extracted text (single-column works well; multi-column order depends on the PDF); scanned PDFs are rejected (no OCR). No adapters yet for DOCX/XLSX. The previous prototype ignored headers, footers and document properties; the new adapters must include them and `verify` must run over all of it.
- Original text that looks like a placeholder is ambiguous on restore.
