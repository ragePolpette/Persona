from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from persona.core.canonicalization import canonicalize_value
from persona.core.masking import deterministic_mask
from persona.core.placeholders import (
    PLACEHOLDER_PREFIX,
    PLACEHOLDER_SUFFIX,
    build_placeholder,
    compute_placeholder_integrity_tag,
    parse_placeholder,
)
from persona.core.text_ops import strict_restore_text
from persona.core.tokens import stable_token_id
from persona.models.entities import DocumentMetadata, MapEntry
from persona.security.argon2_utils import Argon2Params
from persona.security.keystore import ensure_root_key
from persona.security.map_store import decrypt_map_file, encrypt_map_file


TEST_KEY = b"0123456789abcdef0123456789abcdef"
FAST_PARAMS = Argon2Params(time_cost=1, memory_cost_kib=8192, parallelism=1, hash_len=32)


def test_canonicalize_values() -> None:
    assert canonicalize_value("EMAIL_ADDRESS", "  Alice.Example+Tag@Example.COM ") == "alice.example+tag@example.com"
    assert canonicalize_value("PHONE_NUMBER", " +39 333-123 45 67 ") == "+393331234567"
    assert canonicalize_value("PERSON", "  Mario   Rossi ") == "mario rossi"


def test_stable_token_id_is_keyed_and_deterministic() -> None:
    value = "Alice@example.com"
    token_a = stable_token_id(TEST_KEY, "EMAIL_ADDRESS", value)
    token_b = stable_token_id(TEST_KEY, "EMAIL_ADDRESS", value)
    token_c = stable_token_id(b"other-key-012345678901234567890123", "EMAIL_ADDRESS", value)
    assert token_a == token_b
    assert token_a != token_c


def test_deterministic_mask_preserves_shape() -> None:
    masked = deterministic_mask(TEST_KEY, "EMAIL_ADDRESS", "Alice.Smith99@example.com")
    assert masked != "Alice.Smith99@example.com"
    assert len(masked) == len("Alice.Smith99@example.com")
    assert masked[5] == "."
    assert masked[13] == "@"
    assert masked[-4] == "."


def test_map_encryption_round_trip(tmp_path: Path) -> None:
    map_path = tmp_path / "sample.persona-map.json"
    document = DocumentMetadata(
        source_name="sample.docx",
        source_path="C:/tmp/sample.docx",
        file_format=".docx",
        content_sha256=hashlib.sha256(b"doc").hexdigest(),
    )
    entry = MapEntry(
        token_id="ABCDEF123456",
        entity_type="PERSON",
        original_value="Mario Rossi",
        masked_value="Xxxxx Xxxxx",
        placeholder="[[P1|ABCDEF123456|Xxxxx Xxxxx]]",
        location="body/p0",
        segment_id="seg-1",
        start=0,
        end=11,
    )

    encrypt_map_file(map_path, "correct horse battery staple", document, [entry], params=FAST_PARAMS)
    restored_document, restored_entries = decrypt_map_file(map_path, "correct horse battery staple")

    assert restored_document == document
    assert restored_entries == [entry]


def test_placeholder_validation_round_trip() -> None:
    placeholder = build_placeholder(
        "ABCDEF123456",
        "Alice Example",
        integrity_tag=compute_placeholder_integrity_tag(TEST_KEY, "ABCDEF123456", "Alice Example"),
    )
    parsed = parse_placeholder(placeholder)
    assert placeholder.startswith("[[P2|")
    assert placeholder.endswith(PLACEHOLDER_SUFFIX)
    assert parsed.token_id == "ABCDEF123456"
    assert parsed.masked_value == "Alice Example"


def test_strict_restore_skips_altered_placeholder() -> None:
    entry = MapEntry(
        token_id="ABCDEF123456",
        entity_type="PERSON",
        original_value="Mario Rossi",
        masked_value="Tario Xossi",
        placeholder="[[P1|ABCDEF123456|Tario Xossi]]",
        location="body/p0",
        segment_id="seg-1",
        start=0,
        end=11,
    )
    text = (
        "Approved [[P1|ABCDEF123456|Tario Xossi]] "
        "altered [[P1|ABCDEF123456|Tampered Value]]"
    )

    outcome = strict_restore_text(text, [entry])

    assert "Approved Mario Rossi" in outcome.text
    assert "[[P1|ABCDEF123456|Tampered Value]]" in outcome.text
    assert outcome.stats.restored_count == 1
    assert outcome.stats.warnings


def test_keystore_root_key_persists(tmp_path: Path) -> None:
    keystore_path = tmp_path / "keystore.json"
    root_key_a = ensure_root_key("secret-password", path=keystore_path)
    root_key_b = ensure_root_key("secret-password", path=keystore_path)
    assert root_key_a == root_key_b


def test_placeholder_rejects_reserved_delimiters() -> None:
    with pytest.raises(Exception):
        build_placeholder("TOKEN12345678", "bad|value")
