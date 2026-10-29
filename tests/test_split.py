"""The train, valid and test assignment, which is frozen once drawn (DECISIONS.md D22)."""
from __future__ import annotations

import json
import random

from pipeline import bootstrap_labels as bl
from pipeline import common as c


def label(pmid: str, relevant: bool, model_type: str) -> dict:
    return {"pmid": pmid,
            "paper": {"pmid": pmid, "title": f"Paper {pmid}", "abstract": "An abstract.",
                      "mesh": "Microplastics", "year": 2024},
            "tag": {"relevant": relevant, "polymers": ["PS"], "size_class": "micro",
                    "organ_systems": ["hepatic"], "disease_categories": ["none"],
                    "disease_terms": [], "pathways": ["oxidative_stress"],
                    "model_type": model_type, "evidence_rungs": [3], "pet_specific": False,
                    "summary": "Reported.", "confidence": 0.9}}


def corpus(n: int = 60) -> list[dict]:
    rows = []
    for i in range(n):
        relevant = i % 2 == 0
        rows.append(label(f"{9000 + i}", relevant,
                          "animal_in_vivo" if relevant else "not_applicable"))
    return rows


def run_split(tmp_path, monkeypatch, rows, **kwargs):
    monkeypatch.setattr(c, "TRAIN", tmp_path)
    monkeypatch.setattr(bl, "ASSIGNMENT", tmp_path / "split_assignment.json")
    monkeypatch.setattr(bl, "BOOTSTRAP", tmp_path / "bootstrap.jsonl")
    c.jsonl_write(bl.BOOTSTRAP, rows)
    bl.split(**kwargs)
    return {name: [r["pmid"] for r in c.jsonl_read(tmp_path / f"{name}_meta.jsonl")]
            for name in ("train", "valid", "test")}


def test_every_paper_lands_in_exactly_one_split(tmp_path, monkeypatch):
    rows = corpus()
    splits = run_split(tmp_path, monkeypatch, rows)
    assigned = splits["train"] + splits["valid"] + splits["test"]
    assert sorted(assigned) == sorted(r["pmid"] for r in rows)
    assert len(set(assigned)) == len(assigned)


def test_relabelling_does_not_move_papers_between_splits(tmp_path, monkeypatch):
    """The repair in D22 changed the strata the split is drawn on. Without the freeze the
    test set would move with them and two runs' metrics would not be comparable."""
    rows = corpus()
    first = run_split(tmp_path, monkeypatch, rows)
    for row in rows:
        if not row["tag"]["relevant"]:
            row["tag"]["model_type"] = "in_silico"   # the pre-repair labelling
        row["tag"]["evidence_rungs"] = [3, 5]
    second = run_split(tmp_path, monkeypatch, rows)
    for name in ("train", "valid", "test"):
        assert set(second[name]) == set(first[name])
    assert second == first, "the order written should reproduce too"


def test_resplit_draws_again(tmp_path, monkeypatch):
    rows = corpus()
    first = run_split(tmp_path, monkeypatch, rows)
    for i, row in enumerate(rows):
        if not row["tag"]["relevant"]:
            # The pre-repair labelling, which spread the irrelevant papers over several
            # strata and so over a different draw.
            row["tag"]["model_type"] = "in_silico" if i % 4 == 1 else "human_cohort"
    second = run_split(tmp_path, monkeypatch, rows, resplit=True)
    assert sorted(second["train"] + second["valid"] + second["test"]) == \
        sorted(first["train"] + first["valid"] + first["test"])
    assert second != first


def test_papers_labelled_later_join_the_frozen_split(tmp_path, monkeypatch):
    rows = corpus()
    first = run_split(tmp_path, monkeypatch, rows)
    extra = [label(f"{9500 + i}", i % 2 == 0,
                   "cell_line" if i % 2 == 0 else "not_applicable") for i in range(20)]
    second = run_split(tmp_path, monkeypatch, rows + extra)
    for name in ("train", "valid", "test"):
        assert set(first[name]) <= set(second[name])
    assert len(second["train"] + second["valid"] + second["test"]) == len(rows) + len(extra)


def test_draw_split_is_deterministic_for_a_seed():
    rows = corpus()
    a = bl.draw_split(list(rows), random.Random(bl.SEED))
    b = bl.draw_split(list(rows), random.Random(bl.SEED))
    assert a == b
