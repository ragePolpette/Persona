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

from persona.config import CONFIG_DIR, KEYSTORE_PATH, KEYSTORE_VERSION
from persona.exceptions import CorruptKeystoreError, InputFileError, KeystoreDecryptionError
from persona.security.argon2_utils import DEFAULT_ARGON2_PARAMS, Argon2Params, derive_key

AAD = b"persona-keystore-v1"


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parse_keystore_payload(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InputFileError(f"Keystore file not found: {path}") from exc
    except OSError as exc:
        raise CorruptKeystoreError(f"Unable to read keystore file: {path}") from exc

    try:
        payload = json.loads(raw)
    except JSONDecodeError as exc:
        raise CorruptKeystoreError("Keystore file is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise CorruptKeystoreError("Keystore file must contain a JSON object.")
    return payload


def _extract_kdf_params(payload: dict[str, Any]) -> tuple[Argon2Params, bytes]:
    if payload.get("version") != KEYSTORE_VERSION:
        raise CorruptKeystoreError(f"Unsupported keystore version: {payload.get('version')!r}.")
    try:
        params_dict = payload["kdf"]
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
        raise CorruptKeystoreError("Keystore KDF parameters are malformed.") from exc


def resolve_keystore_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    override = os.environ.get("PERSONA_KEYSTORE_PATH")
    return Path(override) if override else KEYSTORE_PATH


def create_keystore(password: str, path: Path | None = None, params: Argon2Params = DEFAULT_ARGON2_PARAMS) -> bytes:
    resolved_path = resolve_keystore_path(path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    root_key = os.urandom(32)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    kek = derive_key(password, salt, params=params)
    ciphertext = AESGCM(kek).encrypt(nonce, root_key, AAD)
    payload = {
        "version": KEYSTORE_VERSION,
        "kdf": params.to_dict() | {"salt_b64": _b64encode(salt)},
        "nonce_b64": _b64encode(nonce),
        "ciphertext_b64": _b64encode(ciphertext),
    }
    _write_json(resolved_path, payload)
    return root_key


def load_root_key(password: str, path: Path | None = None) -> bytes:
    resolved_path = resolve_keystore_path(path)
    payload = _parse_keystore_payload(resolved_path)
    params, salt = _extract_kdf_params(payload)
    try:
        nonce = _b64decode(payload["nonce_b64"])
        ciphertext = _b64decode(payload["ciphertext_b64"])
    except (KeyError, ValueError, TypeError, binascii.Error) as exc:
        raise CorruptKeystoreError("Keystore encryption envelope is malformed.") from exc

    kek = derive_key(password, salt, params=params)
    try:
        return AESGCM(kek).decrypt(nonce, ciphertext, AAD)
    except InvalidTag as exc:
        raise KeystoreDecryptionError("Unable to decrypt local keystore. Check the password or keystore integrity.") from exc
    except ValueError as exc:
        raise CorruptKeystoreError("Keystore ciphertext is malformed.") from exc


def ensure_root_key(password: str, path: Path | None = None) -> bytes:
    resolved_path = resolve_keystore_path(path)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if resolved_path.exists():
        return load_root_key(password, path=resolved_path)
    return create_keystore(password, path=resolved_path)
