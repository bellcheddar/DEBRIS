"""Tag schema: prompt construction and validation, both driven by config/vocab.toml.

The same compact vocabulary block goes into the bootstrap-label prompt, the
fine-tune system prompt and the inference prompt, so the trained tagger sees at
serve time exactly the instruction it was trained on.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pipeline import common as c

V = c.vocab()

LIST_FIELDS = ("polymers", "organ_systems", "disease_categories", "disease_terms",
               "pathways", "evidence_rungs")


def vocabulary_block() -> str:
    """One compact line per field: the whole controlled vocabulary in ~200 tokens."""
    rungs = "; ".join(f"{r['rung']}={r['label'].lower()}" for r in V["rungs"])
    return "\n".join([
        f"polymers: {','.join(V['polymers'])},other:<text>",
        f"size_class: {','.join(V['size_classes'])}",
        f"organ_systems: {','.join(V['organ_systems'])}",
        f"disease_categories: {','.join(V['disease_categories'])}",
        f"pathways: {','.join(V['pathways'])},other:<text>",
        f"model_type: {','.join(V['model_types'])}",
        f"evidence_rungs: {rungs}; reviews use []",
    ])


SYSTEM_PROMPT = (
    "You are DEBRIS, a tagger for micro/nanoplastic disease literature. "
    "Return only JSON matching the schema. Vocabulary:\n" + vocabulary_block()
)

LABEL_INSTRUCTIONS = """Tag the article against the DEBRIS schema.

relevant: true only if the article concerns micro/nanoplastics (or plastic particles,
or their leachates) in relation to a disease state, pathology, toxicity or pathway in
humans, animals, tissue or cells. false for positron emission tomography, polymer
chemistry or recycling, and analytical method development with no health endpoint.
Wildlife surveys and trophic-transfer work (counting particles in whales, seabirds,
fish or invertebrates, or tracing them up a food chain) are false; a controlled
exposure experiment that measures pathology, oxidative stress, immune or genotoxic
endpoints is true whatever the species. Also false for bulk polymer
devices and implants (a Dacron or PET vascular graft, PVC tubing, PMMA cement,
polypropylene mesh) where no particles, wear debris or leachate are studied; for
exposure to monomers or additives alone (vinyl chloride, bisphenol A, phthalates)
with no particle involvement; and for drugs that merely carry a polymer name
(sodium polystyrene sulfonate). Particulate wear debris and degradation products
shed from an implant are relevant. Particles used only as an inert tool are not:
polystyrene beads as a phagocytosis tracer or a calibration standard, polystyrene
spheres as a culture scaffold, a polymer used only to carry a drug. When relevant is false, use
empty lists, disease_categories ["none"], size_class "unspecified", confidence as
usual, and a one-line summary of what the paper is actually about.

polymers: only polymers the study actually used or detected. mixed_unspecified when
the study reports microplastics with no polymer identification.
size_class: nano < 1 um, micro 1 um to 5 mm, mixed, unspecified.
organ_systems and disease_categories: only what the article reports; ["none"] for
disease_categories when no disease endpoint is reported.
disease_terms: up to four free-text clinical terms as written in the article.
pathways: mechanisms the article reports evidence for, not mechanisms it speculates about.
model_type: the single strongest design in the article, and not_applicable when
relevant is false.
evidence_rungs: every rung the article itself supports. 1 detected in human tissue or
fluid; 2 associated with an outcome in a human cohort; 3 reproduced in vivo in animals;
4 mechanism in vitro or ex vivo; 5 dose-response demonstrated, only where the article
reports more than one exposure level or states a dose or concentration dependent effect;
6 effect reversible on particle removal or degradation. Reviews and meta-analyses: [].
pet_specific: true only when PET (polyethylene terephthalate) is specifically studied
or detected, not merely listed among polymers found in the environment.
summary: at most 30 words, British English, no causal claim about humans (use
detected, associated, implicated, reported).
confidence: 0 to 1, your confidence in the whole tag.

Return exactly this shape, no prose, no code fence:
{"relevant":true,"polymers":[],"size_class":"","organ_systems":[],"disease_categories":[],
"disease_terms":[],"pathways":[],"model_type":"","evidence_rungs":[],"pet_specific":false,
"summary":"","confidence":0.0}"""


def user_prompt(paper: dict) -> str:
    mesh = paper.get("mesh") or ""
    if isinstance(mesh, list):
        mesh = "; ".join(mesh)
    abstract = (paper.get("abstract") or "").strip()
    if len(abstract) > 6000:
        abstract = abstract[:6000] + " [truncated]"
    year = paper.get("year") or ""
    return (f"TITLE: {paper.get('title','')}\n"
            f"JOURNAL: {paper.get('journal','')} ({year})\n"
            f"MESH: {mesh[:600]}\n"
            f"ABSTRACT: {abstract}")


# ------------------------------------------------------------------------ validation

def extract_json(text: str) -> dict | None:
    """First JSON object in a model response, tolerating fences and trailing prose."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


SYNONYMS = V.get("synonyms", {})


def _canon(value: str, field: str, allowed: list[str]) -> str | None:
    """Map a near miss (case, separator or a known full name) to a controlled term."""
    norm = value.lower().replace(" ", "_").replace("-", "_").replace("/", "_")
    norm = re.sub(r"_+", "_", norm).strip("_")
    exact = next((a for a in allowed if a.lower() == norm), None)
    if exact:
        return exact
    mapped = SYNONYMS.get(field, {}).get(norm)
    return mapped if mapped in allowed else None


