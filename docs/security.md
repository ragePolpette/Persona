# Security

## Threat model for v1

Persona reduces the risk of exposing raw sensitive text to external AI tools by keeping anonymization and restore local. It does not defend against a compromised workstation, malware, or a stolen unlocked user session.

## Keystore

On first use, Persona creates a local persistent root key.

- the root key is random
- the root key is stored encrypted on disk
- the encryption key is derived from the user password with Argon2id
- the keystore payload is protected with AES-256-GCM

The persistent root key is used for deterministic keyed token generation across sessions.

## Deterministic token ids

Stable ids are derived conceptually as:

```text
token_id = HMAC(root_key, canonical(entity_type + ":" + original_value))
```

Properties:

- deterministic with the same local root key
- different across different root keys
- not a plain public hash of the original value

## Canonicalization

Canonicalization is entity-specific:

- emails are normalized and case-folded
- phone numbers keep an optional leading `+` and collapse to digits
- names collapse whitespace and case-fold
- IBAN and fiscal code values are normalized in uppercase

This keeps token generation stable across equivalent surface forms.

## Masked payloads

The visible masked payload is also deterministic and keyed. It aims to preserve:

- length
- spacing
- punctuation
- broad alphanumeric shape

The masked payload is not intended to be cryptographically reversible on its own. Reversal depends on the encrypted local map.

## Placeholder integrity marker

Current anonymization output uses a `P2` placeholder format with a short integrity marker:

```text
[[P2|TOKEN_ID|TAG|MASKED_VALUE]]
```

`TAG` is derived locally from the persistent root key, token id, and masked value. During restore, Persona checks that the placeholder:

- is well formed
- belongs to an expected token
- matches the encrypted map entry
- carries the expected integrity marker for current-format placeholders

Legacy `P1` placeholders are still accepted for restore.

## Encrypted map

The encrypted map contains at least:

- format version
- document metadata
- token id
- entity type
- original value
- masked value
- logical location and offsets

Map files are encrypted with:

- Argon2id-derived key material
- AES-256-GCM authenticated encryption

## Strict restore

Restore is strict by default.

- exact intact placeholders are restored
- altered placeholders are not restored
- altered placeholders are left in place
- malformed, duplicate, and unexpected placeholders are left in place
- structured issues and counts are emitted in the restore report

This avoids restoring text into placeholders that no longer match the encrypted map.

## Failure normalization

Keystore and map failures are normalized into domain errors for:

- wrong password
- malformed JSON
- malformed encryption envelope
- AES-GCM authentication failure
- malformed decrypted payload

## Non-goals in v1

- OCR
- secret sharing
- centralized key management
- tamper-proof endpoint security
- advanced DLP policy engines
