from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from persona.config import MAP_VERSION
from persona.models.entities import DocumentMetadata, MapEntry
from persona.security.argon2_utils import DEFAULT_ARGON2_PARAMS, Argon2Params, derive_key

AAD = b"persona-map-v1"


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


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
    envelope = json.loads(path.read_text(encoding="utf-8"))
    params_dict = envelope["kdf"]
    params = Argon2Params(
        time_cost=params_dict["time_cost"],
        memory_cost_kib=params_dict["memory_cost_kib"],
        parallelism=params_dict["parallelism"],
        hash_len=params_dict["hash_len"],
    )
    key = derive_key(password, _b64decode(params_dict["salt_b64"]), params=params)
    plaintext = AESGCM(key).decrypt(
        _b64decode(envelope["nonce_b64"]),
        _b64decode(envelope["ciphertext_b64"]),
        AAD,
    )
    payload: dict[str, Any] = json.loads(plaintext.decode("utf-8"))
    document = DocumentMetadata(**payload["document"])
    entries = [MapEntry.from_dict(item) for item in payload["entries"]]
    return document, entries

