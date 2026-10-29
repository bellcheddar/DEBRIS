"""The tag schema: vocabulary coverage, validation, repair and self-consistency."""
from __future__ import annotations

import json

from pipeline import common as c
from pipeline import schema


def test_vocabulary_is_complete():
    v = c.vocab()
    for field in ("polymers", "size_classes", "organ_systems", "disease_categories",
                  "pathways", "model_types"):
        assert v[field], f"{field} is empty"
        assert len(set(v[field])) == len(v[field]), f"{field} has duplicates"
    assert [r["rung"] for r in v["rungs"]] == [1, 2, 3, 4, 5, 6]
    # Every controlled term carries a display label, or the app would print raw keys.
    for field, labels in (("polymers", "polymer_labels"), ("organ_systems", "organ_labels"),
                          ("disease_categories", "disease_labels"), ("pathways", "pathway_labels"),
                          ("model_types", "model_type_labels"), ("size_classes", "size_class_labels")):
        missing = [t for t in v[field] if t not in v[labels]]
        assert not missing, f"{labels} is missing {missing}"


def test_synonyms_resolve_to_controlled_terms():
    v = c.vocab()
    for field, mapping in v["synonyms"].items():
        allowed = v[field]
        bad = {k: val for k, val in mapping.items() if val not in allowed}
        assert not bad, f"synonyms.{field} maps to unknown terms: {bad}"


def test_prompt_carries_every_term():
    block = schema.vocabulary_block()
    v = c.vocab()
    for term in v["polymers"] + v["organ_systems"] + v["pathways"] + v["model_types"]:
        assert term in block, f"{term} missing from the prompt vocabulary block"


def test_validate_repairs_near_misses():
    tag, problems, candidates = schema.validate({
        "relevant": "true", "polymers": ["polystyrene", "PET"], "size_class": "Micro",
        "organ_systems": ["Heart"], "disease_categories": ["Atherosclerosis"],
        "disease_terms": ["carotid artery disease"], "pathways": ["ROS", "other: autophagy"],
        "model_type": "Human Tissue", "evidence_rungs": [1, "2", 42],
        "pet_specific": True, "summary": "PET detected in plaque.", "confidence": "0.9"})
    assert tag["polymers"] == ["PS", "PET"]
    assert tag["size_class"] == "micro"
    assert tag["organ_systems"] == ["cardiovascular"]
    assert tag["disease_categories"] == ["atherosclerosis_mace"]
    assert tag["pathways"] == ["oxidative_stress", "other:autophagy"]
    assert tag["model_type"] == "human_tissue"
    assert tag["evidence_rungs"] == [1, 2]
    assert tag["confidence"] == 0.9
    assert ("pathways", "other:autophagy") in candidates
    assert not problems


def test_validate_rejects_unusable_payloads():
    for payload in (None, [], "nope", {"polymers": ["PET"]}):
        tag, problems, _ = schema.validate(payload)
        assert tag is None and problems


def test_irrelevant_papers_are_emptied():
    tag, _, _ = schema.validate({"relevant": False, "polymers": ["PET"],
                                 "organ_systems": ["cardiovascular"], "pathways": ["oxidative_stress"],
                                 "evidence_rungs": [1], "model_type": "review",
                                 "pet_specific": True, "summary": "A PET scan study.",
                                 "confidence": 0.95})
    assert tag["organ_systems"] == [] and tag["pathways"] == []
    assert tag["disease_categories"] == ["none"] and tag["evidence_rungs"] == []
    assert tag["pet_specific"] is False


def test_reviews_carry_no_rungs():
    tag, _, _ = schema.validate({"relevant": True, "polymers": ["PET"], "model_type": "review",
                                 "organ_systems": ["systemic"], "evidence_rungs": [1, 2, 3],
                                 "summary": "A review.", "confidence": 0.8})
    assert tag["evidence_rungs"] == []


def test_extract_json_tolerates_fences_and_prose():
    assert schema.extract_json('```json\n{"relevant": true}\n```') == {"relevant": True}
    assert schema.extract_json('Here you go: {"relevant": false} and that is all') == {"relevant": False}
    assert schema.extract_json("no json here") is None
    nested = schema.extract_json('{"a": {"b": 1}, "c": [1,2]}')
    assert nested == {"a": {"b": 1}, "c": [1, 2]}


def test_self_consistency_scores_agreement():
    a = {"relevant": True, "polymers": ["PET"], "organ_systems": ["cardiovascular"],
         "disease_categories": ["thrombosis"], "pathways": ["oxidative_stress"],
         "evidence_rungs": [1], "model_type": "human_tissue"}
    assert schema.self_consistency(a, a) == 1.0
    assert schema.self_consistency(a, None) == 0.0
    b = dict(a, polymers=["PS"], relevant=False)
    assert 0.0 < schema.self_consistency(a, b) < 1.0


def test_user_prompt_is_bounded():
    prompt = schema.user_prompt({"title": "T", "journal": "J", "year": 2024,
                                 "mesh": "x" * 2000, "abstract": "y" * 20000})
    assert len(prompt) < 7200 and "[truncated]" in prompt
