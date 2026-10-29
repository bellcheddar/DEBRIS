"""Tagging priority tiers and the choice of local weights."""
from __future__ import annotations

from pipeline import common as c
from pipeline import schema
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


# -------------------------------------------------- vocabulary candidate counting

def tagged_db(tmp_path):
    db = tmp_path / "t.sqlite"
    c.init_db(db)
    conn = c.connect(db)
    conn.execute("INSERT INTO papers (pmid, doi_status, title, abstract) VALUES ('1','verified','t','a')")
    conn.commit()
    return conn


def tag_with(pathways: list[str]) -> tuple[dict, list[tuple[str, str]]]:
    raw = {"relevant": True, "polymers": ["PET"], "size_class": "microplastic",
           "organ_systems": ["cardiovascular"], "disease_categories": ["atherosclerosis_mace"],
           "disease_terms": ["plaque"], "pathways": pathways, "model_type": "in_vitro",
           "evidence_rungs": [3], "pet_specific": True, "summary": "s", "confidence": 0.9}
    label, _, candidates = schema.validate(raw)
    return label, candidates


def counts(conn) -> dict:
    return {r["value"]: r["count"]
            for r in conn.execute("SELECT value, count FROM vocab_candidates")}


def test_a_candidate_is_counted_once_per_paper(tmp_path):
    conn = tagged_db(tmp_path)
    label, candidates = tag_with(["other:protein_corona"])
    for _ in range(3):
        tag.store(conn, "1", label, label, [], candidates, "test", "v1")
    assert counts(conn) == {"other:protein_corona": 1}


def test_a_retag_moves_the_paper_between_candidates(tmp_path):
    conn = tagged_db(tmp_path)
    first, first_cands = tag_with(["other:protein_corona"])
    tag.store(conn, "1", first, first, [], first_cands, "test", "v1")
    second, second_cands = tag_with(["other:lipid_metabolism"])
    tag.store(conn, "1", second, second, [], second_cands, "test", "v1")
    assert counts(conn) == {"other:lipid_metabolism": 1}


def test_an_in_vocabulary_retag_clears_the_candidate(tmp_path):
    conn = tagged_db(tmp_path)
    label, candidates = tag_with(["other:protein_corona"])
    tag.store(conn, "1", label, label, [], candidates, "test", "v1")
    clean, clean_cands = tag_with(["oxidative_stress"])
    assert clean_cands == []
    tag.store(conn, "1", clean, clean, [], clean_cands, "test", "v1")
    assert counts(conn) == {}


def test_an_out_of_vocabulary_value_queues_the_paper_for_review(tmp_path):
    conn = tagged_db(tmp_path)
    label, candidates = tag_with(["other:protein_corona"])
    reason = tag.store(conn, "1", label, label, [], candidates, "test", "v1")
    assert reason == "out-of-vocabulary value"


def test_dose_evidence_separates_dose_from_size_dependence():
    """Rung 5 needs the abstract to report more than one exposure level. A
    size-dependent study is not a dose-response (DECISIONS.md D22)."""
    from tools.repair_labels import dose_evidence

    assert dose_evidence("exposure caused a dose-dependent rise in ALT")
    assert dose_evidence("mice received various concentrations of polystyrene")
    assert dose_evidence("larvae were exposed to 10 mg/L and 100 mg/L for 21 days")
    assert dose_evidence("the IC50 was 42 ug/mL")
    assert not dose_evidence("particles of different diameters showed size-dependent uptake")
    assert not dose_evidence("mice were exposed to 100 mg/L polystyrene for 28 days")
    assert not dose_evidence("polystyrene nanoplastics induced cardiomyocyte apoptosis")
