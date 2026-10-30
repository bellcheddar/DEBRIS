"""Phase 2 of the lab (LAB_PLAN.md): the v2 labels as switches, and how they are scored.

Four switches, each replacing one field of the v1 gold with its v2 label (D39, D40):
  model_type_v2  2a  the explicit design order, and cell_free
  pathways_v2    2b  measured in this study, the three promoted values; every other:
                     pathway trains and scores as one other_pathway class (D50)
  polymers_v2    2c  the finest stated type, PA6 and PA66 under PA, PBAT
  tissues        2d  a new field from Liu et al.'s 18, with organ systems derived from it

A definitional change moves the yardstick, so every Phase 2 comparison scores both arms
against the same v2 gold: the Phase 1 recipe (trained on v1) and the switch (trained on v2).
`gold()` builds that yardstick from all four v2 fields whatever the arm trained on.

Organ systems are reported three ways from the same predictions (the 2d hypothesis):
tagged directly, derived from the predicted tissues, and the union of the two. Each is
scored against the v1 organ-system gold, and the derived policy also against systems
derived from the gold tissues, which is the purely literal pipeline.
"""
from __future__ import annotations

import json

from pipeline import common as c
from pipeline import labels_v2 as L
from pipeline import schema
from pipeline import train as production

SWITCHES = ("model_type_v2", "pathways_v2", "polymers_v2", "tissues")
V2 = L.V2
PARENT = {**V2["polymer_parent"], **V2["tissue_parent"]}
SYSTEM_OF = {**V2["tissue_system"], **{f"other:{k}": v for k, v in V2["other_tissue_system"].items()}}


def any_on(switches: dict) -> bool:
    return any(switches.get(s) for s in SWITCHES)


def labels() -> dict[str, dict]:
    if not L.LABELS.exists():
        raise SystemExit("no v2 labels: run `pixi run python pipeline/labels_v2.py merge`")
    return {r["pmid"]: r for r in c.jsonl_read(L.LABELS)}


def empty_v2() -> dict:
    """The v2 fields of a paper that is not relevant: nothing to read, as in v1."""
    return {"model_type": "not_applicable", "pathways": [], "polymers": [], "tissues": []}


def apply(tag: dict, label: dict | None, switches: dict) -> dict:
    """The v1 tag with the switched-on fields replaced by their v2 labels."""
    v2 = label if tag["relevant"] and label else empty_v2()
    out = dict(tag)
    if switches.get("model_type_v2"):
        out["model_type"] = v2["model_type"]
    if switches.get("pathways_v2"):
        out["pathways"] = L.group_pathways(v2["pathways"])
    if switches.get("polymers_v2"):
        out["polymers"] = list(v2["polymers"])
    if switches.get("tissues"):
        out["tissues"] = list(v2["tissues"])
    if out["model_type"] in ("review", "meta_analysis"):
        out["evidence_rungs"] = []
    return out


def gold(tag: dict, label: dict | None) -> dict:
    """The Phase 2 yardstick: every v2 field, whichever arm is being scored."""
    return apply(tag, label, {s: True for s in SWITCHES})


def vocabulary_block(switches: dict) -> str:
    """The v1 vocabulary block with the switched fields' v2 values."""
    lines = schema.vocabulary_block().splitlines()
    out = []
    for line in lines:
        key = line.split(":", 1)[0]
        if key == "polymers" and switches.get("polymers_v2"):
            line = f"polymers: {','.join(V2['polymers'])},other:<text>"
        elif key == "pathways" and switches.get("pathways_v2"):
            line = f"pathways: {','.join(L.PATHWAYS)},{L.OTHER_PATHWAY}"
        elif key == "model_type" and switches.get("model_type_v2"):
            line = f"model_type: {','.join(L.MODEL_TYPES)}"
        out.append(line)
        if key == "organ_systems" and switches.get("tissues"):
            out.append(f"tissues: {','.join(V2['tissues'])},other:<text>")
    return "\n".join(out)


def system_prompt(switches: dict) -> str:
    if not any_on(switches):
        return schema.SYSTEM_PROMPT
    return schema.SYSTEM_PROMPT.split("Vocabulary:\n")[0] + "Vocabulary:\n" + vocabulary_block(switches)


