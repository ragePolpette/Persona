"""Recall/precision on the synthetic Italian corpus, plus the full loop with a simulated AI.

`SENSITIVE` entries are what must not survive; `keep` entries are business content that must
(amounts, dates, article numbers). The no-glossary thresholds are a ratchet on today's
measured numbers: raise them when detection improves, never lower them.
Run with `-s` to see the table.
"""

from __future__ import annotations

import re
from collections import defaultdict

import pytest

from persona.engine import anonymize_text, verify
from persona.restore import placeholders_in, restore_text
from persona.textnorm import FoldedText
from persona.vault import Vault
from tests.conftest import CorpusDoc, FAST_KDF, load_corpus

CORPUS = load_corpus()
STRUCTURED = {"EMAIL", "TELEFONO", "IBAN", "CF", "PIVA", "INDIRIZZO", "URL"}


def _vault(tmp_path, doc: CorpusDoc, *, glossary: bool) -> Vault:
    vault = Vault.create(tmp_path / f"{doc.name}.vault", "pw", params=FAST_KDF)
    if glossary:
        for item in doc.glossary:
            vault.add_glossary(item["term"], item["kind"], item["aliases"])
    return vault


def _recall(tmp_path, *, glossary: bool) -> tuple[dict[str, list[int]], list[tuple[str, str]]]:
    per_kind: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    missed: list[tuple[str, str]] = []
    for doc in CORPUS:
        censored, _ = anonymize_text(doc.text, _vault(tmp_path, doc, glossary=glossary))
        folded = FoldedText(censored)
        for item in doc.sensitive:
            survived = bool(folded.find_all(item["text"]))
            per_kind[item["kind"]][1] += 1
            per_kind[item["kind"]][0] += not survived
            if survived:
                missed.append((doc.name, item["text"]))
    return per_kind, missed


def test_corpus_is_well_formed() -> None:
    assert len(CORPUS) >= 9
    for doc in CORPUS:
        for item in doc.sensitive:
            assert item["text"] in doc.text, (doc.name, item["text"])


def test_recall_without_glossary(tmp_path, capsys) -> None:
    per_kind, missed = _recall(tmp_path, glossary=False)
    with capsys.disabled():
        print("\nrecall WITHOUT glossary")
        for kind, (hit, total) in sorted(per_kind.items()):
            print(f"  {kind:10} {hit}/{total}")
        print(f"  missed: {len(missed)}")
    for kind in STRUCTURED:
        hit, total = per_kind[kind]
        assert hit == total, f"{kind}: {hit}/{total} (missed: {[m for m in missed]})"
    overall = sum(hit for hit, _ in per_kind.values()), sum(total for _, total in per_kind.values())
    assert overall[0] >= 83, f"overall recall regressed: {overall}"  # ratchet: 83/88 today


def test_recall_with_glossary_is_complete(tmp_path) -> None:
    per_kind, missed = _recall(tmp_path, glossary=True)
    assert missed == []


@pytest.mark.parametrize("glossary", [False, True])
@pytest.mark.parametrize("doc", CORPUS, ids=lambda d: d.name)
def test_business_content_is_not_over_masked(tmp_path, doc: CorpusDoc, glossary: bool) -> None:
    censored, _ = anonymize_text(doc.text, _vault(tmp_path, doc, glossary=glossary))
    for kept in doc.keep:
        assert kept in censored, f"over-masked: {kept!r}"


@pytest.mark.parametrize("glossary", [False, True])
@pytest.mark.parametrize("doc", CORPUS, ids=lambda d: d.name)
def test_safety_check_passes_on_own_output_and_roundtrip_is_exact(tmp_path, doc: CorpusDoc, glossary: bool) -> None:
    vault = _vault(tmp_path, doc, glossary=glossary)
    censored, _ = anonymize_text(doc.text, vault)
    assert verify({"t": censored}, vault) == []
    report = restore_text(censored, vault, expected=placeholders_in(censored))
    assert report.text == doc.text
    assert report.clean and not report.altered


PLACEHOLDER = re.compile(r"\[([A-Z]+)_(\d+)\]")

MANGLINGS = {
    "markdown-escaped": lambda m: f"\\[{m.group(1)}\\_{m.group(2)}\\]",
    "lowercase-spaced": lambda m: f"[{m.group(1).lower()} {m.group(2)}]",
    "parentheses": lambda m: f"({m.group(1)}_{m.group(2)})",
}


@pytest.mark.parametrize("mangling", MANGLINGS)
@pytest.mark.parametrize("doc", CORPUS, ids=lambda d: d.name)
def test_roundtrip_survives_what_an_ai_does_to_placeholders(tmp_path, doc: CorpusDoc, mangling: str) -> None:
    vault = _vault(tmp_path, doc, glossary=True)
    censored, _ = anonymize_text(doc.text, vault)
    mangled = PLACEHOLDER.sub(MANGLINGS[mangling], censored)
    report = restore_text(mangled, vault, expected=placeholders_in(censored))
    assert report.text == doc.text
    assert report.clean
