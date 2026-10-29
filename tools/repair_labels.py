"""One-off repair of the bootstrap labels (see DECISIONS.md D22).

Two fields were not functions of the abstract the tagger reads, so no amount of
training could learn them:

  model_type on an irrelevant paper. The enum had no value for "no design worth
  recording", so the labeller guessed one: in_silico on 252 of the 584 irrelevant
  training rows, human_cohort on 150. Over a third of the training set therefore taught
  an arbitrary design, and in_silico became a bin for off-topic work. Every irrelevant
  label is set to the new not_applicable value.

  evidence_rungs containing 5 where the abstract reports no dose information at all.
  Rung 5 is a demonstrated dose-response; 154 of the 245 labels carrying it sat on
  abstracts with no dose phrasing and no second exposure level, and a sample showed
  size-dependent studies read as dose-dependent. Rung 5 is removed from those. The rule
  only removes: an abstract that does report dose information is left as labelled,
  because stating a concentration is not the same as demonstrating a response to it.

  pixi run python tools/repair_labels.py --dry-run

Writes the session label files in place. Re-run ingest and split afterwards; the split
is frozen in data/train/split_assignment.json, so the test set does not move.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c  # noqa: E402

SESSION = c.LABELS / "session"
BOOTSTRAP = c.LABELS / "bootstrap.jsonl"

DOSE_PHRASE = re.compile(
    r"dose-?dependen|concentration-?dependen|dose-?respons|dose[- ]effect|"
    r"(?:increasing|different|various|graded|ascending|escalating|multiple)\s+"
    r"(?:dose|doses|concentration|concentrations|exposure level)|"
    r"(?:low|high)[- ]and[- ](?:low|high)[- ]?dose|low-?, ?medium|"
    r"EC50|LC50|IC50|LOEC|NOEC|benchmark dose|dose range|concentration range|"
    r"ranging from [\d.]+ to [\d.]+", re.I)
CONCENTRATION = re.compile(
    r"\d[\d.,]*\s?(?:m|µ|u|n|p)?g\s?/\s?(?:ml|mL|l|L|kg|g|dl)\b|"
    r"\d[\d.,]*\s?(?:mg|µg|ug|ng|pg)\b|\d[\d.,]*\s?(?:particles|items|MPs)\b|"
    r"\d[\d.,]*\s?(?:%|ppm|ppb)\b", re.I)


def dose_evidence(text: str) -> str | None:
    """How the abstract shows more than one exposure level, if it does at all."""
    if DOSE_PHRASE.search(text):
        return "phrase"
    if len({m.group(0).lower() for m in CONCENTRATION.finditer(text)}) >= 2:
        return "levels"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="repair the bootstrap labels (D22)")
    ap.add_argument("--dry-run", action="store_true", help="count the changes, write nothing")
    args = ap.parse_args()

    papers = {r["pmid"]: r["paper"] for r in c.jsonl_read(BOOTSTRAP)}
    counts: collections.Counter = collections.Counter()
    for path in sorted(SESSION.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        changed = False
        for row in rows:
            paper = papers.get(row["pmid"], {})
            text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
            if not row.get("relevant"):
                if row.get("model_type") != "not_applicable":
                    counts[f"model_type {row.get('model_type')} -> not_applicable"] += 1
                    row["model_type"] = "not_applicable"
                    changed = True
                if row.get("polymers"):
                    counts["polymers emptied on an irrelevant paper"] += 1
                    row["polymers"] = []
                    changed = True
            rungs = row.get("evidence_rungs") or []
            if 5 in rungs and not dose_evidence(text):
                row["evidence_rungs"] = [r for r in rungs if r != 5]
                counts["rung 5 removed, no dose information in the abstract"] += 1
                changed = True
        if changed and not args.dry_run:
            c.jsonl_write(path, rows)
        counts["files changed" if changed else "files unchanged"] += 1

    for key, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{n:5d}  {key}")
    if args.dry_run:
        print("\ndry run: nothing written")


if __name__ == "__main__":
    main()
