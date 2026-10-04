from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from persona.vault import Argon2Params, Vault

CORPUS_DIR = Path(__file__).parent / "corpus"
FAST_KDF = Argon2Params(time_cost=1, memory_cost_kib=8, parallelism=1)


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
