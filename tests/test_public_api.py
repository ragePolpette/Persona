from __future__ import annotations

from pathlib import Path

import persona
from tests.conftest import FAST_KDF


def test_documented_python_api(tmp_path: Path) -> None:
    vault = persona.Vault.create(tmp_path / "acme.vault", "pw", params=FAST_KDF)
    censored, result = persona.anonymize_text("Il Dott. Mario Rossi scrive a m.rossi@acme.example", vault)
    vault.save()
    assert censored == "Il Dott. [PERSONA_1] scrive a [EMAIL_1]"
    assert result.placeholders["[PERSONA_1]"] == 1
    assert persona.verify({"answer": censored}, vault) == []
    reopened = persona.Vault.open(tmp_path / "acme.vault", "pw")
    report = persona.restore_text("Risposta per [PERSONA_1].", reopened)
    assert report.text == "Risposta per Mario Rossi." and report.clean
