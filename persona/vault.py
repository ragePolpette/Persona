"""Per-project encrypted vault: placeholder <-> original value, plus the user's glossary.

One vault per project/client, so the same value gets the same placeholder in every
document of that project. The whole file is AES-256-GCM encrypted with an Argon2id-derived key.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from persona.exceptions import InputError, VaultError, WrongPasswordError
from persona.placeholders import KINDS, format_placeholder

VAULT_VERSION = 1
_AAD = b"persona-vault-v1"


@dataclass(slots=True)
class Argon2Params:
    time_cost: int = 3
    memory_cost_kib: int = 65536
    parallelism: int = 4
    hash_len: int = 32


@dataclass(slots=True)
class VaultEntry:
    kind: str
    number: int
    value: str
    case_sensitive: bool = False  # set for bare surname/first-name aliases

    @property
    def placeholder(self) -> str:
        return format_placeholder(self.kind, self.number)


@dataclass(slots=True)
class GlossaryTerm:
    term: str
    kind: str
    aliases: list[str] = field(default_factory=list)

    @property
    def all_forms(self) -> list[str]:
        return [self.term, *self.aliases]


class Vault:
    def __init__(self, path: Path, key: bytes, salt: bytes, params: Argon2Params) -> None:
        self.path = path
        self._key = key
        self._salt = salt
        self._params = params
        self._by_value: dict[str, VaultEntry] = {}
        self._by_ref: dict[tuple[str, int], VaultEntry] = {}
        self._counters: dict[str, int] = {}
        self.glossary: list[GlossaryTerm] = []

    # -- lifecycle -----------------------------------------------------------------

    @classmethod
    def create(cls, path: Path, password: str, params: Argon2Params | None = None) -> "Vault":
        path = Path(path)
        if path.exists():
            raise VaultError(f"Vault already exists: {path}")
        params = params or Argon2Params()
        salt = os.urandom(16)
        vault = cls(path, _derive_key(password, salt, params), salt, params)
        vault.save()
        return vault

    @classmethod
    def open(cls, path: Path, password: str) -> "Vault":
        path = Path(path)
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise VaultError(f"Vault not found: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise VaultError(f"Unreadable vault file: {path}") from exc
        try:
            if envelope["version"] != VAULT_VERSION:
                raise VaultError(f"Unsupported vault version: {envelope['version']!r}")
            params = Argon2Params(**envelope["kdf"]["params"])
            salt = _b64d(envelope["kdf"]["salt"])
            nonce = _b64d(envelope["nonce"])
            ciphertext = _b64d(envelope["ciphertext"])
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise VaultError("Malformed vault envelope.") from exc
        key = _derive_key(password, salt, params)
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, _AAD)
        except InvalidTag as exc:
            raise WrongPasswordError("Wrong password, or the vault file was modified.") from exc
        vault = cls(path, key, salt, params)
        vault._load(plaintext)
        return vault

    def save(self) -> None:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, self._dump(), _AAD)
        envelope = {
            "version": VAULT_VERSION,
            "kdf": {"params": vars_of(self._params), "salt": _b64e(self._salt)},
            "nonce": _b64e(nonce),
            "ciphertext": _b64e(ciphertext),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".vault-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(envelope, handle)
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    # -- entries -------------------------------------------------------------------

    @property
    def entries(self) -> list[VaultEntry]:
        return sorted(self._by_ref.values(), key=lambda e: (e.kind, e.number))

    def placeholder_for(self, kind: str, value: str, *, case_sensitive: bool = False) -> str:
        """Placeholder for `value`, creating it if new. The caller is responsible for `save()`.

        Identity is the exact surface string: "ACME S.R.L." and "Acme S.r.l." get separate
        placeholders, so restoring gives back exactly what was in the document.
        """
        existing = self._by_value.get(value)
        if existing is not None:
            return existing.placeholder
        if kind not in KINDS:
            raise InputError(f"Unknown kind '{kind}'. Valid kinds: {', '.join(KINDS)}.")
        number = self._counters.get(kind, 0) + 1
        entry = VaultEntry(kind=kind, number=number, value=value, case_sensitive=case_sensitive)
        self._register(entry)
        return entry.placeholder

    def lookup(self, kind: str, number: int) -> VaultEntry | None:
        return self._by_ref.get((kind, number))

    def add_glossary(self, term: str, kind: str, aliases: list[str] | None = None) -> GlossaryTerm:
        if kind not in KINDS:
            raise InputError(f"Unknown kind '{kind}'. Valid kinds: {', '.join(KINDS)}.")
        term = term.strip()
        if not term:
            raise InputError("Glossary term cannot be empty.")
        clean_aliases = [a.strip() for a in (aliases or []) if a.strip()]
        for item in self.glossary:
            if item.term == term:
                item.kind = kind
                item.aliases = sorted(set(item.aliases) | set(clean_aliases))
                return item
        item = GlossaryTerm(term=term, kind=kind, aliases=sorted(set(clean_aliases)))
        self.glossary.append(item)
        return item

    # -- serialization ---------------------------------------------------------------

    def _register(self, entry: VaultEntry) -> None:
        self._by_value[entry.value] = entry
        self._by_ref[(entry.kind, entry.number)] = entry
        self._counters[entry.kind] = max(self._counters.get(entry.kind, 0), entry.number)

    def _dump(self) -> bytes:
        payload: dict[str, Any] = {
            "entries": [
                {"kind": e.kind, "number": e.number, "value": e.value}
                | ({"case_sensitive": True} if e.case_sensitive else {})
                for e in self.entries
            ],
            "glossary": [
                {"term": g.term, "kind": g.kind, "aliases": g.aliases} for g in self.glossary
            ],
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _load(self, plaintext: bytes) -> None:
        try:
            payload = json.loads(plaintext.decode("utf-8"))
            for item in payload["entries"]:
                self._register(
                    VaultEntry(
                        kind=item["kind"],
                        number=int(item["number"]),
                        value=item["value"],
                        case_sensitive=bool(item.get("case_sensitive", False)),
                    )
                )
            for item in payload["glossary"]:
                self.glossary.append(
                    GlossaryTerm(term=item["term"], kind=item["kind"], aliases=list(item["aliases"]))
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise VaultError("Vault payload is malformed.") from exc


def vars_of(params: Argon2Params) -> dict[str, int]:
    return {
        "time_cost": params.time_cost,
        "memory_cost_kib": params.memory_cost_kib,
        "parallelism": params.parallelism,
        "hash_len": params.hash_len,
    }


def _derive_key(password: str, salt: bytes, params: Argon2Params) -> bytes:
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_cost_kib,
        parallelism=params.parallelism,
        hash_len=params.hash_len,
        type=Type.ID,
    )


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)
