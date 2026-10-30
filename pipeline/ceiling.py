"""The label ceiling (LAB_PLAN.md, Phase 0): how often two labellers agree, field by field.

A model cannot agree with the labels more often than two careful labellers agree with each
other. A sample of the labelled papers is labelled a second time by a different model,
shown exactly what the first labeller was shown and given the same instructions, and the
two label sets are scored against each other with the same `field_metrics` the floors use.

The second labeller is a local Qwen2.5-32B, because no API key is set (LAB_PLAN.md,
decisions). Zero-shot and quantised, it is likely a less careful labeller than the first,
so its disagreements include its own mistakes: the agreement measured here is a pessimistic
estimate of the true ceiling, a level the labels are at least that consistent to.

  pixi run python pipeline/ceiling.py sample
  pixi run python pipeline/ceiling.py label      # needs the GPU to itself
  pixi run python pipeline/ceiling.py summary
  pixi run python pipeline/ceiling.py label-v2   # the same sample under the v2.1 rules (D40)
  pixi run python pipeline/ceiling.py summary-v2
  pixi run python pipeline/ceiling.py label-v2 --rules v2.2   # plus the assay cues (D47)
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c
from pipeline import lab
from pipeline import schema
from pipeline import train as production

SECOND_LABELLER = "mlx-community/Qwen2.5-32B-Instruct-4bit"
N = 150
SEED = 31
HOME = lab.LAB / "ceiling"
SAMPLE = HOME / "sample.json"
LABELS = HOME / "qwen32b.jsonl"
LABELS_V2 = HOME / "qwen32b_v2.jsonl"
RULES = {"v2.1": LABELS_V2, "v2.2": HOME / "qwen32b_v2_2.jsonl", "v2.3": HOME / "qwen32b_v2_3.jsonl"}
# v2.3 (D48): the model-type and polymer boundaries the v2.1 ceiling disagreed on, written
# as the gold already applies them. Kept here until Phase 2 releases labels_v2.py.
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
V2_LISTS = ("pathways", "polymers", "tissues")


def draw_sample(records: list[dict]) -> list[str]:
    """A sample in proportion to the corpus's own mix of relevance and study design, so
    the ceiling it measures is the ceiling of the corpus rather than of its hard cases."""
    if SAMPLE.exists():
        return json.loads(SAMPLE.read_text())["pmids"]
    strata: dict[tuple, list[str]] = collections.defaultdict(list)
    for r in sorted(records, key=lambda r: r["pmid"]):
        strata[(bool(r["tag"]["relevant"]), r["tag"]["model_type"])].append(r["pmid"])
    rng = random.Random(SEED)
    total = len(records)
    picked: list[str] = []
    # Largest remainder, so the sample is exactly N and every stratum gets its share.
    quotas = {k: N * len(v) / total for k, v in strata.items()}
    counts = {k: int(q) for k, q in quotas.items()}
    for k in sorted(quotas, key=lambda k: quotas[k] - counts[k], reverse=True)[:N - sum(counts.values())]:
        counts[k] += 1
    for key in sorted(strata, key=str):
        picked += rng.sample(strata[key], counts[key])
    HOME.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text(json.dumps({"seed": SEED, "n": len(picked), "written": c.now(),
                                  "pmids": sorted(picked)}, indent=1))
    c.log(f"ceiling: sampled {len(picked)} papers")
    return sorted(picked)


def labeller_view(paper: dict) -> str:
    """The article exactly as the first labeller received it (bootstrap_labels.prepare):
    publication types to 120 characters, MeSH to 400, the abstract to 2,400."""
    return (f"TITLE: {paper.get('title', '')}\n"
            f"JOURNAL: {paper.get('journal', '')} ({paper.get('year') or '?'})\n"
            f"TYPES: {(paper.get('pub_types') or '')[:120]}\n"
            f"MESH: {(paper.get('mesh') or '')[:400]}\n"
            f"ABSTRACT: {(paper.get('abstract') or '')[:2400]}")


def label_prompt(paper: dict) -> str:
    return (schema.LABEL_INSTRUCTIONS
            + "\n\nLabel the article below. Return only one JSON object.\n\n"
            + labeller_view(paper))


def label() -> None:
    from mlx_lm import load

    records = {r["pmid"]: r for r in lab.canonical_records()}
    pmids = draw_sample(list(records.values()))
    done = {r["pmid"] for r in c.jsonl_read(LABELS)} if LABELS.exists() else set()
    todo = [p for p in pmids if p not in done]
    if not todo:
        c.log("ceiling: every sampled paper already has its second label")
        return
    c.log(f"ceiling: labelling {len(todo)} papers with {SECOND_LABELLER}")
    model, tokenizer = load(SECOND_LABELLER)
    started = time.monotonic()
    rows = list(c.jsonl_read(LABELS)) if LABELS.exists() else []
    # In batches written as they finish, so an interruption costs one batch.
    for start in range(0, len(todo), lab.SCORE_BATCH):
        chunk = todo[start:start + lab.SCORE_BATCH]
        texts = lab.generate_batch(model, tokenizer,
                                   [label_prompt(records[p]["paper"]) for p in chunk])
        for pmid, text in zip(chunk, texts):
            raw = schema.extract_json(text)
            second, problems, _ = schema.validate(raw)
            rows.append({"pmid": pmid, "gold": records[pmid]["tag"],
                         "pred": second if second is not None else dict(production.UNPARSED),
                         "parsed": raw is not None, "problems": problems})
        c.jsonl_write(LABELS, rows)
    minutes = (time.monotonic() - started) / 60
    c.log(f"ceiling: {len(todo)} second labels in {minutes:.1f} min")


def summary() -> dict | None:
    """Agreement between the two labellers, each field with its 95 % interval."""
    if not LABELS.exists():
        return None
    rows = list(c.jsonl_read(LABELS))
    if not rows:
        return None
    return lab.bootstrap([rows], lambda m: m[0])


# ---------------------------------------------------------------- v2 rules (Phase 2)

def cue_block() -> str:
    """The v2.2 addition: the assays and markers that count as evidence for each pathway."""
    import tomllib

    table = tomllib.loads(MARKERS.read_text())["cues"]
    return ("\n\nv2.2 assay cues. Tag a pathway when the study itself measured one of these "
            "(a null result counts); the same words used only as background do not count:\n"
            + "\n".join(f"  {k}: {v}" for k, v in table.items()))


def instructions(rules: str) -> str:
    from pipeline import labels_v2 as L

    return (L.INSTRUCTIONS + (cue_block() if rules in ("v2.2", "v2.3") else "")
            + (V2_3_RULINGS if rules == "v2.3" else ""))


def open_fields(raw: dict | None) -> dict:
    """Tissues and pathways are open fields, so a bare name outside the vocabulary is the
    labeller's other:<name> without the prefix. Read it so, rather than dropping it: the
    v2.1 ceiling lost 44 tissue values this way (D47)."""
    from pipeline import labels_v2 as L

    raw = dict(raw or {})
    allowed = {"tissues": (L.V2["tissues"], L.V2["synonyms"]["tissues"]),
               "pathways": (L.PATHWAYS, L.V1.get("synonyms", {}).get("pathways", {}))}
    for field, (vocab, synonyms) in allowed.items():
        values = raw.get(field)
        if isinstance(values, list):
            raw[field] = [v if not isinstance(v, str) or v.startswith("other:")
                          or L.canonical(v, vocab, synonyms) else "other:" + v for v in values]
    return raw


def recovered(row: dict) -> dict:
    """A v2.1 second label with the bare names cleaning dropped put back as other:,
    from the problems it recorded, since its raw answer was not kept."""
    from pipeline import labels_v2 as L

    if row.get("raw") is not None or row["pred"] is None:
        return row
    pred = {k: list(v) if isinstance(v, list) else v for k, v in row["pred"].items()}
    for problem in row["problems"]:
        m = re.match(r"(tissues|pathways) '(.+)'$", problem)
        if m:
            v = "other:" + L._key(m.group(2))
            v = L.NORMALISE.get(m.group(1), {}).get(v, v)
            if v not in pred[m.group(1)]:
                pred[m.group(1)].append(v)
    return {**row, "pred": pred}


def v2_prompt(paper: dict, examples: list[tuple[dict, dict]], rules: str = "v2.1") -> str:
    """The instructions and worked examples the first labeller had, then the paper."""
    from pipeline import labels_v2 as L

    shown = "\n\n".join(f"{L.view(p)}\nANSWER: {json.dumps(a)}" for p, a in examples)
    return (instructions(rules) + "\n\nWorked examples:\n\n" + shown
            + "\n\nLabel the paper below. Return only one JSON object.\n\n" + L.view(paper))


def v2_sample() -> tuple[list[str], dict[str, dict], list[tuple[dict, dict]]]:
    """The ceiling sample's papers that have v2 labels, less the worked examples, which
    the second labeller is shown with their answers."""
    from pipeline import labels_v2 as L

    records = {r["pmid"]: r for r in L.records()}
    gold = {r["pmid"]: r for r in c.jsonl_read(L.LABELS)}
    examples = [(records[e["pmid"]]["paper"], {k: e[k] for k in ("pmid",) + L.FIELDS})
                for e in c.jsonl_read(L.HOME / "examples.jsonl") if e["pmid"] in records]
    shown = {p["pmid"] for _, p in examples}
    pmids = [p for p in draw_sample(lab.canonical_records())
             if p in gold and p in records and p not in shown]
    return pmids, {p: dict(records[p], v2=gold[p]) for p in pmids}, examples


def label_v2(rules: str = "v2.1") -> None:
    from mlx_lm import load

    from pipeline import labels_v2 as L

    out = RULES[rules]
    pmids, records, examples = v2_sample()
    done = {r["pmid"] for r in c.jsonl_read(out)} if out.exists() else set()
    todo = [p for p in pmids if p not in done]
    if not todo:
        c.log("ceiling v2: every sampled paper already has its second v2 label")
        return
    c.log(f"ceiling {rules}: labelling {len(todo)} papers with {SECOND_LABELLER}")
    model, tokenizer = load(SECOND_LABELLER)
    started = time.monotonic()
    rows = list(c.jsonl_read(out)) if out.exists() else []
    for start in range(0, len(todo), lab.SCORE_BATCH):
        chunk = todo[start:start + lab.SCORE_BATCH]
        texts = lab.generate_batch(model, tokenizer,
                                   [v2_prompt(records[p]["paper"], examples, rules) for p in chunk])
        for pmid, text in zip(chunk, texts):
            raw = schema.extract_json(text)
            read = open_fields(raw) if rules != "v2.1" else (raw or {})
            second, problems = L.clean(L.normalise({**read, "pmid": pmid}))
            rows.append({"pmid": pmid, "gold": records[pmid]["v2"], "pred": second, "raw": raw,
                         "parsed": raw is not None, "problems": problems})
        c.jsonl_write(out, rows)
    c.log(f"ceiling v2: {len(todo)} second labels in {(time.monotonic() - started) / 60:.1f} min")


def set_counts(gold: list, pred: list) -> tuple[int, int, int]:
    g, p = set(gold or []), set(pred or [])
    return len(g & p), len(p - g), len(g - p)


def agreement_v2(pairs: list[tuple[dict, dict]]) -> dict[str, tuple[float, float, float]]:
    """Agreement field by field, with a 95 % bootstrap interval over papers: model type as
    accuracy, the three lists as micro F1, the same way the lab scores them."""
    import numpy as np

    counts = {f: np.array([set_counts(g.get(f), p.get(f)) for g, p in pairs]) for f in V2_LISTS}
    same = np.array([g.get("model_type") == p.get("model_type") for g, p in pairs])

    def measure(idx) -> dict[str, float]:
        out = {"model_type_accuracy": float(same[idx].mean())}
        for f in V2_LISTS:
            tp, fp, fn = counts[f][idx].sum(axis=0)
            out[f"{f}_f1"] = float(2 * tp / (2 * tp + fp + fn)) if tp + fp + fn else 1.0
        return out

    n = len(pairs)
    point = measure(np.arange(n))
    rng = np.random.default_rng(7)
    draws = collections.defaultdict(list)
    for _ in range(lab.BOOTSTRAP):
        for k, v in measure(rng.integers(0, n, n)).items():
            draws[k].append(v)
    return {k: (point[k], float(np.quantile(draws[k], 0.025)), float(np.quantile(draws[k], 0.975)))
            for k in point}


def summary_v2() -> dict | None:
    """Every v2 ceiling run so far, beside the v1 ceiling on the same papers. Tissues are
    new in v2, so the v1 block leaves them out. The v2.1 run is read with its dropped bare
    names recovered, and also as it was first reported."""
    runs = {rules: [r for r in c.jsonl_read(path) if r["pred"] is not None]
            for rules, path in RULES.items() if path.exists()}
    runs = {k: v for k, v in runs.items() if v}
    if not runs:
        return None
    out = {}
    if "v2.1" in runs:
        out["v2.1 as reported"] = agreement_v2([(r["gold"], r["pred"]) for r in runs["v2.1"]])
        runs["v2.1"] = [recovered(r) for r in runs["v2.1"]]
    for rules, rows in runs.items():
        out[rules] = agreement_v2([(r["gold"], r["pred"]) for r in rows])
    rows = next(iter(runs.values()))
    v1 = {r["pmid"]: r for r in c.jsonl_read(LABELS)} if LABELS.exists() else {}
    both = [r for r in rows if r["pmid"] in v1]
    if both:
        out["v1 same papers"] = {k: v for k, v in agreement_v2(
            [(v1[r["pmid"]]["gold"], v1[r["pmid"]]["pred"]) for r in both]).items()
            if not k.startswith("tissues")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="The label ceiling (LAB_PLAN.md)")
    ap.add_argument("step", choices=["sample", "label", "summary", "label-v2", "summary-v2"])
    ap.add_argument("--rules", choices=sorted(RULES), default="v2.1")
    args = ap.parse_args()
    if args.step == "sample":
        draw_sample(lab.canonical_records())
    elif args.step == "label":
        label()
    elif args.step == "label-v2":
        label_v2(args.rules)
    elif args.step == "summary-v2":
        result = summary_v2()
        if result is None:
            print("no second v2 labels yet")
        for block, metrics in (result or {}).items():
            for k, (point, lo, hi) in metrics.items():
                print(f"{block:<20}{k:<22}{point:.3f}  [{lo:.3f}, {hi:.3f}]")
    else:
        result = summary()
        if result is None:
            print("no second labels yet")
        for k, (point, lo, hi) in (result or {}).items():
            print(f"{k:<24}{point:.3f}  [{lo:.3f}, {hi:.3f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
