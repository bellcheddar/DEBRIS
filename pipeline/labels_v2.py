"""The Phase 2 relabelling pass (LAB_PLAN.md, switches 2a to 2d, and Phase 4's promotions).

Four fields are labelled again under sharper rules, for every v1-relevant paper in the
cross-validation set and the test split: model type (2a), pathways (2b), polymers at the
finest stated level (2c) and a new tissues field from Liu et al.'s 18 (2d). Relevance and
the other fields keep their v1 labels. Irrelevant papers need no second reading: their four
fields are empty and their model type is not_applicable.

There is no API key (LAB_PLAN.md, decisions), so the labeller is the build session, reading
each paper exactly as the v1 labeller did, from batch files this module writes; the 32B
labels the ceiling sample under the same rules afterwards. Thirty papers sit in two batches
each, so the session's agreement with itself is measured too.

  pixi run python pipeline/labels_v2.py export     # data/lab/labels_v2/batches/bNN.jsonl
  pixi run python pipeline/labels_v2.py check      # validates data/lab/labels_v2/out/bNN.jsonl
  pixi run python pipeline/labels_v2.py merge      # data/lab/labels_v2/labels.jsonl, with the
                                                 # v2.1 rulings and overrides.jsonl applied
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import tomllib
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c

V1 = c.vocab()
V2 = tomllib.loads((c.ROOT / "config" / "vocab_v2.toml").read_text())
# The lab imports this module (through lab_v2), so lab itself is imported only where used.
HOME = c.DATA / "lab" / "labels_v2"
BATCHES = HOME / "batches"
OUT = HOME / "out"
LABELS = HOME / "labels.jsonl"
BATCH = 90
OVERLAP = 30
SEED = 39
FIELDS = ("model_type", "pathways", "polymers", "tissues")
# Open fields: a bare name outside the vocabulary is the labeller's other:<name> (D47, D50).
OPEN = ("pathways", "tissues")
PROMOTED_PATHWAYS = ["lipid_metabolism", "er_stress_autophagy", "endocrine_disruption"]
PATHWAYS = list(V1["pathways"]) + PROMOTED_PATHWAYS
OTHER_TISSUES = list(V2["other_tissue_system"])
DESIGN_ORDER = ["meta_analysis", "review", "human_cohort", "human_tissue", "animal_in_vivo",
                "organoid", "human_in_vitro", "cell_line", "cell_free", "in_silico"]
# v2 adds cell_free (D40): laboratory work with no cells or organisms (sorption, surfactant
# films, protein assays, particles released from products), which no v1 value fits.
MODEL_TYPES = [m for m in V1["model_types"] if m != "not_applicable"] + ["cell_free", "not_applicable"]
OVERRIDES = HOME / "overrides.jsonl"

# v2.1 spellings (D40): what the ten labellers wrote for the same thing, mapped to one key.
NORMALISE = {
    "tissues": {"other:gills": "other:gill", "other:digestive_gland": "other:hepatopancreas",
                "other:hemolymph": "blood", "other:haemolymph": "blood",
                "other:head_kidney": "kidney", "other:umbilical_vein": "other:blood_vessel",
                "other:retina": "other:eye"},
    "pathways": {"other:acetylcholinesterase_inhibition": "other:neurotransmitter_disruption",
                 "other:cholinergic_disruption": "other:neurotransmitter_disruption",
                 "other:neurotransmission": "other:neurotransmitter_disruption",
                 "other:neurotoxicity": "other:neurotransmitter_disruption"},
}

BASE_INSTRUCTIONS = f"""Label four fields of a micro/nanoplastic health paper under the DEBRIS v2 rules.
Read only what the record gives (title, journal, publication types, MeSH, abstract). Every
value must be supported by the text; when the text does not say, leave it out.

model_type: one value, the strongest design in the paper, by this order:
  {" > ".join(DESIGN_ORDER)}.
  meta_analysis or review when the publication types or the abstract say the paper is one
  (a review with a small experiment of its own is still a review). human_cohort: an
  association between exposure and an outcome tested in people. human_tissue: particles
  detected or measured in human tissue or fluid, with no outcome association.
  animal_in_vivo: living animals exposed, any species. organoid: organoids or
  organ-on-chip. human_in_vitro: primary human cells, explants or ex vivo human tissue.
  cell_line: an immortalised or named line of any species (HepG2, Caco-2, A549, HUVEC
  lines sold as lines, RAW264.7, BEAS-2B ...), and primary cells from animals.
  in_silico: docking, simulation or modelling only.

