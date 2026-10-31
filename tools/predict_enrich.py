"""The production tagger's reading of the Phase 3a papers, to find where the batch labellers'
study-type calls differ from the conventions the gold follows (D58).

  pixi run python tools/predict_enrich.py   # data/lab/enrich/predicted.jsonl
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c  # noqa: E402
from pipeline import tag  # noqa: E402

HOME = c.DATA / "lab" / "enrich"


def main() -> int:
    cfg = tomllib.loads((c.ROOT / "config" / "tuning.toml").read_text()).get("tag", {})
    tagger = tag.BatchedTagger(cfg["model"], cfg.get("adapter"), {**cfg, "sampled_fraction": 0},
                               tag.Recipe("v2"))
    records = list(c.jsonl_read(HOME / "records.jsonl"))
    out = []
    for r, res in zip(records, tagger.tag_many([r["paper"] for r in records])):
        pred, _, _ = tag.Recipe("v2").validate(res["raw"])
        out.append({"pmid": r["pmid"], "pred": pred, "token_prob": res["token_prob"]})
    c.jsonl_write(HOME / "predicted.jsonl", out)
    c.log(f"predict enrich: {len(out)} papers read by debris_v2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
