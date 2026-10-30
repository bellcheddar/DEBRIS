"""Audit the v2 pathway labels against assay cues (D47). CPU only.

For each paper and each pathway, a cue from config/pathway_markers.toml either appears in
the abstract or does not. Crossing that with the label gives four counts per pathway:

  labelled with a cue        the expected case
  labelled with no cue       possibly tagged from background, or a cue the list lacks
  cue but not labelled       possibly missed, or a cue named as background
  neither

The cue list is a screen, not a labeller: it reads words, not whether the study measured
them. Its use is to show which pathways the instructions leave least determined, and
which papers to read again first.

  pixi run python tools/label_audit.py            # writes data/lab/labels_v2/audit.json
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import common as c  # noqa: E402
from pipeline import labels_v2 as L  # noqa: E402

MARKERS = ROOT / "config" / "pathway_markers.toml"
OUT = L.HOME / "audit.json"


def cues() -> dict[str, re.Pattern]:
    table = tomllib.loads(MARKERS.read_text())["markers"]
    return {k: re.compile("|".join(v), re.I) for k, v in table.items()}


def text_of(paper: dict) -> str:
    return f"{paper.get('title', '')} {paper.get('abstract', '')}"


def audit(labels: list[dict], papers: dict[str, dict], patterns: dict[str, re.Pattern]) -> dict:
    out = {}
    for pathway, pattern in patterns.items():
        counts = {"labelled_cue": 0, "labelled_no_cue": [], "cue_not_labelled": [], "neither": 0}
        for lab in labels:
            if lab["model_type"] in ("review", "meta_analysis"):
                continue
            has_cue = bool(pattern.search(text_of(papers[lab["pmid"]])))
            labelled = pathway in lab["pathways"]
            if labelled and has_cue:
                counts["labelled_cue"] += 1
            elif labelled:
                counts["labelled_no_cue"].append(lab["pmid"])
            elif has_cue:
                counts["cue_not_labelled"].append(lab["pmid"])
            else:
                counts["neither"] += 1
        out[pathway] = counts
    return out


def main() -> int:
    labels = list(c.jsonl_read(L.LABELS))
    papers = {r["pmid"]: r["paper"] for r in L.records()}
    result = audit(labels, papers, cues())
    OUT.write_text(json.dumps({"written": c.now(), "papers": len(labels), "pathways": result}, indent=1))
    print(f"{'pathway':<32}{'labelled':>9}{'with cue':>9}{'no cue':>8}{'cue, unlabelled':>17}")
    for k, v in sorted(result.items(), key=lambda kv: -len(kv[1]["cue_not_labelled"])):
        n = v["labelled_cue"] + len(v["labelled_no_cue"])
        print(f"{k:<32}{n:>9}{v['labelled_cue']:>9}{len(v['labelled_no_cue']):>8}{len(v['cue_not_labelled']):>17}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
