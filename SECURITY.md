# Security Policy

## Scope

Persona is a local command-line tool. It masks sensitive values in documents before they are shared with an external service (typically an AI), and restores them afterwards. In scope:

- The encrypted vault (`persona/vault.py`): AES-256-GCM with an Argon2id derived key.
- The anonymization pipeline, including the safety check that re-reads the written file.
- DOCX and XLSX handling, including removal of author and revision metadata.
- The restore step.

## Threat model

Persona assumes the machine running it is trusted and the external service is not. The goal is that the file you share does not contain the values stored in the vault or values the detectors recognise.

What Persona does:

- Keeps the placeholder-to-value mapping only in the vault, encrypted with a password-derived key.
- Re-opens the file it wrote and scans it again before declaring it shareable; if anything is found, nothing is written unless `--force` is used.
- Scrubs author, last-modified-by, company and revision/comment author fields, and the page thumbnail, in DOCX/XLSX output.

What Persona does not protect against:

- Sensitive values that no detector or glossary entry matches. Detection is heuristic. Review the output before sending real data.
- Text inside images, charts, SmartArt, pivot tables, drawings, external links, data connections and macros. Persona warns about these but does not process them.
- Identifiers stored as numbers in spreadsheets.
- Identification from context (for example "the only supplier of X in Y").
- A compromised local machine, a weak vault password, or a password exposed through the `PERSONA_PASSWORD` environment variable.
- The behaviour of the service that receives the anonymized file.

## Reporting a vulnerability

Please report privately through GitHub Security Advisories: open the repository's Security tab and choose "Report a vulnerability". If that is not available, open a minimal issue asking for a private contact channel, without technical details or sample data.

Do not include real personal data in reports. Use synthetic examples.

Useful reports include a leak that the safety check misses, a flaw in the vault format or key handling, and a restore behaviour that returns the wrong value.

## Not covered

- Missed detections of ordinary sensitive values in unusual formats. These are accuracy issues; open a normal issue with a synthetic example.
- Issues that require an already compromised machine or access to the unlocked vault.
- Vulnerabilities in third-party dependencies that have no demonstrated effect on Persona.