def validate(raw: dict | None, switches: dict) -> tuple[dict | None, list[str]]:
    """v1 validation for the v1 fields, v2 cleaning for the switched ones."""
    pred, problems, _ = schema.validate(raw)
    if pred is None or not any_on(switches):
        return pred, problems
    v2, v2_problems = L.clean(L.normalise({f: raw.get(f) for f in L.FIELDS}))
    if switches.get("model_type_v2") and pred["relevant"] and v2["model_type"]:
        problems = [p for p in problems if not p.startswith("model_type")]
        pred["model_type"] = v2["model_type"]
    for field, switch in (("pathways", "pathways_v2"), ("polymers", "polymers_v2"),
                          ("tissues", "tissues")):
        if switches.get(switch):
            pred[field] = v2[field] if pred["relevant"] else []
    if switches.get("pathways_v2"):
        pred["pathways"] = L.group_pathways(pred["pathways"])
    return pred, problems + [p for p in v2_problems if not p.startswith("model_type")]


def up(values, table=PARENT) -> set:
    return {table.get(v, v) for v in values}


def systems(tissues) -> set:
    return {SYSTEM_OF[t] for t in tissues if t in SYSTEM_OF}


def metrics(pairs: list[tuple[dict, dict]]) -> dict:
    """The Phase 2 fields, on top of field_metrics. A prediction with no tissues field
    (an arm trained without 2d) scores tissues as empty and derives no systems."""
    f1 = lambda sets: round(production.micro_f1(sets), 4)
    get = lambda d, k: d.get(k) or []
    out = {
        "tissues_f1": f1([(set(get(g, "tissues")), set(get(p, "tissues"))) for g, p in pairs]),
        "tissues_parent_f1": f1([(up(get(g, "tissues")), up(get(p, "tissues"))) for g, p in pairs]),
        "polymers_parent_f1": f1([(up(g["polymers"]), up(p["polymers"])) for g, p in pairs]),
        "organ_systems_derived_f1": f1([(set(g["organ_systems"]), systems(get(p, "tissues")))
                                        for g, p in pairs]),
        "organ_systems_union_f1": f1([(set(g["organ_systems"]),
                                       set(p["organ_systems"]) | systems(get(p, "tissues")))
                                      for g, p in pairs]),
        "organ_systems_literal_f1": f1([(systems(get(g, "tissues")), systems(get(p, "tissues")))
                                        for g, p in pairs]),
    }
    rel = [(g, p) for g, p in pairs if g["relevant"]]
    out["tissues_named_rate"] = round(sum(bool(get(p, "tissues")) for _, p in rel) / max(1, len(rel)), 4)
    return out


def per_tissue(pairs: list[tuple[dict, dict]]) -> dict[str, dict]:
    """Recall and support for each of Liu et al.'s 18, since some have a handful of papers."""
    out = {}
    for t in V2["liu_tissues"]:
        gold_has = [(g, p) for g, p in pairs if t in (g.get("tissues") or [])]
        hit = sum(t in (p.get("tissues") or []) for _, p in gold_has)
        out[t] = {"support": len(gold_has), "recall": round(hit / len(gold_has), 3) if gold_has else None}
    return out


def target_json(tag: dict) -> str:
    return json.dumps(tag, separators=(",", ":"), ensure_ascii=False)


# ------------------------------------------------------------------------ report

V2_METRICS = ("tissues_f1", "tissues_parent_f1", "polymers_parent_f1",
              "organ_systems_derived_f1", "organ_systems_union_f1", "organ_systems_literal_f1")


def paper_sets(g: dict, p: dict) -> dict[str, tuple[set, set]]:
    """Gold and predicted sets per paper for each Phase 2 metric, as metrics() forms them."""
    get = lambda d, k: d.get(k) or []
    return {
        "tissues_f1": (set(get(g, "tissues")), set(get(p, "tissues"))),
        "tissues_parent_f1": (up(get(g, "tissues")), up(get(p, "tissues"))),
        "polymers_parent_f1": (up(g["polymers"]), up(p["polymers"])),
        "organ_systems_derived_f1": (set(g["organ_systems"]), systems(get(p, "tissues"))),
        "organ_systems_union_f1": (set(g["organ_systems"]),
                                   set(p["organ_systems"]) | systems(get(p, "tissues"))),
        "organ_systems_literal_f1": (systems(get(g, "tissues")), systems(get(p, "tissues"))),
    }