pathways: tag a mechanism only where the abstract reports an assay, a marker or a result
  for it in this study (ROS, MDA, SOD for oxidative_stress; NLRP3 or IL-1b measured for
  inflammasome_il1b; a measured cytokine panel or NF-kB activation for nfkb_cytokine ...).
  A mechanism named as background, hypothesis or future work is not tagged. Reviews: [].
  Values: {", ".join(PATHWAYS)}, or other:<short_snake_case> for a measured mechanism with
  no value above.

polymers: every polymer the study used or detected, at the finest type the text states:
  PA6 or PA66 when stated, PA when only polyamide or nylon is said; PBAT, PLA as stated.
  mixed_unspecified when particles are reported with no polymer identified. Polymers only
  listed as found in the environment, or in other studies, are not tagged.
  Values: {", ".join(V2["polymers"])}, or other:<name>.

tissues: the anatomical sites where this study measures particles or measures an effect,
  in any species. Not sites named as background or as routes in general.
  Values: {", ".join(V2["tissues"])}.
  brain or intestine when no region or segment is named; frontal_lobe, medulla_oblongata,
  small_intestine only when named. heart muscle or heart tissue is myocardium. blood when
  particles are measured in blood, plasma or serum, or blood cells are the subject; a serum
  marker read for another organ (ALT for the liver) counts as that organ, not blood. Cells
  count as the tissue they model when the abstract names it (hepatocytes = liver; lung
  epithelial cells = lung). Sites outside these are other:<key>, using exactly these keys
  where they fit: {", ".join(OTHER_TISSUES)}; otherwise other:<short_snake_case>.
  Whole embryos or larvae, or behaviour, with no organ named give no tissue; an organ
  measured inside them does (zebrafish larval brain = brain). A biodistribution study
  lists the organs the abstract names as measured.
  A paper with no anatomical site (an environmental survey, a pure cell-free assay) has [].

v2.1 rulings (settled after the first pass, D40):
- An abstract that plainly reports original data outranks a "Review" publication type.
  Editorials, commentary and news count as review. Reviews take empty pathways, polymers
  and tissues: a review measures nothing.
- cell_free: laboratory work with no cells or organisms (sorption or desorption in
  simulated fluids, surfactant films, purified proteins, particles released from products).
  Ex vivo animal tissue and primary animal cells are cell_line.
- A mechanism that was assayed counts whether or not the result was positive. Inflammation
  with no named marker is not nfkb_cytokine. Transcriptomic enrichment counts as a result.
- leachate_chemical_toxicity: chemicals released from or carried on the particles
  (eluates, additives in the plastic, pre-contaminated particles), not an additive dosed
  separately alongside them.
- Haemolymph and haemocytes are blood. Heart rate or heartbeat counts as myocardium.
  Neurotransmitter or acetylcholinesterase changes are other:neurotransmitter_disruption.

Return one JSON object per paper, one per line, nothing else:
{{"pmid":"...","model_type":"...","pathways":[],"polymers":[],"tissues":[]}}"""

# v2.3 (D48, adopted by the owner D50): the model-type and polymer boundaries the v2.1
# ceiling disagreed on, written as the gold already applies them.
V2_3_RULINGS = """

v2.3 rulings, model type and polymers:
- human_cohort when particle levels or exposure are tested against an outcome or compared
  between people grouped by disease: cases and controls, tumour against para-tumour tissue,
  levels against disease severity or a clinical measure. Controlled human exposure
  experiments and trials are human_cohort too. human_tissue when particles are only
  detected or quantified, even in patients, or when a patient is described in passing.
