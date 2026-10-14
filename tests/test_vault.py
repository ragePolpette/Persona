from __future__ import annotations

import base64
import json
import os
import sys

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from persona import vault as vault_module
from persona.exceptions import InputError, VaultError, WrongPasswordError
from persona.vault import Argon2Params, Vault
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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits do not apply on Windows")
def test_vault_file_is_private(vault: Vault) -> None:
    assert vault.path.stat().st_mode & 0o077 == 0


def _write_envelope(path, **changes) -> None:
    envelope = json.loads(path.read_text())
    for key, value in changes.items():
        if key in vault_module.vars_of(FAST_KDF):
            envelope["kdf"]["params"][key] = value
        else:
            envelope[key] = value
    path.write_text(json.dumps(envelope))


@pytest.mark.parametrize(
    "changes",
    [
        {"memory_cost_kib": 4 * 1024 * 1024},
        {"time_cost": 1000},
        {"parallelism": 64},
        {"hash_len": 16},
        {"time_cost": "3"},
    ],
)
def test_kdf_parameters_from_the_file_are_bounded_before_any_work(vault: Vault, monkeypatch, changes) -> None:
    _write_envelope(vault.path, **changes)

    def no_kdf(*args, **kwargs):
        raise AssertionError("the KDF must not run with out-of-range parameters")

    monkeypatch.setattr(vault_module, "_derive_key", no_kdf)
    with pytest.raises(VaultError, match="KDF parameters"):
        Vault.open(vault.path, "pw")


def test_creating_a_vault_with_out_of_range_parameters_is_refused(tmp_path) -> None:
    with pytest.raises(VaultError, match="out of range"):
        Vault.create(tmp_path / "v.vault", "pw", params=Argon2Params(time_cost=11, memory_cost_kib=8, parallelism=1))


def test_new_vaults_bind_version_and_kdf_parameters_as_associated_data(vault: Vault) -> None:
    envelope = json.loads(vault.path.read_text())
    assert envelope["version"] == 2
    key = vault_module._derive_key("pw", base64.b64decode(envelope["kdf"]["salt"]), FAST_KDF)
    nonce, ciphertext = base64.b64decode(envelope["nonce"]), base64.b64decode(envelope["ciphertext"])
    with pytest.raises(InvalidTag):
        AESGCM(key).decrypt(nonce, ciphertext, b"persona-vault-v1")  # the old constant AAD no longer fits


def test_downgrading_the_version_field_is_detected(vault: Vault) -> None:
    _write_envelope(vault.path, version=1)
    with pytest.raises(WrongPasswordError):
        Vault.open(vault.path, "pw")


def test_version_1_vaults_still_open_and_are_upgraded_on_save(tmp_path) -> None:
    path = tmp_path / "old.vault"
    salt, nonce = os.urandom(16), os.urandom(12)
    payload = {"entries": [{"kind": "PERSONA", "number": 1, "value": "Mario Rossi"}], "glossary": [], "allowlist": []}
    key = vault_module._derive_key("pw", salt, FAST_KDF)
    ciphertext = AESGCM(key).encrypt(nonce, json.dumps(payload).encode(), b"persona-vault-v1")
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "kdf": {"params": vault_module.vars_of(FAST_KDF), "salt": base64.b64encode(salt).decode()},
                "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(ciphertext).decode(),
            }
        )
    )
    old = Vault.open(path, "pw")
    assert old.lookup("PERSONA", 1).value == "Mario Rossi"
    old.save()
    assert json.loads(path.read_text())["version"] == 2
    assert Vault.open(path, "pw").lookup("PERSONA", 1).value == "Mario Rossi"
    assert json.loads(old.backup_paths()[0].read_text())["version"] == 1  # the original file is kept


def test_saving_keeps_rotating_backups_of_the_previous_file(vault: Vault) -> None:
    newest, middle, oldest = vault.backup_paths()
    assert not newest.exists()
    for number in range(1, 6):
        vault.placeholder_for("PERSONA", f"Persona {number}")
        vault.save()
    assert [p.exists() for p in (newest, middle, oldest)] == [True, True, True]
    assert not oldest.with_name(f"{vault.path.name}.bak.3").exists()
    assert Vault.open(newest, "pw").lookup("PERSONA", 4).value == "Persona 4"
    assert Vault.open(newest, "pw").lookup("PERSONA", 5) is None
    assert Vault.open(oldest, "pw").lookup("PERSONA", 3) is None
    if sys.platform != "win32":
        assert newest.stat().st_mode & 0o077 == 0


def test_rekey_changes_the_password_keeps_the_data_and_drops_old_backups(vault: Vault) -> None:
    vault.placeholder_for("PERSONA", "Mario Rossi")
    vault.save()
    assert vault.backup_paths()[0].exists()
    removed = vault.rekey("new-pw", params=FAST_KDF)
    assert removed and not any(p.exists() for p in vault.backup_paths())
    with pytest.raises(WrongPasswordError):
        Vault.open(vault.path, "pw")
    assert Vault.open(vault.path, "new-pw").lookup("PERSONA", 1).value == "Mario Rossi"
