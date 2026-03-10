# Security

## Scope

Persona is a local/offline anonymization system. The security goal is not endpoint hardening; it is controlled reversible anonymization of local documents without sending content to cloud services.

This design still does not defend against:

- compromised hosts
- malware on the user workstation
- memory scraping on an unlocked machine
- theft of decrypted working files

## Security-critical split

The new LLM-guided detection path changes what identifies sensitive content, but it does not change the deterministic security core.

Security-relevant responsibilities remain split as follows:

- local LLM backend
  - identifies sensitive blocks only
- deterministic engine
  - generates stable token ids
  - generates masked blocks
  - creates placeholders
  - writes encrypted maps
  - restores original values
  - verifies binding and placeholder integrity

The LLM never generates placeholders or replacement text directly.

## Root key and keystore

Persona still uses a persistent local root key.

Properties:

- generated randomly on first use
- stored encrypted on disk
- wrapped with a password-derived key
- used for stable token ids and deterministic masking across sessions

Keystore protection:

- KDF: Argon2id
- encryption: AES-256-GCM

## Encrypted map

The encrypted map still stores the sensitive reversible state.

At minimum it contains:

- document metadata
- binding metadata
- token id
- optional block label
- original block text
- masked block text
- placeholder
- logical location / offsets
- optional score / reason metadata from reviewable findings

Map files are encrypted with:

- Argon2id-derived key material
- AES-256-GCM authenticated encryption

## Block-oriented masking

The new model detects whole logical blocks, but masking remains deterministic and structural.

Preserved as much as possible:

- length
- spaces
- punctuation
- broad alpha/numeric shape

This is useful for review and document readability, but it leaks some structural information about the original block. That tradeoff is unchanged from the prior design and remains intentional.

## Placeholder integrity

Current generated placeholders use:

```text
[[P2|TOKEN_ID|TAG|MASKED_BLOCK]]
```

Where:

- `TOKEN_ID` is stable and keyed
- `TAG` is derived from local key material, token id, and masked block

Restore verifies:

- placeholder shape
- token presence in map
- exact placeholder equality when expected
- integrity tag for `P2`

Legacy `P1` placeholders are still accepted for compatibility.

## Document binding

The recent hardening work remains in effect and now applies to the LLM-guided engine as well.

The encrypted map stores binding metadata for both original and censored files, including:

- file format
- exact file hash
- logical-content fingerprint
- structural fingerprint
- segment count

Restore modes:

- `pragmatic`
  - continue when binding is weak but still report issues
- `strict`
  - refuse restore before output when the file/map pair is not compatible enough

This binding is stronger than simple placeholder matching, but it is still not equivalent to a cryptographically signed in-file provenance marker.

## Local LLM backend considerations

Persona now depends on a local LLM runtime for detection quality.

Important consequences:

- detection quality depends on the local runtime and prompt adherence
- malformed or ambiguous JSON from the local runtime is rejected by validation code
- the model is not trusted to rewrite the source text
- the model is not trusted to produce replacements or restore logic

This keeps the LLM on the narrowest possible part of the trust boundary.

## Web app considerations

The local app introduces a browser surface but remains local-only.

Current properties:

- local FastAPI process
- no remote calls by design in Persona itself
- local JSON metadata storage
- logical-text preview only

Current limits:

- no authentication layer inside the local app
- no multi-user isolation
- no CSRF/session hardening aimed at hostile local networks

This is acceptable for a single-user localhost tool, but it is not a hardened multi-user desktop product.

## Error handling

Failure normalization remains important.

Domain errors cover at least:

- wrong password
- malformed keystore/map JSON
- AES-GCM authentication failure
- malformed decrypted payload
- unsupported format
- strict binding refusal
- invalid LLM output
- local backend runtime failures

The intent is that users see clean operational errors rather than raw library stack traces.

## Remaining security limitations

- no OCR
- no secure deletion of originals/censored/restored files
- no OS-native secret-store integration yet
- no embedded Persona marker in output files yet
- PDF support remains weaker for both fidelity and binding confidence
- the app preview is extracted logical text, not a secure visual diff of the actual document layout
