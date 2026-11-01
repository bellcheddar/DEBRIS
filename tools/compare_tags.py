"""Compare a shadow re-tag with the live tags before switching models (D68).

Reads the live database and a re-tagged copy, matches papers by PMID, and reports what
the switch would change: the published counts (on topic, PET specific, human evidence),
flips in relevance and the PET flag, study type and evidence changes, agreement on the
list fields, and a sample of changed papers to read. Never writes to either database.

  pixi run python tools/compare_tags.py data/debris_v3_shadow.sqlite [--sample 12]
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c  # noqa: E402

LISTS = {"polymers": ("tag_polymers", "polymer"), "organ_systems": ("tag_organs", "organ_system"),
         "tissues": ("tag_tissues", "tissue"), "pathways": ("tag_pathways", "pathway"),
         "diseases": ("tag_diseases", "disease_category"), "rungs": ("tag_rungs", "rung")}


def open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def headline(conn) -> dict:
    corpus = c.corpus_clause()
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    base = f"FROM papers p JOIN tags t USING (pmid) WHERE {corpus}"
    return {
        "on topic": one(f"SELECT COUNT(*) {base} AND t.relevant = 1"),
        "PET specific": one(f"SELECT COUNT(*) {base} AND t.relevant = 1 AND t.pet_specific = 1"),
        "names PET": one(f"""SELECT COUNT(*) {base} AND t.relevant = 1
                             AND p.pmid IN (SELECT pmid FROM tag_polymers WHERE polymer = 'PET')"""),
        "human evidence": one(f"""SELECT COUNT(*) {base} AND t.relevant = 1
                                  AND p.pmid IN (SELECT pmid FROM tag_rungs WHERE rung IN (1, 2))"""),
    }


def lists(conn, table: str, column: str) -> dict[str, set]:
    out: dict[str, set] = {}
    for pmid, v in conn.execute(f"SELECT pmid, {column} FROM {table}"):
        out.setdefault(pmid, set()).add(str(v))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("shadow")
    ap.add_argument("--version", default="debris_v3")
    ap.add_argument("--sample", type=int, default=12)
    ap.add_argument("--out", default=None, help="write the report as JSON here too")
    args = ap.parse_args()

    live, shadow = open_ro(c.DB_PATH), open_ro(Path(args.shadow))
    corpus = c.corpus_clause()
    pmids = [r[0] for r in shadow.execute(f"""
        SELECT t.pmid FROM tags t JOIN papers p USING (pmid)
        WHERE {corpus} AND t.model_version = ?""", (args.version,))]
    old = {r["pmid"]: dict(r) for r in live.execute("SELECT * FROM tags")}
    new = {r["pmid"]: dict(r) for r in shadow.execute(
        "SELECT * FROM tags WHERE model_version = ?", (args.version,))}
    both = [p for p in pmids if p in old]

    rel = Counter((old[p]["relevant"], new[p]["relevant"]) for p in both)
    on = [p for p in both if old[p]["relevant"] and new[p]["relevant"]]
    pet = Counter((old[p]["pet_specific"], new[p]["pet_specific"]) for p in on)
    mt = Counter((old[p]["model_type"], new[p]["model_type"]) for p in on
                 if old[p]["model_type"] != new[p]["model_type"])

    agreement = {}
    for name, (table, column) in LISTS.items():
        a, b = lists(live, table, column), lists(shadow, table, column)
        same = jac = 0.0
        for p in on:
            x, y = a.get(p, set()), b.get(p, set())
            same += x == y
            jac += len(x & y) / len(x | y) if x | y else 1.0
        agreement[name] = {"identical": round(same / max(1, len(on)), 3),
                           "mean_jaccard": round(jac / max(1, len(on)), 3)}

    changed = [p for p in on if old[p]["model_type"] != new[p]["model_type"]
               or old[p]["pet_specific"] != new[p]["pet_specific"]]
    flipped = [p for p in both if old[p]["relevant"] != new[p]["relevant"]]
    rng = random.Random(42)
    titles = dict(live.execute("SELECT pmid, title FROM papers"))

    def show(p):
        return {"pmid": p, "title": (titles.get(p) or "")[:110],
                "relevant": [old[p]["relevant"], new[p]["relevant"]],
                "model_type": [old[p]["model_type"], new[p]["model_type"]],
                "pet_specific": [old[p]["pet_specific"], new[p]["pet_specific"]]}

    report = {
        "papers compared": len(both),
        "headline": {"live": headline(live), "shadow": headline(shadow)},
        "relevance (live, shadow)": {f"{a}->{b}": n for (a, b), n in sorted(rel.items())},
        "pet_specific among on-topic (live, shadow)": {f"{a}->{b}": n for (a, b), n in sorted(pet.items())},
        "study type changes": len([p for p in on if old[p]["model_type"] != new[p]["model_type"]]),
        "top study type moves": [f"{a} -> {b}: {n}" for (a, b), n in mt.most_common(10)],
        "list agreement on on-topic papers": agreement,
        "sample relevance flips": [show(p) for p in rng.sample(flipped, min(args.sample, len(flipped)))],
        "sample other changes": [show(p) for p in rng.sample(changed, min(args.sample, len(changed)))],
    }
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
