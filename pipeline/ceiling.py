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
"""
from __future__ import annotations

import argparse
import collections
import json
import random
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

def v2_prompt(paper: dict, examples: list[tuple[dict, dict]]) -> str:
    """The v2.1 instructions and worked examples the first labeller had, then the paper."""
    from pipeline import labels_v2 as L

    shown = "\n\n".join(f"{L.view(p)}\nANSWER: {json.dumps(a)}" for p, a in examples)
    return (L.INSTRUCTIONS + "\n\nWorked examples:\n\n" + shown
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


def label_v2() -> None:
    from mlx_lm import load

    from pipeline import labels_v2 as L

    pmids, records, examples = v2_sample()
    done = {r["pmid"] for r in c.jsonl_read(LABELS_V2)} if LABELS_V2.exists() else set()
    todo = [p for p in pmids if p not in done]
    if not todo:
        c.log("ceiling v2: every sampled paper already has its second v2 label")
        return
    c.log(f"ceiling v2: labelling {len(todo)} papers with {SECOND_LABELLER}")
    model, tokenizer = load(SECOND_LABELLER)
    started = time.monotonic()
    rows = list(c.jsonl_read(LABELS_V2)) if LABELS_V2.exists() else []
    for start in range(0, len(todo), lab.SCORE_BATCH):
        chunk = todo[start:start + lab.SCORE_BATCH]
        texts = lab.generate_batch(model, tokenizer,
                                   [v2_prompt(records[p]["paper"], examples) for p in chunk])
        for pmid, text in zip(chunk, texts):
            raw = schema.extract_json(text)
            second, problems = L.clean(L.normalise({**(raw or {}), "pmid": pmid}))
            rows.append({"pmid": pmid, "gold": records[pmid]["v2"], "pred": second,
                         "parsed": raw is not None, "problems": problems})
        c.jsonl_write(LABELS_V2, rows)
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
    """The v2 ceiling, beside the v1 ceiling on the same papers (tissues are new in v2)."""
    if not LABELS_V2.exists():
        return None
    rows = [r for r in c.jsonl_read(LABELS_V2) if r["pred"] is not None]
    if not rows:
        return None
    v1 = {r["pmid"]: r for r in c.jsonl_read(LABELS)} if LABELS.exists() else {}
    both = [r for r in rows if r["pmid"] in v1]
    out = {"papers": len(rows), "v2": agreement_v2([(r["gold"], r["pred"]) for r in rows])}
    if both:
        out["v1_same_papers"] = agreement_v2([(v1[r["pmid"]]["gold"], v1[r["pmid"]]["pred"])
                                              for r in both])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="The label ceiling (LAB_PLAN.md)")
    ap.add_argument("step", choices=["sample", "label", "summary", "label-v2", "summary-v2"])
    args = ap.parse_args()
    if args.step == "sample":
        draw_sample(lab.canonical_records())
    elif args.step == "label":
        label()
    elif args.step == "label-v2":
        label_v2()
    elif args.step == "summary-v2":
        result = summary_v2()
        if result is None:
            print("no second v2 labels yet")
        for block in ("v2", "v1_same_papers"):
            for k, (point, lo, hi) in (result or {}).get(block, {}).items():
                print(f"{block:<16}{k:<22}{point:.3f}  [{lo:.3f}, {hi:.3f}]")
    else:
        result = summary()
        if result is None:
            print("no second labels yet")
        for k, (point, lo, hi) in (result or {}).items():
            print(f"{k:<24}{point:.3f}  [{lo:.3f}, {hi:.3f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
