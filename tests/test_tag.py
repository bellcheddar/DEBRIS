"""Tagging priority tiers and the choice of local weights."""
from __future__ import annotations

from pipeline import common as c
from pipeline import schema
from pipeline import tag
from tests.conftest import insert_paper as conftest_insert


def paper(title="", abstract="", pub_types="", pmid="1", year=2024,
          hit_strategy="mesh") -> dict:
    return {"pmid": pmid, "title": title, "abstract": abstract,
            "pub_types": pub_types, "year": year, "hit_strategy": hit_strategy}


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


def test_a_paper_that_never_names_a_plastic_goes_behind_the_corpus():
    """The MeSH strategy indexes implant materials, so these arrive looking like cohorts."""
    graft = paper(title="Dacron prosthetic vascular jacket in the Ross operation",
                  abstract="A patient cohort followed for ten years.")
    assert tag.tier_of(graft, set()) == 6
    assert tag.tier_of(paper(title="Wheelchair axle position in C7 tetraplegia"), set()) == 6


def test_the_pet_abbreviation_still_counts_as_a_plastic():
    """`PET exposure in mice` is polyethylene terephthalate and must keep its own tier."""
    assert tag.tier_of(paper(title="PET exposure in mice", abstract="In vivo."), set()) == 4


def test_a_scanner_tells_the_other_pet_apart():
    """Same three letters, and only one of them comes with a radiotracer."""
    assert tag.tier_of(paper(title="Role of PET/CT in diffuse large B-cell lymphoma"), set()) == 6
    assert tag.tier_of(paper(title="FDG PET imaging of aortitis",
                             abstract="A patient cohort."), set()) == 6
    assert not tag.names_a_plastic("68ga-psma-11 pet for renal cell carcinoma")


def test_imaging_used_to_track_particles_is_not_demoted():
    """Five of the nine imaging papers in the corpus are real microplastics work."""
    tracked = paper(title="Tracking ultrafine polystyrene in an asthmatic mouse model "
                          "using positron emission tomography", abstract="In vivo.")
    assert tag.tier_of(tracked, set()) == 4
    assert tag.names_a_plastic("unraveling the in vivo fate of inhaled micro- and "
                               "nanoplastics with pet imaging")


def test_a_deliberate_control_is_tagged_last():
    """Tagged, because validate.py has to show the tagger refusing it, but tagged last."""
    control = paper(title="Microplastics in a patient cohort", hit_strategy="negative")
    assert tag.tier_of(control, set()) == 7
    # a paper the real strategies also found keeps its place
    assert tag.tier_of(paper(title="Microplastics in carotid plaque",
                             abstract="A patient cohort.",
                             hit_strategy="textword,negative"), set()) == 2


def test_a_broken_tagger_stops_the_run_instead_of_failing_the_corpus(corpus, monkeypatch,
                                                                     capsys):
    """One pass takes ten hours, so a tagger that dies at hour two must not mark the rest
    of the corpus failed and then exit zero. That would read as a tagging result rather
    than an outage, and it would put the whole corpus in the review queue."""
    import sqlite3

    conn = sqlite3.connect(corpus)
    with conn:  # enough untagged papers to run past the breaker
        for n in range(2000, 2040):
            conftest_insert(conn, str(n), relevant=None)
    conn.close()

    class BrokenTagger:
        name = "broken"

        def tag_many(self, papers):
            raise RuntimeError("Metal command buffer execution failed")

        def tag(self, paper):
            raise RuntimeError("Metal command buffer execution failed")

    monkeypatch.setattr(tag, "RETRY_PAUSE", 0)
    monkeypatch.setattr(tag, "local_model_choice", lambda *a, **k: ("model", None))
    monkeypatch.setattr(tag, "BatchedTagger", lambda *a, **k: BrokenTagger())
    monkeypatch.setattr("sys.argv", ["tag", "--local"])

    assert tag.main() == 1, "an outage has to be a non-zero exit"

    conn = c.connect(corpus)
    attempted = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE status LIKE 'failed:%'").fetchone()[0]
    assert attempted == tag.CONSECUTIVE_FAILURE_LIMIT, "it stopped at the breaker"
    assert tag.pending(conn, None, None), "the rest is left for the next run to pick up"
    conn.close()


def test_a_blip_costs_the_paper_nothing(corpus, monkeypatch):
    """A cold Space or a dropped connection should be asked a second time, not written off."""
    calls = {"n": 0}

    class FlakyTagger:
        name = "flaky"

        def tag_many(self, papers):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("Metal command buffer timed out")
            return [{"raw": {"relevant": False, "polymers": [], "size_class": "unknown",
                             "organ_systems": [], "disease_categories": ["none"],
                             "disease_terms": [], "pathways": [], "model_type": "not_applicable",
                             "evidence_rungs": [], "pet_specific": False,
                             "summary": "Not relevant.", "confidence": 0.9},
                     "sampled": None, "sampled_run": False, "token_prob": 0.97} for _ in papers]

    monkeypatch.setattr(tag, "RETRY_PAUSE", 0)
    monkeypatch.setattr(tag, "local_model_choice", lambda *a, **k: ("model", None))
    monkeypatch.setattr(tag, "BatchedTagger", lambda *a, **k: FlakyTagger())
    monkeypatch.setattr("sys.argv", ["tag", "--local", "--limit", "1"])

    assert tag.main() == 0
    assert calls["n"] == 2, "asked twice, and the second answer was kept"
    conn = c.connect(corpus)
    assert conn.execute(
        "SELECT COUNT(*) FROM papers WHERE status LIKE 'failed:%'").fetchone()[0] == 0
    row = conn.execute("SELECT self_consistency, token_prob FROM tags "
                       "WHERE token_prob IS NOT NULL").fetchone()
    assert row[0] is None and row[1] == 0.97, "a confident paper skips the sampled pass"
    conn.close()


def test_the_least_confident_share_gets_the_sampled_pass():
    assert tag.least_confident([0.9, 0.2, 0.5, 0.95, 0.4, 0.8], 0.33) == {1, 4}
    assert tag.least_confident([0.9, 0.2], 0.0) == set()
    assert tag.least_confident([0.9], 0.01) == {0}


def test_an_old_database_gains_the_token_prob_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)   # the schema as it was before D45
    conn.executescript(c.SCHEMA.replace(",\n  token_prob REAL", ""))
    assert "token_prob" not in {r[1] for r in conn.execute("PRAGMA table_info(tags)")}
    conn.close()
    c.init_db(path)
    conn = sqlite3.connect(path)
    assert "token_prob" in {r[1] for r in conn.execute("PRAGMA table_info(tags)")}
    conn.close()
