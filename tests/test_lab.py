"""The lab must change only what an experiment says it changes.

Every lab result is a comparison, so the harness is only trustworthy if a variant with
every switch off is exactly the current training data, each switch changes one thing, the
folds never reach the test split, and the fast bootstrap scores exactly what the
production scorer scores.
"""
from __future__ import annotations

import collections
import json

import numpy as np
import pytest

from pipeline import common as c
from pipeline import lab
from pipeline import train as production


def record(pmid, relevant=True, model_type="animal_in_vivo", pub_types="Journal Article",
           mesh="Animals; Mice; Microplastics"):
    tag = {"relevant": relevant, "polymers": ["PS"], "size_class": "micro",
           "organ_systems": ["hepatic"], "disease_categories": ["liver_disease"],
           "disease_terms": ["steatosis"], "pathways": ["oxidative_stress"],
           "model_type": model_type, "evidence_rungs": [3], "pet_specific": False,
           "summary": "Polystyrene raised hepatic lipid in mice.", "confidence": 0.8}
    paper = {"pmid": pmid, "title": "A title", "journal": "J Test", "year": 2024,
             "mesh": mesh, "abstract": "An abstract.", "pub_types": pub_types}
    return {"pmid": pmid, "paper": paper, "tag": tag}


def test_every_switch_off_reproduces_the_current_training_rows():
    """The baseline is only a baseline if it is byte for byte what production trains on."""
    if not (c.TRAIN / "train_meta.jsonl").exists():
        pytest.skip("no labelled data in this checkout")
    for split in ("train", "valid"):
        built = sorted(json.dumps(lab.chat_row(r, {}), sort_keys=True, ensure_ascii=False)
                       for r in c.jsonl_read(c.TRAIN / f"{split}_meta.jsonl"))
        actual = sorted(json.dumps(r, sort_keys=True, ensure_ascii=False)
                        for r in c.jsonl_read(c.TRAIN / f"{split}.jsonl"))
        assert built == actual, f"the {split} rows differ from production"


def test_types_switch_adds_what_the_labeller_saw():
    long_mesh = "; ".join(f"Term {i}" for i in range(120))
    paper = record("1", pub_types="Review", mesh=long_mesh)["paper"]
    off, on = lab.user_prompt(paper, {}), lab.user_prompt(paper, {"types": True})
    assert "TYPES:" not in off and "TYPES: Review" in on
    assert long_mesh not in off, "production truncates MeSH at 600 characters"
    assert long_mesh in on
    assert on.replace("TYPES: Review\n", "").replace(long_mesh, long_mesh[:600]) == off


def test_order_switch_moves_keys_and_nothing_else():
    tag = record("1")["tag"]
    reordered = json.loads(lab.target(tag, {"order": True}))
    assert list(reordered)[:3] == ["relevant", "model_type", "evidence_rungs"]
    assert list(reordered)[-1] == "summary"
    assert reordered == tag


def test_drop_confidence_removes_the_field_and_the_answer_still_validates():
    from pipeline import schema
    answer = json.loads(lab.target(record("1")["tag"], {"drop_confidence": True}))
    assert "confidence" not in answer
    tag, problems, _ = schema.validate(answer)
    assert tag is not None


def test_folds_cover_every_paper_once_balance_strata_and_repeat(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "LAB", tmp_path)
    monkeypatch.setattr(lab, "FOLDS", tmp_path / "folds.json")
    monkeypatch.setattr(lab, "test_pmids", lambda: {"t1", "t2"})
    records = ([record(f"a{i}") for i in range(31)]
               + [record(f"c{i}", model_type="cell_line") for i in range(10)]
               + [record(f"n{i}", relevant=False, model_type="not_applicable") for i in range(20)])
    first = lab.assign_folds(records)
    assert set(first) == {r["pmid"] for r in records}
    assert set(first.values()) == {0, 1, 2}
    for prefix in ("a", "c", "n"):
        sizes = collections.Counter(f for p, f in first.items() if p.startswith(prefix))
        assert max(sizes.values()) - min(sizes.values()) <= 1, f"stratum {prefix} unbalanced"
    assert lab.assign_folds(records) == first, "read back, not redrawn"
    assert lab.assign_folds(records, force=True) == first, "and the same when redrawn"


def test_folds_refuse_a_test_split_paper(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "LAB", tmp_path)
    monkeypatch.setattr(lab, "FOLDS", tmp_path / "folds.json")
    monkeypatch.setattr(lab, "test_pmids", lambda: {"x1"})
    with pytest.raises(SystemExit):
        lab.assign_folds([record("x1"), record("x2"), record("x3")])


def test_fast_bootstrap_scores_exactly_what_production_scores():
    rng = np.random.default_rng(3)
    vocab_p, vocab_o = ["PS", "PE", "PET"], ["hepatic", "renal", "immune"]
    rows = []
    for i in range(60):
        gold, pred = record(str(i))["tag"], record(str(i))["tag"]
        gold["relevant"] = bool(rng.random() < 0.7)
        pred["relevant"] = gold["relevant"] if rng.random() < 0.85 else not gold["relevant"]
        for t in (gold, pred):
            t["polymers"] = list(rng.choice(vocab_p, rng.integers(0, 3), replace=False))
            t["organ_systems"] = list(rng.choice(vocab_o, rng.integers(0, 3), replace=False))
            t["evidence_rungs"] = sorted(rng.choice([1, 3, 4, 5], rng.integers(0, 3), replace=False).tolist())
            t["model_type"] = str(rng.choice(["animal_in_vivo", "cell_line"]))
        rows.append({"pmid": str(i), "gold": gold, "pred": pred, "parsed": True})
    stats = lab.checked_stats(rows)        # raises if the two disagree
    fast = lab.stats_metrics(stats, np.arange(len(rows)))
    slow = production.field_metrics([(r["gold"], r["pred"]) for r in rows])
    for k in slow:
        if k in fast:
            assert fast[k] == pytest.approx(slow[k], abs=6e-5), k


def test_phase1_is_a_balanced_half_fraction_with_d_the_product_of_a_b_c():
    levels = np.array([[1 if x else -1 for x in v] for v in lab.PHASE1.values()])
    assert (levels.sum(axis=0) == 0).all(), "every factor on in four runs, off in four"
    assert (levels[:, 3] == levels[:, 0] * levels[:, 1] * levels[:, 2]).all()
    gram = levels.T @ levels
    assert (gram == np.diag(np.diag(gram))).all(), "the factors are orthogonal"


def test_phase1_configuration_one_reuses_the_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "CONFIGS", tmp_path)
    lab.write_phase1(400)
    first = (tmp_path / "phase1-c1.toml").read_text()
    assert 'reuse = "phase0-baseline"' in first
    assert len(list(tmp_path.glob("phase1-c*.toml"))) == 8
