# Security

## Threat model for v1

Persona is designed to keep document processing local and offline. It does not protect against a compromised workstation, but it reduces the risk of sending raw sensitive data into downstream AI tooling.

## Key points

- A local persistent root key is created on first use.
- The root key is encrypted at rest with a key derived from the user password using Argon2id.
- Stable token ids are generated with keyed HMAC-SHA256 over canonicalized values.
- Encrypted map files use AES-256-GCM with explicit versioning and integrity protection.
- Restore is strict by default and does not rehydrate altered placeholders.

## Non-goals in v1

- OCR
- malware-resistant secret storage
- collaborative key sharing
- advanced DLP policy engines

