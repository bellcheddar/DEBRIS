"""Where the tagger is wrong, field by field.

Reads the predictions `pipeline/train.py` writes while scoring and reports, per field,
precision and recall and the values most often missed or invented. That is what decides
which rung of the spec 5.5 fallback ladder to climb next, rather than a single F1.

  pixi run errors              # the fused model's test-split predictions
  pixi run errors --label q4
"""
from __future__ import annotations

import argparse
import collections

from pipeline import common as c

MULTI = ("polymers", "organ_systems", "pathways", "disease_categories")


def counts(rows: list[dict], field: str) -> tuple[int, int, int, collections.Counter,
                                                  collections.Counter]:
    tp = fp = fn = 0
    missed: collections.Counter = collections.Counter()
    invented: collections.Counter = collections.Counter()
    for row in rows:
        gold, pred = set(row["gold"].get(field) or []), set(row["pred"].get(field) or [])
        tp += len(gold & pred)
        fp += len(pred - gold)
        fn += len(gold - pred)
        missed.update(gold - pred)
        invented.update(pred - gold)
    return tp, fp, fn, missed, invented


def report(label: str) -> int:
    path = c.TRAIN / f"predictions_{label}.jsonl"
    if not path.exists():
        raise SystemExit(f"no {path.name}: run `pixi run train` first")
    rows = list(c.jsonl_read(path))
    print(f"{len(rows)} papers from {path.name}\n")

    for field in MULTI:
        tp, fp, fn, missed, invented = counts(rows, field)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        print(f"{field}: precision {precision:.3f}, recall {recall:.3f} "
              f"(tp {tp}, fp {fp}, fn {fn})")
        if missed:
            print("   missed:   " + ", ".join(f"{v} x{n}" for v, n in missed.most_common(6)))
        if invented:
            print("   invented: " + ", ".join(f"{v} x{n}" for v, n in invented.most_common(6)))
        print()

    empty_gold = sum(1 for r in rows if not r["gold"].get("pathways"))
    empty_pred = sum(1 for r in rows if not r["pred"].get("pathways"))
    print(f"pathways left empty: gold {empty_gold}, predicted {empty_pred}")

    rel = collections.Counter((bool(r["gold"]["relevant"]), bool(r["pred"]["relevant"]))
                              for r in rows)
    print(f"\nrelevance: true positive {rel[(True, True)]}, false positive "
          f"{rel[(False, True)]}, false negative {rel[(True, False)]}, "
          f"true negative {rel[(False, False)]}")

    types = collections.Counter((r["gold"]["model_type"], r["pred"]["model_type"])
                                for r in rows if r["gold"]["model_type"] != r["pred"]["model_type"])
    print("\nmodel_type confusions (gold -> predicted):")
    for (gold, pred), n in types.most_common(8):
        print(f"   {gold} -> {pred}  x{n}")

    rungs = collections.Counter()
    for r in rows:
        gold, pred = sorted(r["gold"].get("evidence_rungs") or []), \
                     sorted(r["pred"].get("evidence_rungs") or [])
        if gold != pred:
            rungs[(tuple(gold), tuple(pred))] += 1
    print("\nrung sets that differ (gold -> predicted):")
    for (gold, pred), n in rungs.most_common(8):
        print(f"   {list(gold)} -> {list(pred)}  x{n}")

    unparsed = sum(1 for r in rows if not r.get("parsed", True))
    print(f"\nunparseable JSON: {unparsed}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Tagger error analysis")
    ap.add_argument("--label", default="fused")
    args = ap.parse_args()
    return report(args.label)


if __name__ == "__main__":
    raise SystemExit(main())
