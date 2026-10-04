from __future__ import annotations

import json

import pytest

from persona.exceptions import InputError, VaultError, WrongPasswordError
from persona.vault import Vault
from tests.conftest import FAST_KDF


def test_placeholders_are_numbered_per_kind_and_stable(vault: Vault) -> None:
    assert vault.placeholder_for("PERSONA", "Mario Rossi") == "[PERSONA_1]"
    assert vault.placeholder_for("PERSONA", "Anna Verdi") == "[PERSONA_2]"
    assert vault.placeholder_for("AZIENDA", "Acme S.r.l.") == "[AZIENDA_1]"
    assert vault.placeholder_for("PERSONA", "Mario Rossi") == "[PERSONA_1]"


def test_identity_is_the_exact_surface_string(vault: Vault) -> None:
    assert vault.placeholder_for("AZIENDA", "ACME S.R.L.") != vault.placeholder_for("AZIENDA", "Acme S.r.l.")


def test_roundtrip_to_disk_keeps_entries_glossary_and_numbering(vault: Vault) -> None:
    vault.placeholder_for("PERSONA", "Mario Rossi")
    vault.placeholder_for("PERSONA", "Rossi", case_sensitive=True)
    vault.add_glossary("Acme S.r.l.", "AZIENDA", ["Acme"])
    vault.save()

    reopened = Vault.open(vault.path, "pw")
    assert reopened.lookup("PERSONA", 1).value == "Mario Rossi"
    assert reopened.lookup("PERSONA", 2).case_sensitive is True
    assert reopened.glossary[0].all_forms == ["Acme S.r.l.", "Acme"]
    assert reopened.placeholder_for("PERSONA", "Anna Verdi") == "[PERSONA_3]"


def test_wrong_password_is_rejected(vault: Vault) -> None:
    with pytest.raises(WrongPasswordError):
        Vault.open(vault.path, "nope")


def test_tampering_is_detected(vault: Vault) -> None:
    envelope = json.loads(vault.path.read_text())
    envelope["ciphertext"] = envelope["ciphertext"][:-4] + ("AAAA" if not envelope["ciphertext"].endswith("AAAA") else "BBBB")
    vault.path.write_text(json.dumps(envelope))
    with pytest.raises(WrongPasswordError):
        Vault.open(vault.path, "pw")


def test_vault_file_does_not_contain_plaintext(vault: Vault) -> None:
    vault.placeholder_for("PERSONA", "Mario Rossi")
    vault.add_glossary("Acme S.r.l.", "AZIENDA")
    vault.save()
    raw = vault.path.read_text()
    assert "Mario" not in raw and "Acme" not in raw


def test_malformed_and_missing_files_give_clean_errors(tmp_path) -> None:
    with pytest.raises(VaultError):
        Vault.open(tmp_path / "missing.vault", "pw")
    broken = tmp_path / "broken.vault"
    broken.write_text("not json")
    with pytest.raises(VaultError):
        Vault.open(broken, "pw")


def test_create_refuses_to_overwrite(vault: Vault) -> None:
    with pytest.raises(VaultError):
        Vault.create(vault.path, "pw", params=FAST_KDF)


def test_unknown_kind_is_rejected(vault: Vault) -> None:
    with pytest.raises(InputError):
        vault.placeholder_for("ROBA", "x")
    with pytest.raises(InputError):
        vault.add_glossary("x", "ROBA")


def test_vault_file_is_private(vault: Vault) -> None:
    assert vault.path.stat().st_mode & 0o077 == 0
