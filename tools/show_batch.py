"""Print a labelling batch compactly for the build session (spec 0.2 fallback).

With no ANTHROPIC_API_KEY the build session writes the bootstrap labels itself. Long
abstracts are trimmed from the middle, never the end: the design is stated at the
start and the outcome at the end, and both decide the tags.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCHES = ROOT / "data" / "labels" / "batches"
HEAD, TAIL = 560, 380


def trim(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) <= HEAD + TAIL + 20:
        return text
    return f"{text[:HEAD]} [...] {text[-TAIL:]}"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    brief = "--brief" in sys.argv
    for name in args:
        path = BATCHES / (name if name.endswith(".json") else f"batch_{int(name):03d}.json")
        papers = json.loads(path.read_text())
        print(f"===== {path.stem} ({len(papers)} papers) =====")
        for p in papers:
            mesh = " ".join((p.get("mesh") or "").split())[:170]
            print(f"\n--- {p['pmid']} | {p['journal']} | {p.get('pub_types','')[:60]}")
            print(f"T: {' '.join(p['title'].split())}")
            if mesh:
                print(f"M: {mesh}")
            abstract = p.get("abstract", "")
            print(f"A: {' '.join(abstract.split())[:300]}" if brief else f"A: {trim(abstract)}")
        print()


if __name__ == "__main__":
    main()