- human_in_vitro is primary human cells, explants or ex vivo human tissue only (PBMCs,
  freshly isolated or donor cells, HPAEpiC). Every other cultured cell is cell_line: a named
  or immortalised line of any species (THLE-2, BEAS-2B, A549, HepG2, Caco-2, THP-1,
  RAW264.7, GC-2, TM3, EA.hy926, and commercial HUVEC), and primary cells or explants from
  animals (rat cardiomyocytes, trout kidney cells, sheep placental cells). When a study uses
  both a line and primary human cells, it is human_in_vitro by the order above.
- The design is the strongest one the study itself ran. In vivo work mentioned as earlier
  findings or as motivation does not make an in vitro study animal_in_vivo.
- cell_free covers measured release, sorption or desorption in simulated fluids even when a
  model then estimates intake from the measurements; in_silico is modelling with no
  measurement of its own.
- polymers: in a detection study, every polymer the study reports detecting, minor
  fractions included. A study of plastic-related chemicals with no particles has [], not
  mixed_unspecified; mixed_unspecified needs particles with no polymer identified.
"""
MARKERS = c.ROOT / "config" / "pathway_markers.toml"


def cue_block() -> str:
    """The v2.2 addition: the assays and markers that count as evidence for each pathway."""
    table = tomllib.loads(MARKERS.read_text())["cues"]
    return ("\n\nv2.2 assay cues. Tag a pathway when the study itself measured one of these "
            "(a null result counts); the same words used only as background do not count:\n"
            + "\n".join(f"  {k}: {v}" for k, v in table.items()))


# The official rules (owner, D50): v2.1 with the v2.2 assay cues and the v2.3 rulings.
INSTRUCTIONS = BASE_INSTRUCTIONS + cue_block() + V2_3_RULINGS

# Rare pathways (owner, D50): every other:<name> pathway counts as one class for training
# and scoring; the specific name stays in labels.jsonl as the note.
OTHER_PATHWAY = "other_pathway"


def group_pathways(values) -> list[str]:
    return list(dict.fromkeys(OTHER_PATHWAY if v.startswith("other:") else v for v in values or []))



def view(paper: dict) -> str:
    """The paper exactly as the v1 labeller saw it (bootstrap_labels.prepare)."""
    from pipeline.ceiling import labeller_view
    return labeller_view(paper)


def records() -> list[dict]:
    """Every v1-relevant paper, cross-validation and test, with its split."""
    from pipeline import lab

    rows = [dict(r, split="cv") for r in lab.canonical_records()]
    rows += [dict(r, split="test") for r in c.jsonl_read(c.TRAIN / "test_meta.jsonl")]
    return sorted((r for r in rows if r["tag"]["relevant"]), key=lambda r: r["pmid"])


def export() -> None:
    rows = records()
    rng = random.Random(SEED)
    rng.shuffle(rows)
    batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]
    repeat = rng.sample([r for r in rows if r["split"] == "cv"], OVERLAP)
    # Each repeated paper goes into a batch other than its own, so the two readings are
    # independent.
    home_of = {r["pmid"]: i for i, b in enumerate(batches) for r in b}
    for k, r in enumerate(repeat):
        target = (home_of[r["pmid"]] + 1 + k % (len(batches) - 1)) % len(batches)
        batches[target].append(r)
    BATCHES.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(batches):
        rng.shuffle(b)
        c.jsonl_write(BATCHES / f"b{i:02d}.jsonl", [{"pmid": r["pmid"], "record": view(r["paper"])}
                                                   for r in b])
    (HOME / "instructions.txt").write_text(INSTRUCTIONS + "\n")
    (HOME / "export.json").write_text(json.dumps(
        {"written": c.now(), "papers": len(rows), "batches": len(batches), "batch": BATCH,
         "overlap": sorted(r["pmid"] for r in repeat), "seed": SEED}, indent=1))
    c.log(f"labels v2: exported {len(rows)} relevant papers in {len(batches)} batches, "
          f"{OVERLAP} read twice")


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def canonical(value: str, allowed: list[str], synonyms: dict[str, str]) -> str | None:
    """A labelled value in its vocabulary spelling, or None if it is not one."""
    if not isinstance(value, str) or not value.strip():
        return None
    if value.startswith("other:"):
        return "other:" + _key(value[6:]) if _key(value[6:]) else None
    lookup = {_key(a): a for a in allowed}
    k = _key(value)
    return lookup.get(k) or synonyms.get(k)


def clean(row: dict) -> tuple[dict, list[str]]:
    problems = []
    out = {"pmid": str(row.get("pmid", ""))}
    mt = row.get("model_type")
    out["model_type"] = mt if mt in MODEL_TYPES else None
    if out["model_type"] is None:
        problems.append(f"model_type {mt!r}")
    spec = {"pathways": (PATHWAYS, V1.get("synonyms", {}).get("pathways", {})),
            "polymers": (V2["polymers"], {**V1["synonyms"]["polymers"], **V2["synonyms"]["polymers"]}),
            "tissues": (V2["tissues"], V2["synonyms"]["tissues"])}
    for field, (allowed, synonyms) in spec.items():
        values = row.get(field) or []
        if not isinstance(values, list):
            problems.append(f"{field} not a list")
            values = []
        kept = []
        for v in values:
            if field == "pathways" and v == OTHER_PATHWAY:
                canon = OTHER_PATHWAY
            else:
                canon = canonical(v, allowed, synonyms)
            if canon is None and field in OPEN and isinstance(v, str) and _key(v):
                canon = "other:" + _key(v)
            if canon is None:
                problems.append(f"{field} {v!r}")
            elif canon not in kept:
                kept.append(canon)
        out[field] = kept
    return out, problems


def normalise(row: dict) -> dict:
    """The v2.1 rulings that need no rereading: one spelling per site and mechanism, and
    reviews measure nothing."""
    row = dict(row)
    for field, table in NORMALISE.items():
        row[field] = list(dict.fromkeys(table.get(v, v) for v in row.get(field) or []))
    if row.get("model_type") == "review":
        row["pathways"], row["polymers"], row["tissues"] = [], [], []
    return row


def check() -> dict:
    expected = {p.stem: {r["pmid"] for r in c.jsonl_read(p)} for p in sorted(BATCHES.glob("b*.jsonl"))}
    report = {}
    for name, pmids in expected.items():
        path = OUT / f"{name}.jsonl"
        if not path.exists():
            report[name] = "missing"
            continue
        rows = list(c.jsonl_read(path))
        got = {str(r.get("pmid")) for r in rows}
        problems = [p for r in rows for p in clean(r)[1]]
        report[name] = {"rows": len(rows), "absent": sorted(pmids - got),
                        "extra": sorted(got - pmids), "problems": problems}
    return report


def merge() -> None:
    """One label per paper. A paper read twice keeps its home-batch reading; the other is
    kept apart for the self-agreement figure."""
    meta = json.loads((HOME / "export.json").read_text())
    overlap = set(meta["overlap"])
    seen: dict[str, dict] = {}
    second: list[dict] = []
    for path in sorted(OUT.glob("b*.jsonl")):
        for row in c.jsonl_read(path):
            label, problems = clean(normalise(row))
            label["batch"] = path.stem
            label["problems"] = problems
            if label["pmid"] in seen:
                second.append(label)
            else:
                seen[label["pmid"]] = label
    overrides = {r["pmid"]: r for r in c.jsonl_read(OVERRIDES)} if OVERRIDES.exists() else {}
    for pmid, row in overrides.items():
        label, problems = clean(normalise(row))
        seen[pmid] = {**label, "batch": "override", "reason": row.get("reason", ""),
                      "problems": problems}
    c.jsonl_write(LABELS, [seen[k] for k in sorted(seen)])
    c.jsonl_write(HOME / "second_reading.jsonl", sorted(second, key=lambda r: r["pmid"]))
    c.log(f"labels v2: merged {len(seen)} labels, {len(second)} second readings of "
          f"{len(overlap)} repeated papers")


def main() -> int:
    ap = argparse.ArgumentParser(description="The Phase 2 relabelling pass")
    ap.add_argument("step", choices=["export", "check", "merge", "instructions"])
    args = ap.parse_args()
    if args.step == "export":
        export()
    elif args.step == "check":
        print(json.dumps(check(), indent=1))
    elif args.step == "merge":
        merge()
    else:
        print(INSTRUCTIONS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
