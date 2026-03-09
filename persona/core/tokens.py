from __future__ import annotations

import base64
import hashlib
import hmac

from persona.core.canonicalization import canonicalize_token_material


def stable_token_id(root_key: bytes, entity_type: str, value: str, length: int = 12) -> str:
    digest = hmac.new(root_key, canonicalize_token_material(entity_type, value), hashlib.sha256).digest()
    token = base64.b32encode(digest).decode("ascii").rstrip("=")
    return token[:length]


def deterministic_bytes(root_key: bytes, purpose: str, material: bytes, size: int) -> bytes:
    blocks: list[bytes] = []
    counter = 0
    seed = purpose.encode("utf-8") + b":" + material
    while sum(len(block) for block in blocks) < size:
        counter_bytes = counter.to_bytes(4, "big")
        blocks.append(hmac.new(root_key, seed + b":" + counter_bytes, hashlib.sha256).digest())
        counter += 1
    return b"".join(blocks)[:size]

