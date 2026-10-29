"""Tagging priority tiers and the choice of local weights."""
from __future__ import annotations

from pipeline import tag


def paper(title="", abstract="", pub_types="", pmid="1", year=2024) -> dict:
    return {"pmid": pmid, "title": title, "abstract": abstract,
            "pub_types": pub_types, "year": year}


def test_gold_papers_are_tagged_first():
    assert tag.tier_of(paper(pmid="9", title="anything"), {"9"}) == 1


def test_human_tissue_outranks_other_human_mentions():
    tissue = paper(title="Microplastics in carotid plaque", abstract="A patient cohort.")
    other = paper(title="Polystyrene in human serum", abstract="Volunteer samples.")
    assert tag.tier_of(tissue, set()) == 2
    assert tag.tier_of(other, set()) == 3


def test_animal_and_in_vitro_sit_below_human_work():
    assert tag.tier_of(paper(title="PET exposure in mice", abstract="In vivo."), set()) == 4
    assert tag.tier_of(paper(title="Caco-2 uptake of PS beads"), set()) == 4


def test_reviews_go_last_even_when_they_mention_patients():
    review = paper(title="Microplastics and patient outcomes", abstract="A cohort of studies.",
                   pub_types="Review")
    assert tag.tier_of(review, set()) == 5


def test_untiered_papers_fall_to_the_back():
    assert tag.tier_of(paper(title="Polymer degradation in seawater"), set()) == 5


def test_q4_is_preferred_when_both_copies_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(tag.c, "ADAPTERS", tmp_path)
    monkeypatch.setattr(tag.c, "ROOT", tmp_path)
    (tmp_path / "debris_v1_q4").mkdir()
    (tmp_path / "debris_v1_fused").mkdir()
    model, adapter = tag.local_model_choice(None, None, {})
    assert model.endswith("debris_v1_q4")
    assert adapter is None


def test_use_fused_marker_overrides_the_q4_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(tag.c, "ADAPTERS", tmp_path)
    monkeypatch.setattr(tag.c, "ROOT", tmp_path)
    (tmp_path / "debris_v1_q4").mkdir()
    (tmp_path / "debris_v1_fused").mkdir()
    (tmp_path / "USE_FUSED").write_text("q4 lost accuracy\n")
    model, _ = tag.local_model_choice(None, None, {})
    assert model.endswith("debris_v1_fused")


def test_bare_adapter_is_used_when_nothing_has_been_fused(tmp_path, monkeypatch):
    monkeypatch.setattr(tag.c, "ADAPTERS", tmp_path)
    monkeypatch.setattr(tag.c, "ROOT", tmp_path)
    (tmp_path / "debris_v1").mkdir()
    model, adapter = tag.local_model_choice(None, None, {"model_id": "base/model"})
    assert model == "base/model"
    assert adapter.endswith("debris_v1")


def test_an_explicit_model_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(tag.c, "ADAPTERS", tmp_path)
    monkeypatch.setattr(tag.c, "ROOT", tmp_path)
    (tmp_path / "debris_v1_q4").mkdir()
    model, _ = tag.local_model_choice("some/other-model", None, {})
    assert model == "some/other-model"