def paper_counts(rows: list[dict]):
    """(papers, 3) arrays of true positives, false positives and false negatives, so a
    bootstrap resamples counts rather than recomputing sets."""
    import numpy as np

    out = {k: np.zeros((len(rows), 3), dtype=np.int64) for k in V2_METRICS}
    for i, r in enumerate(rows):
        for k, (a, b) in paper_sets(r["gold"], r["pred"]).items():
            out[k][i] = (len(a & b), len(b - a), len(a - b))
    return out


def f1_counts(counts, idx) -> dict[str, float]:
    out = {}
    for k, arr in counts.items():
        tp, fp, fn = arr[idx].sum(axis=0)
        out[k] = 0.0 if tp == 0 and (fp or fn) else (1.0 if tp == 0 else float(2 * tp / (2 * tp + fp + fn)))
    return out


def report_section(results: dict[str, dict], configs: dict[str, dict], resamples: int = 2000) -> list[str]:
    """Phase 2 in LAB_REPORT.md: the v2-only metrics for every arm scored on v2 gold, and
    each arm's paired effect over its reference. Adopting a definition is the owner's call
    (LAB_PLAN.md rule 5), so this measures and does not decide."""
    import numpy as np

    arms = [n for n in results if configs[n].get("gold") == "v2"]
    if not arms:
        return []
    lines = ["## Phase 2: v2 metrics", "",
             "Scored against v2 gold. Organ systems three ways: tagged directly (the floor "
             "metric above), derived from the predicted tissues, and the union; `literal` "
             "compares systems derived from tissues on both sides.", "",
             "| experiment | " + " | ".join(V2_METRICS) + " |", "|---" * (len(V2_METRICS) + 1) + "|"]
    for n in arms:
        rows = [results[n][p] for p in sorted(results[n])]
        m = f1_counts(paper_counts(rows), np.arange(len(rows)))
        lines.append(f"| {n} | " + " | ".join(f"{m[k]:.3f}" for k in V2_METRICS) + " |")
    lines.append("")
    diffs = []
    for n in arms:
        ref = configs[n].get("compare_to")
        if not ref or ref not in results or ref == n:
            continue
        shared = sorted(set(results[n]) & set(results[ref]))
        a = paper_counts([results[ref][p] for p in shared])
        b = paper_counts([results[n][p] for p in shared])
        full = np.arange(len(shared))
        point = {k: f1_counts(b, full)[k] - f1_counts(a, full)[k] for k in V2_METRICS}
        rng = np.random.default_rng(7)
        draws = {k: [] for k in V2_METRICS}
        for _ in range(resamples):
            idx = rng.integers(0, len(shared), len(shared))
            fa, fb = f1_counts(a, idx), f1_counts(b, idx)
            for k in V2_METRICS:
                draws[k].append(fb[k] - fa[k])
        cells = []
        for k in V2_METRICS:
            lo, hi = np.quantile(draws[k], 0.025), np.quantile(draws[k], 0.975)
            cells.append(f"{point[k]:+.3f} [{lo:+.3f}, {hi:+.3f}]" + (" **real**" if lo > 0 or hi < 0 else ""))
        diffs.append(f"| {n} vs {ref} | " + " | ".join(cells) + " |")
    if diffs:
        lines += ["| comparison | " + " | ".join(V2_METRICS) + " |",
                  "|---" * (len(V2_METRICS) + 1) + "|"] + diffs + [""]
    tissue_arms = [n for n in arms if configs[n].get("switches", {}).get("tissues")]
    for n in tissue_arms:
        rows = [results[n][p] for p in sorted(results[n])]
        per = per_tissue([(r["gold"], r["pred"]) for r in rows])
        lines += [f"### Per tissue, {n}", "", "| tissue | " + " | ".join(next(iter(per.values()))) + " |",
                  "|---" * (len(next(iter(per.values()))) + 1) + "|"]
        lines += [f"| {t} | " + " | ".join(str(v) for v in d.values()) + " |" for t, d in per.items()]
        lines.append("")
    return lines
