from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from persona import vault as vault_module
from persona.vault import Argon2Params, Vault

CORPUS_DIR = Path(__file__).parent / "corpus"
FAST_KDF = Argon2Params(time_cost=1, memory_cost_kib=8, parallelism=1)


@pytest.fixture
def fast_kdf(monkeypatch: pytest.MonkeyPatch) -> Argon2Params:
    """Cheap Argon2 for every vault created without explicit parameters (CLI tests)."""
    monkeypatch.setattr(vault_module, "DEFAULT_PARAMS", FAST_KDF)
    return FAST_KDF


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fast_kdf: Argon2Params) -> Path:
    """An isolated PERSONA_HOME and a password in the environment, for CLI tests."""
    home = tmp_path / "home"
    monkeypatch.setenv("PERSONA_HOME", str(home))
    monkeypatch.setenv("PERSONA_PASSWORD", "pw")
    return home


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    return Vault.create(tmp_path / "test.vault", "pw", params=FAST_KDF)


@dataclass
class CorpusDoc:
    name: str
    text: str
    sensitive: list[dict]
    glossary: list[dict]
    keep: list[str]


def load_corpus() -> list[CorpusDoc]:
    docs = []
    for text_path in sorted(p for p in CORPUS_DIR.iterdir() if p.suffix in {".txt", ".md"}):
        truth = json.loads((CORPUS_DIR / f"{text_path.stem}.truth.json").read_text(encoding="utf-8"))
        docs.append(
            CorpusDoc(
                name=text_path.name,
                text=text_path.read_text(encoding="utf-8"),
                sensitive=truth["sensitive"],
                glossary=truth["glossary"],
                keep=truth["keep"],
            )
        )
    return docs
