# Changelog

## Unreleased

### Security

- `anonymize` now saves the vault before moving the anonymized file into place. Previously a crash between the two steps could leave an anonymized file whose placeholders were never stored, so it could not be restored.
- DOCX/XLSX parts are parsed with entity resolution, DTD loading and network access disabled. A part that declares a DTD is refused with an error (Office files never contain one). This closes an XML external entity (XXE) vector.
- Vault KDF parameters read from a file are validated before key derivation: time cost 1..10, memory 8*parallelism KiB..1 GiB, parallelism 1..8, 32-byte key. Out-of-range values give a clear error instead of an unbounded allocation.
- New vault format version 2: the version, KDF parameters and salt are authenticated as AES-GCM associated data. Version 1 vaults are still read and are rewritten as version 2 on the next save. Note: once saved, a vault can no longer be opened by older Persona releases.

### Added

- Rotating vault backups: before each save the previous file is kept as `<name>.vault.bak`, `.bak.1`, `.bak.2`.
- `persona rekey` changes the vault password (new salt, current KDF settings). The new password comes from `PERSONA_NEW_PASSWORD` or an interactive prompt. Backups encrypted with the old password are deleted.
- Batch mode: `persona anonymize <dir>` processes every supported file in a directory, `--recursive` includes subdirectories, `--out` mirrors the tree in another directory. Hidden files and earlier outputs (`*.anon.*`, `*.restored.*`) are skipped; a blocked file does not stop the others.
- `--json` prints a report with paths, statuses and counts. It never contains detected values.
- `--stdin` reads text from standard input and `--stdout` writes the anonymized text to standard output (text inputs only).
- Column-header detection in XLSX sheets and DOCX tables: every non-empty cell below a header such as `Nome`, `Cognome`, `Cliente`, `Email`, `Telefono`, `Codice Fiscale`, `P.IVA`, `Indirizzo` (or English equivalents) is masked whole with the matching kind.
- Names written surname first (`Rossi Mario`, `BIANCHI Laura`) are detected.
- Foreign phone numbers without `+`: the `00` international prefix (`0044 20 7946 0958`) and numbers after a label such as `Tel.` or `phone:` (`(212) 555-0147`).
- `persona` now re-exports the stable Python API: `Vault`, `anonymize_text`, `restore_text`, `verify`.

### Changed

- Name aliases are derived only from profile URLs (LinkedIn, GitHub, GitLab, Bitbucket, X/Twitter, Facebook, Instagram, TikTok, YouTube, Telegram). Ordinary web addresses such as `www.acme.com/prodotti` no longer turn path words into masked "names". Only the profile handle is used, not later path parts or query strings.
- `.txt` and `.md` files are read as UTF-8 (BOM accepted and written back) with a Windows-1252 fallback, and line endings are preserved exactly. Output is always UTF-8.
- `--review` together with `--dry-run` now prints a warning that the review is skipped.
- Faster overlap resolution and verification: spans are sorted once and search patterns are compiled once per run instead of once per segment.
- Detection word lists (name particles, stop words) live in one module, `persona/detect/vocabulary.py`.

### Development

- `ruff` is part of the `dev` extras and runs in CI; the test matrix now includes Windows.
- A single `fast_kdf` fixture replaces the per-file patching of Argon2 defaults in tests.
