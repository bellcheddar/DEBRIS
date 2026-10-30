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
