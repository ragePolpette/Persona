from __future__ import annotations

import string

from persona.core.canonicalization import canonicalize_token_material
from persona.core.tokens import deterministic_bytes

LOWER = string.ascii_lowercase
UPPER = string.ascii_uppercase
DIGITS = string.digits


def _pick_char(pool: str, byte_value: int) -> str:
    return pool[byte_value % len(pool)]


def deterministic_mask(root_key: bytes, entity_type: str, original_value: str) -> str:
    if not original_value:
        return ""
    material = canonicalize_token_material(entity_type, original_value)
    stream = deterministic_bytes(root_key, "mask", material, len(original_value))
    masked: list[str] = []
    for char, entropy in zip(original_value, stream, strict=True):
        if char.islower():
            masked.append(_pick_char(LOWER, entropy))
        elif char.isupper():
            masked.append(_pick_char(UPPER, entropy))
        elif char.isdigit():
            masked.append(_pick_char(DIGITS, entropy))
        elif char.isspace() or not char.isalnum():
            masked.append(char)
        else:
            masked.append("x")
    return "".join(masked)

