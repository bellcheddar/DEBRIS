"""Phase 2 switches: the v2 fields replace only what is switched on, and score as designed."""
from __future__ import annotations

from pipeline import lab_v2 as V

TAG = {"relevant": True, "polymers": ["PA"], "size_class": "micro", "organ_systems": ["hepatic"],
       "disease_categories": ["none"], "disease_terms": [], "pathways": ["oxidative_stress"],
       "model_type": "animal_in_vivo", "evidence_rungs": [3], "pet_specific": False,
       "summary": "", "confidence": 0.8}
LABEL = {"pmid": "1", "model_type": "cell_free", "pathways": ["lipid_metabolism"],
         "polymers": ["PA66"], "tissues": ["liver", "frontal_lobe"]}


def test_only_switched_fields_change():
    out = V.apply(TAG, LABEL, {"polymers_v2": True})
    assert out["polymers"] == ["PA66"] and out["pathways"] == ["oxidative_stress"]
    assert "tissues" not in out and out["model_type"] == "animal_in_vivo"


def test_irrelevant_papers_take_empty_v2_fields():
    out = V.gold({**TAG, "relevant": False, "model_type": "not_applicable"}, LABEL)
    assert out["tissues"] == [] and out["polymers"] == [] and out["model_type"] == "not_applicable"


def test_prompt_lists_v2_values_only_when_switched():
    assert V.system_prompt({}) == V.schema.SYSTEM_PROMPT
    p = V.system_prompt({"tissues": True, "polymers_v2": True, "model_type_v2": True})
    assert "tissues: blood," in p and "PA66" in p and "cell_free" in p
    assert "tissues:" not in V.system_prompt({"polymers_v2": True})


def test_validate_keeps_v2_values():
    raw = {**TAG, "model_type": "cell_free", "polymers": ["nylon 66"], "tissues": ["heart", "other:gills"]}
    pred, problems = V.validate(raw, {"model_type_v2": True, "polymers_v2": True, "tissues": True})
    assert pred["model_type"] == "cell_free" and pred["polymers"] == ["PA66"]
    assert pred["tissues"] == ["myocardium", "other:gill"]
    assert not [p for p in problems if "model_type" in p]


def test_parent_level_and_derived_systems():
    gold = V.gold(TAG, LABEL)
    pred = {**gold, "polymers": ["PA"], "tissues": ["brain", "liver"], "organ_systems": []}
    m = V.metrics([(gold, pred)])
    assert m["polymers_parent_f1"] == 1.0 and m["tissues_parent_f1"] == 1.0
    assert m["tissues_f1"] == 0.5
    assert m["organ_systems_derived_f1"] == round(2 / 3, 4)   # hepatic right, neurological extra
    assert m["organ_systems_literal_f1"] == 1.0
    assert m["organ_systems_union_f1"] == m["organ_systems_derived_f1"]


def test_every_tissue_and_other_site_has_a_system_except_muscle():
    for t in V.V2["tissues"]:
        assert (t in V.SYSTEM_OF) == (t != "skeletal_muscle")


def test_report_section_counts_match_metrics_and_pair_arms():
    from pipeline import lab_v2

    g = {"relevant": True, "polymers": ["PA6"], "organ_systems": ["nervous"], "tissues": ["frontal_lobe"]}
    p = {"relevant": True, "polymers": ["PA"], "organ_systems": [], "tissues": ["brain"]}
    rows = {str(i): {"gold": g, "pred": p} for i in range(6)}
    import numpy as np
    counted = lab_v2.f1_counts(lab_v2.paper_counts(list(rows.values())), np.arange(6))
    direct = lab_v2.metrics([(g, p)] * 6)
    for k in lab_v2.V2_METRICS:
        assert abs(counted[k] - direct[k]) < 1e-4, k
    configs = {"base": {"gold": "v2"}, "arm": {"gold": "v2", "compare_to": "base",
                                                "switches": {"tissues": True}}}
    lines = lab_v2.report_section({"base": rows, "arm": rows}, configs, resamples=20)
    text = "\n".join(lines)
    assert "arm vs base" in text and "+0.000" in text and "Per tissue, arm" in text
    assert lab_v2.report_section({"x": rows}, {"x": {}}) == []


def test_ceiling_reads_bare_open_values_as_other_and_recovers_old_rows():
    from pipeline import ceiling as C

    raw = C.open_fields({"tissues": ["gill", "liver"], "pathways": ["lipid_metabolism", "odd_one"]})
    assert raw["tissues"] == ["other:gill", "liver"]
    assert raw["pathways"] == ["lipid_metabolism", "other:odd_one"]
    row = {"pred": {"tissues": ["liver"], "pathways": []}, "problems": ["tissues 'gills'"]}
    assert C.recovered(row)["pred"]["tissues"] == ["liver", "other:gill"]


def test_v2_3_instructions_stack_on_v2_2():
    from pipeline import ceiling as C

    assert "v2.2 assay cues" in C.instructions("v2.3") and "v2.3 rulings" in C.instructions("v2.3")
    assert "v2.3 rulings" not in C.instructions("v2.2")
    assert "v2.2 assay cues" not in C.instructions("v2.1")


def test_the_official_rules_are_v2_3_and_open_fields_keep_bare_names():
    from pipeline import labels_v2 as L

    assert "lipid_metabolism: triglycerides" in L.cue_block()
    assert L.INSTRUCTIONS.startswith(L.BASE_INSTRUCTIONS)
    assert "v2.2 assay cues" in L.INSTRUCTIONS and "v2.3 rulings" in L.INSTRUCTIONS
    row, problems = L.clean({"pmid": "1", "model_type": "cell_line", "polymers": [],
                             "tissues": ["gill", "liver"], "pathways": ["odd one", "other_pathway"]})
    assert row["tissues"] == ["other:gill", "liver"]
    assert row["pathways"] == ["other:odd_one", "other_pathway"] and not problems


def test_rare_pathways_train_and_score_as_one_class():
    from pipeline import labels_v2 as L

    assert L.group_pathways(["oxidative_stress", "other:a", "other:b"]) == ["oxidative_stress", "other_pathway"]
    tag = {"relevant": True, "pathways": [], "polymers": [], "model_type": "cell_line", "evidence_rungs": [3]}
    label = {"model_type": "cell_line", "pathways": ["other:x"], "polymers": [], "tissues": []}
    assert V.apply(tag, label, {"pathways_v2": True})["pathways"] == ["other_pathway"]
    assert "other_pathway" in V.vocabulary_block({"pathways_v2": True})


def test_the_final_split_trains_on_every_lab_paper_and_holds_out_the_test_split():
    from pipeline import lab

    records, folds = lab.final_split()
    test = lab.test_pmids()
    assert {p for p, f in folds.items() if f == 0} == test
    assert sum(1 for f in folds.values() if f == 1) == len(lab.canonical_records())
