from __future__ import annotations

import base64
import binascii
import json
import os
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from persona.config import MAP_VERSION
from persona.exceptions import CorruptMapError, InputFileError, MapDecryptionError
from persona.models.entities import DocumentMetadata, MapEntry
from persona.security.argon2_utils import DEFAULT_ARGON2_PARAMS, Argon2Params, derive_key

AAD = b"persona-map-v1"


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def _parse_map_envelope(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InputFileError(f"Encrypted map file not found: {path}") from exc
    except OSError as exc:
        raise CorruptMapError(f"Unable to read encrypted map file: {path}") from exc
    try:
        payload = json.loads(raw)
    except JSONDecodeError as exc:
        raise CorruptMapError("Encrypted map file is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise CorruptMapError("Encrypted map file must contain a JSON object.")
    return payload


def _extract_envelope_kdf(envelope: dict[str, Any]) -> tuple[Argon2Params, bytes]:
    if envelope.get("version") != MAP_VERSION:
        raise CorruptMapError(f"Unsupported encrypted map version: {envelope.get('version')!r}.")
    try:
        params_dict = envelope["kdf"]
        return (
            Argon2Params(
                time_cost=params_dict["time_cost"],
                memory_cost_kib=params_dict["memory_cost_kib"],
                parallelism=params_dict["parallelism"],
                hash_len=params_dict["hash_len"],
            ),
            _b64decode(params_dict["salt_b64"]),
        )
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise CorruptMapError("Encrypted map KDF parameters are malformed.") from exc


def _load_plaintext_payload(plaintext: bytes) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, JSONDecodeError) as exc:
        raise CorruptMapError("Decrypted map payload is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise CorruptMapError("Decrypted map payload must be a JSON object.")
    if payload.get("version") != MAP_VERSION:
        raise CorruptMapError(f"Unsupported decrypted map payload version: {payload.get('version')!r}.")
    try:
        document = payload["document"]
        entries = payload["entries"]
        if not isinstance(document, dict) or not isinstance(entries, list):
            raise TypeError
        DocumentMetadata(**document)
        [MapEntry.from_dict(item) for item in entries]
    except (KeyError, TypeError, ValueError) as exc:
        raise CorruptMapError("Decrypted map payload is missing required document or entry fields.") from exc
    return payload


def serialize_map_payload(document: DocumentMetadata, entries: list[MapEntry]) -> bytes:
    payload = {
        "version": MAP_VERSION,
        "document": document.to_dict(),
        "entries": [entry.to_dict() for entry in entries],
    }
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def encrypt_map_file(
    path: Path,
    password: str,
    document: DocumentMetadata,
    entries: list[MapEntry],
    params: Argon2Params = DEFAULT_ARGON2_PARAMS,
) -> None:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = derive_key(password, salt, params=params)
    plaintext = serialize_map_payload(document, entries)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, AAD)
    envelope = {
        "version": MAP_VERSION,
        "kdf": params.to_dict() | {"salt_b64": _b64encode(salt)},
        "nonce_b64": _b64encode(nonce),
        "ciphertext_b64": _b64encode(ciphertext),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")


def decrypt_map_file(path: Path, password: str) -> tuple[DocumentMetadata, list[MapEntry]]:
    envelope = _parse_map_envelope(path)
    params, salt = _extract_envelope_kdf(envelope)
    try:
        nonce = _b64decode(envelope["nonce_b64"])
        ciphertext = _b64decode(envelope["ciphertext_b64"])
    except (KeyError, ValueError, TypeError, binascii.Error) as exc:
        raise CorruptMapError("Encrypted map envelope is malformed.") from exc

    key = derive_key(password, salt, params=params)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, AAD)
    except InvalidTag as exc:
        raise MapDecryptionError("Unable to decrypt encrypted map. Check the password or map integrity.") from exc
    except ValueError as exc:
        raise CorruptMapError("Encrypted map ciphertext is malformed.") from exc

    payload = _load_plaintext_payload(plaintext)
    document = DocumentMetadata(**payload["document"])
    entries = [MapEntry.from_dict(item) for item in payload["entries"]]
    return document, entries
