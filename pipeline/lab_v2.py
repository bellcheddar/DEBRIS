"""Phase 2 of the lab (LAB_PLAN.md): the v2 labels as switches, and how they are scored.

Four switches, each replacing one field of the v1 gold with its v2 label (D39, D40):
  model_type_v2  2a  the explicit design order, and cell_free
  pathways_v2    2b  measured in this study, the three promoted values
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
        out["pathways"] = list(v2["pathways"])
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
            line = f"pathways: {','.join(L.PATHWAYS)},other:<text>"
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