def _clean_list(values: Any, allowed: list[str], open_field: bool,
                candidates: list[tuple[str, str]], field: str) -> list[str]:
    out: list[str] = []
    for v in values if isinstance(values, list) else []:
        if not isinstance(v, str):
            continue
        v = v.strip()
        if v in allowed:
            out.append(v)
        elif v.lower().startswith("other:") and len(v) > 6:
            body = v.split(":", 1)[1].strip()
            if canon := _canon(body, field, allowed):
                out.append(canon)
            elif open_field:
                value = "other:" + body.lower()[:40]
                candidates.append((field, value))
                out.append(value)
        elif v:
            if canon := _canon(v, field, allowed):
                out.append(canon)
            elif open_field:
                value = "other:" + v.lower().replace(" ", "_")[:40]
                candidates.append((field, value))
                out.append(value)
    seen, uniq = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def validate(tag: dict | None) -> tuple[dict | None, list[str], list[tuple[str, str]]]:
    """Coerce a raw tag to the schema.

    Returns (tag or None, problems, vocabulary candidates). A tag is rejected
    outright only when it is not a dict or carries no usable relevance flag.
    """
    problems: list[str] = []
    candidates: list[tuple[str, str]] = []
    if not isinstance(tag, dict):
        return None, ["not a JSON object"], candidates

    if "relevant" not in tag:
        return None, ["missing relevant"], candidates
    relevant = tag["relevant"]
    if isinstance(relevant, str):
        relevant = relevant.strip().lower() in ("true", "yes", "1")
    relevant = bool(relevant)

    out: dict[str, Any] = {"relevant": relevant}
    out["polymers"] = _clean_list(tag.get("polymers"), V["polymers"], True, candidates, "polymers")
    size = (tag.get("size_class") or "unspecified")
    size = size.strip().lower() if isinstance(size, str) else "unspecified"
    if size not in V["size_classes"]:
        problems.append(f"size_class '{size}' not in vocabulary")
        size = "unspecified"
    out["size_class"] = size
    out["organ_systems"] = _clean_list(tag.get("organ_systems"), V["organ_systems"], False,
                                       candidates, "organ_systems")
    out["disease_categories"] = _clean_list(tag.get("disease_categories"), V["disease_categories"],
                                            False, candidates, "disease_categories")
    terms = tag.get("disease_terms")
    out["disease_terms"] = [str(t).strip()[:80] for t in terms[:4]] if isinstance(terms, list) else []
    out["pathways"] = _clean_list(tag.get("pathways"), V["pathways"], True, candidates, "pathways")

    model_type = tag.get("model_type")
    model_type = model_type.strip() if isinstance(model_type, str) else ""
    model_type = _canon(model_type, "model_types", V["model_types"]) or model_type.lower()
    if model_type not in V["model_types"]:
        problems.append(f"model_type '{model_type}' not in vocabulary")
        model_type = "not_applicable" if not relevant else "cell_line"
    if not relevant:
        # An irrelevant paper has no design worth recording, and every list field is
        # already emptied below, so the enum follows them rather than holding a guess.
        model_type = "not_applicable"
    out["model_type"] = model_type

    rungs = tag.get("evidence_rungs")
    clean_rungs = []
    for r in rungs if isinstance(rungs, list) else []:
        try:
            r = int(r)
        except (TypeError, ValueError):
            continue
        if 1 <= r <= 6:
            clean_rungs.append(r)
    if model_type in ("review", "meta_analysis", "not_applicable"):
        clean_rungs = []
    out["evidence_rungs"] = sorted(set(clean_rungs))

    pet = tag.get("pet_specific")
    if isinstance(pet, str):
        pet = pet.strip().lower() in ("true", "yes", "1")
    # Absent flag with PET in the polymer list is read as PET-specific; an explicit
    # false is respected (PET listed only among environmental polymers found).
    out["pet_specific"] = ("PET" in out["polymers"]) if pet is None else bool(pet)

    summary = tag.get("summary") or ""
    summary = re.sub(r"\s+", " ", str(summary)).strip()
    words = summary.split()
    if len(words) > 34:
        summary = " ".join(words[:34])
        problems.append("summary truncated to 34 words")
    out["summary"] = summary

    try:
        conf = float(tag.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
        problems.append("confidence unparseable")
    out["confidence"] = min(max(conf, 0.0), 1.0)

    if relevant:
        if not out["disease_categories"]:
            out["disease_categories"] = ["none"]
        if not out["polymers"]:
            out["polymers"] = ["mixed_unspecified"]
            problems.append("no polymer given; set mixed_unspecified")
        if not out["organ_systems"]:
            problems.append("relevant paper with no organ system")
    else:
        out["polymers"] = []
        out["organ_systems"] = []
        out["pathways"] = []
        out["disease_categories"] = ["none"]
        out["evidence_rungs"] = []
        out["pet_specific"] = False
    # PET-specific is a subset of naming PET (D66): a flag on a paper that does not list
    # PET is a tagging slip, usually a PVC, PS or polyester fibre study, and is dropped.
    if out["pet_specific"] and "PET" not in out["polymers"]:
        out["pet_specific"] = False
        problems.append("pet_specific without PET in polymers; flag dropped")

    return out, problems, candidates


def jaccard(a: list, b: list) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def self_consistency(greedy: dict, sampled: dict | None) -> float:
    """Agreement between the greedy and sampled passes over the list fields."""
    if not sampled:
        return 0.0
    scores = [jaccard(greedy.get(f, []), sampled.get(f, [])) for f in
              ("polymers", "organ_systems", "disease_categories", "pathways", "evidence_rungs")]
    scores.append(1.0 if greedy.get("relevant") == sampled.get("relevant") else 0.0)
    scores.append(1.0 if greedy.get("model_type") == sampled.get("model_type") else 0.0)
    return round(sum(scores) / len(scores), 3)
