"""Phase 3a of the lab (LAB_PLAN.md): about 300 more labelled papers aimed at what is short.

Training data is short on human tissue and cohort work, PET, the rarer mechanisms and the
sparsest of the 18 tissues (adrenal, thyroid, pancreas, small intestine, adipose, brain
regions). Keyword screens over the untagged verified corpus find candidates for each, a
fixed quota per target, and the build session labels them under the v1 schema plus the
official v2 rules (D50) in one reading. They only ever train: the scored folds and the test
split stay as they are, so a gain here is a gain on representative papers.

  pixi run python pipeline/enrich.py export   # data/lab/enrich/batches/eNN.jsonl
  pixi run python pipeline/enrich.py merge    # validates data/lab/enrich/out/eNN.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c
from pipeline import labels_v2 as L
from pipeline import schema

HOME = c.DATA / "lab" / "enrich"
BATCHES = HOME / "batches"
OUT = HOME / "out"
RECORDS = HOME / "records.jsonl"     # {"pmid", "paper", "tag"} as canonical_records
LABELS = HOME / "labels_v2.jsonl"    # the v2 fields, as labels_v2.LABELS
# Rulings that settle disagreements between batch labellers: {"pmid", "set": {...}, "why"}.
OVERRIDES = HOME / "overrides.jsonl"
BATCH = 25
SEED = 53

# Sparsest targets first, so a paper that hits several counts toward the rarest.
TARGETS = [
    ("adrenal", r"adrenal", 14),
    ("thyroid", r"thyroid", 30),
    ("adipose", r"adipo|white fat|brown fat", 30),
    ("pancreas", r"pancrea|\bislets?\b|\bbeta cells?\b", 30),
    ("small_intestine", r"small intestin|ileum|ileal|jejun|duoden", 30),
    ("brain_region", r"frontal|cortex|hippocamp|medulla|cerebell|striatum", 30),
    ("stomach", r"stomach|gastric", 25),
    ("spleen", r"\bspleen|splen", 20),
    ("uterus", r"\buter|endometri", 20),
    ("human", r"\b(human (placenta|blood|plasma|serum|urine|stool|feces|faeces|breast milk|semen|"
              r"sputum|tissues?|samples?)|patients|cohort|case-control|participants)\b", 40),
    ("pet", r"polyethylene terephthalate|\bPET (micro|nano|particles?)", 25),
    ("rare_pathway", r"epithelial.mesenchymal|platelet|thromb|endocrine disrupt|ferroptosis|pyroptosis", 20),
]

INSTRUCTIONS = (schema.LABEL_INSTRUCTIONS.rsplit("\n\nReturn exactly this shape", 1)[0] + """

For model_type, pathways and polymers use the v2 rules below instead of the lines above,
and add a tissues field under the v2 rules.

""" + L.INSTRUCTIONS.rsplit("\n\nReturn one JSON object per paper", 1)[0] + "\n" + L.cue_block()
    + L.V2_3_RULINGS + """
Return one JSON object per paper, one per line, nothing else:
{"pmid":"...","relevant":true,"polymers":[],"size_class":"","organ_systems":[],
"disease_categories":[],"disease_terms":[],"pathways":[],"model_type":"","tissues":[],
"evidence_rungs":[],"pet_specific":false,"summary":"","confidence":0.0}""")


def labelled() -> set[str]:
    from pipeline import lab

    return {r["pmid"] for r in lab.canonical_records()} | lab.test_pmids()


def select(conn: sqlite3.Connection) -> list[dict]:
    seen = labelled()
    rows = [dict(r) for r in conn.execute(
        """SELECT pmid, title, journal, year, mesh, abstract, pub_types FROM papers
           WHERE doi_status = 'verified' AND retracted = 0 AND abstract != ''
             AND hit_strategy NOT LIKE 'negative%' ORDER BY pmid""")]
    rows = [r for r in rows if r["pmid"] not in seen]
    rng = random.Random(SEED)
    chosen: dict[str, dict] = {}
    for target, pattern, quota in TARGETS:
        hits = [r for r in rows if r["pmid"] not in chosen
                and re.search(pattern, f"{r['title']} {r['abstract']}", re.I)]
        for r in rng.sample(hits, min(quota, len(hits))):
            chosen[r["pmid"]] = {**r, "target": target}
    return list(chosen.values())


def export() -> None:
    conn = c.connect(readonly=True)
    conn.row_factory = sqlite3.Row
    papers = select(conn)
    random.Random(SEED).shuffle(papers)
    BATCHES.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(papers), BATCH):
        c.jsonl_write(BATCHES / f"e{i // BATCH:02d}.jsonl",
                      [{"pmid": p["pmid"], "record": L.view(p)} for p in papers[i:i + BATCH]])
    (HOME / "instructions.txt").write_text(INSTRUCTIONS + "\n")
    c.jsonl_write(HOME / "selected.jsonl", papers)
    counts: dict[str, int] = {}
    for p in papers:
        counts[p["target"]] = counts.get(p["target"], 0) + 1
    (HOME / "export.json").write_text(json.dumps(
        {"written": c.now(), "papers": len(papers), "batch": BATCH, "seed": SEED,
         "targets": counts}, indent=1))
    c.log(f"enrich: exported {len(papers)} papers in {-(-len(papers) // BATCH)} batches; {counts}")


def down_to_v1(v2: dict) -> dict:
    """The v1 spelling of the v2 fields, for arms that do not switch them on."""
    v1 = c.vocab()
    parent = L.V2["polymer_parent"]
    model_type = v2["model_type"] if v2["model_type"] in v1["model_types"] else "in_silico"
    return {"model_type": model_type,
            "polymers": list(dict.fromkeys(parent.get(p, p) for p in v2["polymers"])),
            "pathways": [p if p in v1["pathways"] or p.startswith("other:") else f"other:{p}"
                         for p in v2["pathways"]]}


def merge() -> dict:
    papers = {p["pmid"]: p for p in c.jsonl_read(HOME / "selected.jsonl")}
    records, labels, problems = [], [], {}
    overrides = {o["pmid"]: o["set"] for o in c.jsonl_read(OVERRIDES)} if OVERRIDES.exists() else {}
    for path in sorted(OUT.glob("e*.jsonl")):
        for raw in c.jsonl_read(path):
            pmid = str(raw.get("pmid", ""))
            raw = {**raw, **overrides.get(pmid, {})}
            if pmid not in papers or pmid in {r["pmid"] for r in records}:
                problems[pmid or path.name] = ["unknown or repeated pmid"]
                continue
            v2, v2_problems = L.clean(L.normalise({"pmid": pmid, **{f: raw.get(f) for f in L.FIELDS}}))
            if not raw.get("relevant"):
                v2 = {"pmid": pmid, "model_type": "not_applicable", "pathways": [],
                      "polymers": [], "tissues": []}
            if v2["model_type"] is None:
                problems[pmid] = v2_problems
                continue
            tag, v1_problems, _ = schema.validate({**raw, **down_to_v1(v2)})
            if tag is None:
                problems[pmid] = v1_problems
                continue
            paper = {k: papers[pmid][k] for k in ("pmid", "title", "journal", "year", "mesh",
                                                  "abstract", "pub_types")}
            records.append({"pmid": pmid, "paper": {**paper, "selection": "enrich"}, "tag": tag})
            labels.append(v2)
            if v1_problems or v2_problems:
                problems[pmid] = v1_problems + v2_problems
    c.jsonl_write(RECORDS, records)
    c.jsonl_write(LABELS, labels)
    summary = {"merged": len(records), "relevant": sum(r["tag"]["relevant"] for r in records),
               "selected": len(papers), "problems": problems}
    (HOME / "merge.json").write_text(json.dumps(summary, indent=1))
    c.log(f"enrich: merged {len(records)} of {len(papers)} ({summary['relevant']} relevant), "
          f"{len(problems)} with problems")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stage", choices=["export", "merge", "instructions"])
    stage = ap.parse_args().stage
    if stage == "export":
        export()
    elif stage == "merge":
        print(json.dumps(merge(), indent=1)[:2000])
    else:
        print(INSTRUCTIONS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
